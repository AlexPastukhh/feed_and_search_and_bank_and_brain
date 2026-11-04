"""Capability-level dispatch independent of any tool's transport or storage."""
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from info_hub.action_workflow import (
    WorkflowValidationError, require_executable_workflow,
)


@dataclass(frozen=True)
class StepOutcome:
    """A normalized tool result for a future persisted ActionRun/StepRun."""

    step_id: str
    capability: str
    tool: str
    status: str
    external_run_ref: str | None
    details: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "capability": self.capability,
            "tool": self.tool,
            "status": self.status,
            "external_run_ref": self.external_run_ref,
            "details": dict(self.details),
        }


class ToolExecutionError(RuntimeError):
    """An operation could not be completed; optionally carries an external run reference."""

    def __init__(
        self, code: str, message: str, *,
        tool: str | None = None, external_run_ref: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.tool = tool
        self.external_run_ref = external_run_ref


class CapabilityAdapter(Protocol):
    @property
    def name(self) -> str: ...

    @property
    def capabilities(self) -> frozenset[str]: ...

    def validate_parameters(self, capability: str, parameters: Mapping[str, Any]) -> None:
        """Check local capability availability without performing a network operation."""
        ...

    def execute(
        self, capability: str, parameters: Mapping[str, Any],
        on_external_ref: Callable[[str], None] | None = None,
    ) -> dict[str, Any]:
        """Return a completed result; report external reference as soon as known."""
        ...


class CapabilityBroker:
    """Explicit tool name + capability selection. No AI planning in V1."""

    def __init__(self, adapters: list[CapabilityAdapter]) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}
        for adapter in adapters:
            if adapter.name in self._adapters:
                raise ValueError(f"Duplicate tool adapter: {adapter.name}")
            self._adapters[adapter.name] = adapter

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(
            capability for adapter in self._adapters.values()
            for capability in adapter.capabilities
        )

    def _adapter_for(self, step: Mapping[str, Any]) -> CapabilityAdapter:
        tool = step["tool"]
        adapter = self._adapters.get(tool)
        if adapter is None:
            raise ToolExecutionError(
                "tool_unavailable", f"Tool is not available: {tool}", tool=tool,
            )
        if step["capability"] not in adapter.capabilities:
            raise ToolExecutionError(
                "capability_unavailable",
                f"Tool {tool} does not implement {step['capability']}",
                tool=tool,
            )
        return adapter

    def preflight(self, definition: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Validate all explicit tool/operation/argument choices before any side effects."""
        validated = require_executable_workflow(definition, self.capabilities)
        steps = validated["workflow"]["steps"]
        for step in steps:
            self._adapter_for(step).validate_parameters(
                step["capability"], step["with"],
            )
        return steps

    def tool_name_for(self, step: Mapping[str, Any]) -> str:
        return self._adapter_for(step).name

    def dispatch_step(
        self, step: Mapping[str, Any],
        on_external_ref: Callable[[str], None] | None = None,
    ) -> StepOutcome:
        """Validate a V1 step before handing it to any registered external tool."""
        if not isinstance(step, Mapping):
            raise WorkflowValidationError("Step must be an object")
        definition = require_executable_workflow(
            {
                "name": "broker dispatch",
                "instruction": "Execute one validated step",
                "workflow": {"schema": 1, "steps": [dict(step)]},
            },
            self.capabilities,
        )
        normalized = definition["workflow"]["steps"][0]
        capability = normalized["capability"]
        adapter = self._adapter_for(normalized)
        adapter.validate_parameters(capability, normalized["with"])
        result = adapter.execute(
            capability, normalized["with"], on_external_ref=on_external_ref,
        )
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise ToolExecutionError(
                "invalid_tool_result",
                f"Tool {adapter.name} did not return a completed result",
                tool=adapter.name,
            )
        external_ref = result.get("external_run_ref")
        if external_ref is not None and not isinstance(external_ref, str):
            raise ToolExecutionError(
                "invalid_tool_result", "Tool returned an invalid external reference",
                tool=adapter.name,
            )
        return StepOutcome(
            step_id=normalized["id"], capability=capability, tool=adapter.name,
            status="completed", external_run_ref=external_ref,
            details={k: v for k, v in result.items()
                     if k not in ("status", "external_run_ref")},
        )



def configured_broker() -> CapabilityBroker:
    """Load allowed adapters from runtime settings; Action YAML selects among them."""
    from info_hub.feedbrain_adapter import FeedbrainSyncAdapter
    from info_hub.settings import get_settings

    settings = get_settings()
    adapter = FeedbrainSyncAdapter(base_url=settings.action_feedbrain_url)
    return CapabilityBroker([adapter])
