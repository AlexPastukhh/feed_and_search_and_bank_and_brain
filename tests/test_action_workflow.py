"""Dependency-free validation tests; YAML parsing tests run where PyYAML is installed."""
import importlib.util
import unittest
from datetime import datetime
from pathlib import Path

from info_hub.action_workflow import (
    WorkflowValidationError,
    parse_action_yaml,
    require_executable_workflow,
    validate_action_document,
)

HAS_YAML = importlib.util.find_spec("yaml") is not None


def sample_action():
    return {
        "name": "Update AI archive",
        "instruction": "Sync selected publications and retain the result.",
        "workflow": {
            "schema": 1,
            "steps": [{
                "id": "refresh",
                "capability": "information.sync",
                "with": {"source": "ai_articles"},
            }],
        },
        "schedule": {"every_minutes": 60},
    }


class ActionDocumentTests(unittest.TestCase):
    def test_accepts_minimal_instruction_only(self):
        doc = validate_action_document({"name": "Study", "instruction": "Study news"})
        self.assertEqual(doc["name"], "Study")
        self.assertIsNone(doc["workflow"])
        self.assertIsNone(doc["schedule"])

    def test_accepts_example_and_preserves_meaning(self):
        doc = validate_action_document(sample_action())
        self.assertEqual(doc["workflow"]["steps"][0]["capability"], "information.sync")
        self.assertEqual(doc["workflow"]["steps"][0]["with"]["source"], "ai_articles")
        self.assertEqual(doc["schedule"]["every_minutes"], 60)

    def test_rejects_empty_instruction_and_name(self):
        for field in ("instruction", "name"):
            with self.subTest(field=field):
                doc = sample_action()
                doc[field] = " \n"
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_rejects_unknown_fields(self):
        cases = [
            ("top level", lambda doc: doc.update({"tool_url": "http://example.net"})),
            ("workflow", lambda doc: doc["workflow"].update({"parallel": True})),
            ("step", lambda doc: doc["workflow"]["steps"][0].update({"script": "rm -rf"})),
        ]
        for label, change in cases:
            with self.subTest(label=label):
                doc = sample_action()
                change(doc)
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_rejects_non_int_schema_and_schedule(self):
        for key, value in (("schema", True), ("schema", "1"), ("schema", 2)):
            doc = sample_action()
            doc["workflow"][key] = value
            with self.subTest(field=key, value=value):
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)
        for interval in (True, 0, -1, 10081, "60", 0.5):
            doc = sample_action()
            doc["schedule"]["every_minutes"] = interval
            with self.subTest(interval=interval):
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_rejects_missing_or_bad_sync_source(self):
        for params in ({}, {"subscription_id": 1}, {"source": "rss/news"},
                       {"source": ""}, {"source": 12}, {"source": "feed", "url": "x"}):
            doc = sample_action()
            doc["workflow"]["steps"][0]["with"] = params
            with self.subTest(params=params):
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_rejects_duplicate_step_ids(self):
        doc = sample_action()
        doc["workflow"]["steps"].append({
            "id": "refresh", "capability": "information.sync", "with": {"source": "second"},
        })
        with self.assertRaisesRegex(WorkflowValidationError, "duplicate step"):
            validate_action_document(doc)

    def test_rejects_missing_or_invalid_step_capability(self):
        for value in ("sync", "Information.Sync", "bad command()", 17, ""):
            doc = sample_action()
            doc["workflow"]["steps"][0]["capability"] = value
            with self.subTest(value=value):
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_rejects_empty_or_too_many_steps(self):
        for length in (0, 25):
            doc = sample_action()
            doc["workflow"]["steps"] = [
                {"id": f"step_{i}", "capability": "data.read"} for i in range(length)
            ]
            with self.subTest(length=length):
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_rejects_unsafe_parameter_values(self):
        for value in (datetime.now(), float("inf"), {"bad key": "x"},
                      list(range(101))):
            doc = sample_action()
            doc["workflow"]["steps"][0] = {
                "id": "future", "capability": "data.read", "with": {"query": value},
            }
            with self.subTest(value_type=type(value).__name__):
                with self.assertRaises(WorkflowValidationError):
                    validate_action_document(doc)

    def test_accepts_future_capability_as_non_executable_draft(self):
        doc = sample_action()
        doc["workflow"]["steps"][0] = {
            "id": "future", "capability": "data.reconcile",
            "with": {"params": {"limit": 25, "keywords": ["ai", "games"]}},
        }
        parsed = validate_action_document(doc)
        self.assertEqual(parsed["workflow"]["steps"][0]["capability"], "data.reconcile")
        with self.assertRaisesRegex(WorkflowValidationError, "data.reconcile"):
            require_executable_workflow(parsed, {"information.sync"})

    def test_instruction_only_cannot_run(self):
        with self.assertRaisesRegex(WorkflowValidationError, "no executable workflow"):
            require_executable_workflow(
                {"name": "Thought", "instruction": "Investigate something"},
                {"information.sync"},
            )

    def test_registered_capability_is_executable(self):
        result = require_executable_workflow(sample_action(), {"information.sync"})
        self.assertEqual(result["workflow"]["steps"][0]["id"], "refresh")

    def test_cannot_execute_unbound_capability(self):
        with self.assertRaisesRegex(WorkflowValidationError, "information.sync"):
            require_executable_workflow(sample_action(), set())

    def test_normalization_is_independent_of_input(self):
        raw = sample_action()
        normalized = validate_action_document(raw)
        raw["workflow"]["steps"][0]["with"]["source"] = "changed"
        self.assertEqual(
            normalized["workflow"]["steps"][0]["with"]["source"], "ai_articles"
        )


@unittest.skipUnless(HAS_YAML, "PyYAML is installed in the application/Docker environment")
class ActionYamlParsingTests(unittest.TestCase):
    EXAMPLE = """\
name: Обновить архив
instruction: |
  Проверь новые публикации.
workflow:
  schema: 1
  steps:
    - id: refresh_feed
      capability: information.sync
      with:
        source: ai_articles
schedule:
  every_minutes: 60
"""

    def test_repository_example_is_valid(self):
        example = Path(__file__).resolve().parents[1] / "examples/actions/rss_sync.yaml"
        doc = parse_action_yaml(example.read_text(encoding="utf-8"))
        self.assertEqual(doc["workflow"]["steps"][0]["capability"], "information.sync")

    def test_parses_document_like_compose(self):
        doc = parse_action_yaml(self.EXAMPLE)
        self.assertEqual(doc["name"], "Обновить архив")
        self.assertEqual(doc["workflow"]["steps"][0]["with"]["source"], "ai_articles")
        self.assertEqual(doc["schedule"]["every_minutes"], 60)

    def test_parses_instruction_only(self):
        doc = parse_action_yaml("name: Research\ninstruction: Research the topic\n")
        self.assertIsNone(doc["workflow"])

    def test_rejects_duplicate_yaml_keys(self):
        raw = "name: one\nname: two\ninstruction: Work\n"
        with self.assertRaisesRegex(WorkflowValidationError, "Duplicate YAML key"):
            parse_action_yaml(raw)

    def test_rejects_yaml_alias(self):
        raw = "name: one\ninstruction: &msg Read this\nextra: *msg\n"
        with self.assertRaisesRegex(WorkflowValidationError, "aliases"):
            parse_action_yaml(raw)

    def test_rejects_unsafe_yaml_type(self):
        raw = "name: test\ninstruction: !!python/object/apply:os.system ['echo x']\n"
        with self.assertRaisesRegex(WorkflowValidationError, "Invalid YAML"):
            parse_action_yaml(raw)

    def test_rejects_multidocument(self):
        raw = "name: one\ninstruction: Work\n---\nname: two\ninstruction: Work\n"
        with self.assertRaisesRegex(WorkflowValidationError, "Invalid YAML"):
            parse_action_yaml(raw)

    def test_rejects_oversized_input(self):
        with self.assertRaisesRegex(WorkflowValidationError, "must contain"):
            parse_action_yaml(" " * 64_001)

    def test_rejects_implicit_timestamp_parameter(self):
        raw = """
name: test
instruction: Work
workflow:
  schema: 1
  steps:
    - id: future
      capability: data.read
      with:
        published_on: 2026-11-04
"""
        with self.assertRaises(WorkflowValidationError):
            parse_action_yaml(raw)


if __name__ == "__main__":
    unittest.main()
