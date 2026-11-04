"""Capability-level dispatch independent of any tool's transport or storage."""
from collections.abc import Mapping
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

    def execute(self, capability: str, parameters: Mapping[str, Any]) -> dict[str, Any]:
        """Return a completed normalized result; raise ToolExecutionError otherwise."""
        ...


class CapabilityBroker:
    """Explicit capability-to-adapter bindings. No tool discovery or AI planning in V1."""

    def __init__(self, adapters: list[CapabilityAdapter]) -> None:
        self._adapters: dict[str, CapabilityAdapter] = {}
        for adapter in adapters:
            for capability in adapter.capabilities:
                if capability in self._adapters:
                    raise ValueError(f"Duplicate adapter for capability: {capability}")
                self._adapters[capability] = adapter

    @property
    def capabilities(self) -> frozenset[str]:
        return frozenset(self._adapters)

    def dispatch_step(self, step: Mapping[str, Any]) -> StepOutcome:
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
        adapter = self._adapters[capability]
        result = adapter.execute(capability, normalized["with"])
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
    """Build the broker from trusted runtime configuration, never from Action YAML."""
    from info_hub.feedbrain_adapter import FeedbrainSyncAdapter, load_feedbrain_bindings
    from info_hub.settings import get_settings

    settings = get_settings()
    bindings = load_feedbrain_bindings(settings.action_feedbrain_sources_json or "{}")
    adapter = FeedbrainSyncAdapter(
        base_url=settings.action_feedbrain_url, source_bindings=bindings,
    )
    return CapabilityBroker([adapter])
