"""Workflow V1 document contract. Pure validation; no tool execution or Feedbrain dependency."""
import math
import re
from collections.abc import Collection
from typing import Any

MAX_DOCUMENT_CHARS = 64_000
MAX_STEPS = 24
MAX_TEXT_CHARS = 32_000
MAX_INTERVAL_MINUTES = 10_080

STEP_ID_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
CAPABILITY_PATTERN = re.compile(r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+")
PARAMETER_PATTERN = re.compile(r"[a-z][a-z0-9_]*")
TOOL_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")
CATEGORY_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,63}")


class WorkflowValidationError(ValueError):
    """Action document is unsafe, ambiguous or outside the supported V1 schema."""


def _mapping(value: Any, location: str) -> dict:
    if not isinstance(value, dict):
        raise WorkflowValidationError(f"{location} must be an object")
    return value


def _keys(value: dict, *, required: set[str], allowed: set[str], location: str) -> None:
    if any(not isinstance(key, str) for key in value):
        raise WorkflowValidationError(f"{location} keys must be strings")
    missing = required - value.keys()
    unknown = value.keys() - allowed
    if missing:
        raise WorkflowValidationError(f"{location} missing: {', '.join(sorted(missing))}")
    if unknown:
        raise WorkflowValidationError(f"{location} unknown fields: {', '.join(sorted(unknown))}")


def _text(value: Any, location: str, *, maximum: int = MAX_TEXT_CHARS) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise WorkflowValidationError(f"{location} must be nonempty text (max {maximum} chars)")
    return value


def _json_value(value: Any, location: str, depth: int = 0) -> Any:
    """Limit parameters to small JSON-compatible values (not Python/YAML objects)."""
    if depth > 6:
        raise WorkflowValidationError(f"{location} nesting is too deep")
    if value is None or isinstance(value, (str, bool, int)):
        if isinstance(value, str) and len(value) > 4096:
            raise WorkflowValidationError(f"{location} text is too long")
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise WorkflowValidationError(f"{location} must be finite")
        return value
    if isinstance(value, list):
        if len(value) > 100:
            raise WorkflowValidationError(f"{location} list is too large")
        return [_json_value(item, f"{location}[]", depth + 1) for item in value]
    if isinstance(value, dict):
        if len(value) > 40:
            raise WorkflowValidationError(f"{location} has too many keys")
        clean = {}
        for key, item in value.items():
            if not isinstance(key, str) or not PARAMETER_PATTERN.fullmatch(key):
                raise WorkflowValidationError(f"{location} keys must be snake_case identifiers")
            clean[key] = _json_value(item, f"{location}.{key}", depth + 1)
        return clean
    raise WorkflowValidationError(f"{location} must be JSON-compatible")


def validate_action_document(document: Any) -> dict[str, Any]:
    """Validate and normalize parsed YAML (or a Python dictionary).

    Storage accepts unknown well-formed tools/capabilities for future adapters.
    Legacy ActionVersion snapshots remain readable but require a new version
    with an explicit tool before they can be executed.
    Call require_executable_workflow() before dispatching any work.
    """
    root = _mapping(document, "action")
    _keys(
        root, required={"name", "instruction"},
        allowed={"name", "category", "instruction", "workflow", "schedule"}, location="action",
    )
    name = _text(root["name"], "name", maximum=200).strip()
    instruction = _text(root["instruction"], "instruction")
    category = root.get("category", "general")
    if not isinstance(category, str) or not CATEGORY_PATTERN.fullmatch(category):
        raise WorkflowValidationError("category must be a lowercase identifier (max 64 chars)")
    result: dict[str, Any] = {
        "name": name, "category": category, "instruction": instruction,
        "workflow": None, "schedule": None,
    }

    if "workflow" in root:
        workflow = _mapping(root["workflow"], "workflow")
        _keys(
            workflow, required={"schema", "steps"}, allowed={"schema", "steps"},
            location="workflow",
        )
        if type(workflow["schema"]) is not int or workflow["schema"] != 1:
            raise WorkflowValidationError("workflow.schema must be integer 1")
        steps = workflow["steps"]
        if not isinstance(steps, list) or not 1 <= len(steps) <= MAX_STEPS:
            raise WorkflowValidationError(f"workflow.steps must contain 1–{MAX_STEPS} steps")

        seen: set[str] = set()
        normalized_steps: list[dict[str, Any]] = []
        for index, raw_step in enumerate(steps):
            location = f"workflow.steps[{index}]"
            step = _mapping(raw_step, location)
            _keys(
                step, required={"id", "tool", "capability"},
                allowed={"id", "tool", "capability", "with"},
                location=location,
            )
            step_id = _text(step["id"], f"{location}.id", maximum=64)
            if not STEP_ID_PATTERN.fullmatch(step_id):
                raise WorkflowValidationError(f"{location}.id must be a lowercase identifier")
            if step_id in seen:
                raise WorkflowValidationError(f"duplicate step id: {step_id}")
            seen.add(step_id)
            tool = _text(step["tool"], f"{location}.tool", maximum=64)
            if not TOOL_PATTERN.fullmatch(tool):
                raise WorkflowValidationError(f"{location}.tool must be a tool identifier")
            capability = _text(step["capability"], f"{location}.capability", maximum=100)
            if not CAPABILITY_PATTERN.fullmatch(capability):
                raise WorkflowValidationError(f"{location}.capability must be dotted identifier")

            params = _mapping(step.get("with", {}), f"{location}.with")
            normalized_params = _json_value(params, f"{location}.with")
            # Tool-specific parameter schemas (including source resource types)
            # belong to adapters; the core only enforces JSON-safe parameters.
            normalized_steps.append({
                "id": step_id, "tool": tool, "capability": capability,
                "with": normalized_params,
            })
        result["workflow"] = {"schema": 1, "steps": normalized_steps}

    if "schedule" in root:
        schedule = _mapping(root["schedule"], "schedule")
        _keys(
            schedule, required={"every_minutes"}, allowed={"every_minutes"},
            location="schedule",
        )
        interval = schedule["every_minutes"]
        if type(interval) is not int or not 1 <= interval <= MAX_INTERVAL_MINUTES:
            raise WorkflowValidationError(
                f"schedule.every_minutes must be integer 1–{MAX_INTERVAL_MINUTES}"
            )
        result["schedule"] = {"every_minutes": interval}
    return result


def require_executable_workflow(
    document: Any, available_capabilities: Collection[str],
) -> dict[str, Any]:
    """Reject instruction-only or unbound workflows before a worker creates side effects."""
    # Registry stores normalized definitions with optional fields set to None.
    # Revalidating such a snapshot must not interpret the absent schedule
    # as a user-supplied null schedule (YAML validation still rejects it).
    if isinstance(document, dict):
        document = {
            key: value for key, value in document.items()
            if not (key in ("workflow", "schedule") and value is None)
        }
    normalized = validate_action_document(document)
    workflow = normalized["workflow"]
    if workflow is None:
        raise WorkflowValidationError("Action has no executable workflow")
    missing = {
        step["capability"] for step in workflow["steps"]
        if step["capability"] not in available_capabilities
    }
    if missing:
        raise WorkflowValidationError(
            f"Capabilities not available: {', '.join(sorted(missing))}"
        )
    return normalized


def parse_action_yaml(raw: str) -> dict[str, Any]:
    """Parse a single, bounded YAML document, rejecting aliases and duplicate map keys."""
    if not isinstance(raw, str) or not raw.strip() or len(raw) > MAX_DOCUMENT_CHARS:
        raise WorkflowValidationError(
            f"Action YAML must contain 1–{MAX_DOCUMENT_CHARS} characters"
        )
    import yaml

    class StrictSafeLoader(yaml.SafeLoader):
        def compose_node(self, parent: Any, index: Any) -> Any:
            if self.check_event(yaml.AliasEvent):
                raise WorkflowValidationError("YAML aliases are not permitted")
            return super().compose_node(parent, index)

        def construct_mapping(self, node: Any, deep: bool = False) -> dict:
            seen = set()
            for key_node, _ in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, str):
                    raise WorkflowValidationError("YAML object keys must be strings")
                if key in seen:
                    raise WorkflowValidationError(f"Duplicate YAML key: {key}")
                seen.add(key)
            return super().construct_mapping(node, deep=deep)

    try:
        document = yaml.load(raw, Loader=StrictSafeLoader)
    except yaml.YAMLError as exc:
        raise WorkflowValidationError(f"Invalid YAML: {exc}") from exc
    return validate_action_document(document)


def main() -> int:
    """Minimal local check; not a workflow runner."""
    import argparse
    import json
    from pathlib import Path

    parser = argparse.ArgumentParser(description="Validate one Action Workflow V1 YAML document")
    parser.add_argument("file", help="Path to the Action YAML file")
    args = parser.parse_args()
    try:
        definition = parse_action_yaml(Path(args.file).read_text(encoding="utf-8"))
    except (WorkflowValidationError, OSError) as exc:
        parser.exit(status=1, message=f"Invalid Action: {exc}\n")
    print(json.dumps(definition, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
