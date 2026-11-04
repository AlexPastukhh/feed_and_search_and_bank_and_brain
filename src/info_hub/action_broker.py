"""Capability-level dispatch independent of any tool's transport or storage."""
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlsplit

from info_hub.action_workflow import (
    WorkflowValidationError, require_executable_workflow,
)

# History is an execution receipt, not an unbounded copy of tool-owned data.
MAX_RESULT_DETAILS_BYTES = 16_384
MAX_RESULT_EXTERNAL_REF_CHARS = 240
MAX_RESULT_DEPTH = 6
MAX_RESULT_NODES = 512

_SECRET_PARTS = (
    "password", "passwd", "secret", "apikey", "accesstoken", "refreshtoken",
    "authtoken", "authorization", "credential", "privatekey", "clientkey",
    "sessioncookie", "setcookie", "presignedurl", "signedurl", "token",
    "accesskey", "signature",
)
_CREDENTIAL_TEXT = re.compile(
    r"(?i)(?:\bbearer\s+\S+|"
    r"\b(?:password|api[_-]?key|access[_-]?token|refresh[_-]?token|"
    r"token|client[_-]?secret|authorization)\s*[:=]\s*\S+)"
)


def _is_sensitive_field(key: str) -> bool:
    compact = re.sub(r"[^a-z0-9]", "", key.lower())
    return any(part in compact for part in _SECRET_PARTS)


def _is_sensitive_text(value: str) -> bool:
    if _CREDENTIAL_TEXT.search(value):
        return True
    if "://" in value:
        try:
            parts = urlsplit(value)
            if parts.username or parts.password:
                return True
            return any(
                _is_sensitive_field(key) or key.lower() in ("sig", "signature", "key")
                for key, _ in parse_qsl(parts.query, keep_blank_values=True)
            )
        except ValueError:
            return True
    return False


class _ResultNotSafe(ValueError):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _safe_result_value(value: Any, *, depth: int, budget: list[int]) -> tuple[Any, bool]:
    """Copy only bounded JSON data, omitting fields with credential-like names."""
    budget[0] += 1
    if budget[0] > MAX_RESULT_NODES or depth > MAX_RESULT_DEPTH:
        raise _ResultNotSafe("too_large")
    if value is None or isinstance(value, (bool, int)):
        return value, False
    if isinstance(value, str):
        if len(value) > 4096:
            raise _ResultNotSafe("too_large")
        if _is_sensitive_text(value):
            return "[REDACTED]", True
        return value, False
    if isinstance(value, float):
        if not math.isfinite(value):
            raise _ResultNotSafe("not_json_compatible")
        return value, False
    if isinstance(value, list):
        if len(value) > 100:
            raise _ResultNotSafe("too_large")
        clean = []
        redacted = False
        for item in value:
            item, removed = _safe_result_value(item, depth=depth + 1, budget=budget)
            clean.append(item)
            redacted |= removed
        return clean, redacted
    if isinstance(value, dict):
        if len(value) > 100:
            raise _ResultNotSafe("too_large")
        clean = {}
        redacted = False
        for key, item in value.items():
            if not isinstance(key, str):
                raise _ResultNotSafe("not_json_compatible")
            if _is_sensitive_field(key) or key.startswith("_action_result_"):
                redacted = True
                continue
            if len(key) > 128:
                raise _ResultNotSafe("too_large")
            clean[key], removed = _safe_result_value(
                item, depth=depth + 1, budget=budget,
            )
            redacted |= removed
        return clean, redacted
    raise _ResultNotSafe("not_json_compatible")


def _history_details(result: dict[str, Any]) -> dict[str, Any]:
    """Preserve a bounded receipt; keep full data in the providing tool."""
    details = {
        key: value for key, value in result.items()
        if key not in ("status", "external_run_ref")
    }
    try:
        details, redacted = _safe_result_value(details, depth=0, budget=[0])
        if redacted:
            details["_action_result_redacted"] = True
        encoded = json.dumps(
            details, ensure_ascii=False, allow_nan=False, separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > MAX_RESULT_DETAILS_BYTES:
            raise _ResultNotSafe("too_large")
        return details
    except _ResultNotSafe as exc:
        return {"_action_result_omitted": exc.reason}
    except (UnicodeError, TypeError, ValueError):
        return {"_action_result_omitted": "not_json_compatible"}


def _checked_external_ref(value: Any, tool: str) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str) or not 1 <= len(value) <= MAX_RESULT_EXTERNAL_REF_CHARS
        or not value.isprintable() or "?" in value or "#" in value
        or _is_sensitive_text(value)
    ):
        raise ToolExecutionError(
            "invalid_tool_result", "Tool returned an unsafe external reference",
            tool=tool,
        )
    return value


def safe_error_external_ref(value: Any, tool: str) -> str | None:
    """Never persist an adapter's unchecked error reference."""
    try:
        return _checked_external_ref(value, tool)
    except ToolExecutionError:
        return None


def safe_error_message(message: str) -> str:
    """Do not persist obviously credential-bearing or unbounded adapter messages."""
    if not isinstance(message, str) or len(message) > 1024 or _is_sensitive_text(message):
        return "Tool error details omitted"
    return message


def safe_error_code(code: Any) -> str:
    """Keep untrusted adapter error codes within the database's fixed-length field."""
    if isinstance(code, str) and re.fullmatch(r"[a-z][a-z0-9_]{0,79}", code):
        return code
    return "tool_error"


@dataclass(frozen=True)
class StepOutcome:
    """A bounded execution receipt, not a copy of the tool-owned data."""

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
        def record_external_ref(ref: str) -> None:
            checked = _checked_external_ref(ref, adapter.name)
            if checked is None:
                raise ToolExecutionError(
                    "invalid_tool_result", "Tool reported an empty external reference",
                    tool=adapter.name,
                )
            if on_external_ref is not None:
                on_external_ref(checked)

        result = adapter.execute(
            capability, normalized["with"], on_external_ref=record_external_ref,
        )
        if not isinstance(result, dict) or result.get("status") != "completed":
            raise ToolExecutionError(
                "invalid_tool_result",
                f"Tool {adapter.name} did not return a completed result",
                tool=adapter.name,
            )
        external_ref = _checked_external_ref(result.get("external_run_ref"), adapter.name)
        return StepOutcome(
            step_id=normalized["id"], capability=capability, tool=adapter.name,
            status="completed", external_run_ref=external_ref,
            details=_history_details(result),
        )



def configured_broker() -> CapabilityBroker:
    """Load allowed adapters from runtime settings; Action YAML selects among them."""
    from info_hub.feedbrain_adapter import FeedbrainSyncAdapter
    from info_hub.settings import get_settings

    settings = get_settings()
    adapter = FeedbrainSyncAdapter(base_url=settings.action_feedbrain_url)
    return CapabilityBroker([adapter])
