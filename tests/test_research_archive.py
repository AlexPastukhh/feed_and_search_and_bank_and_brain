"""Check versioned research report references without external dependencies."""
import json
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parents[1] / "docs/research/action3/runs/2026-11-10-archive01"


class ResearchArchiveTests(unittest.TestCase):
    def test_structured_report_has_stable_references(self):
        data = json.loads((BASE / "result.json").read_text(encoding="utf-8"))
        report = (BASE / "report.md").read_text(encoding="utf-8")
        self.assertEqual(data["metadata"]["action_id"], 3)
        self.assertEqual(data["metadata"]["action_version"], 2)
        self.assertEqual(data["metadata"]["execution_mode"], "external_ai_manual")
        self.assertTrue(data["metadata"]["report_id"])
        evidence = {x["id"] for x in data["evidence"]}
        sources = {x["id"] for x in data["sources"]}
        allids = []
        for key, prefix in (("sources", "SRC"), ("research_action_proposals", "RES"),
                            ("monitoring_action_proposals", "MON")):
            for item in data[key]:
                self.assertRegex(item["id"], rf"^{prefix}-[0-9]{{3}}$")
                self.assertIn(item["id"], report)
                self.assertTrue(set(item["evidence_ids"]) <= evidence)
                allids.append(item["id"])
        self.assertEqual(len(allids), len(set(allids)))
        for proposal in data["research_action_proposals"] + data["monitoring_action_proposals"]:
            self.assertIn(proposal["change"], ("create", "update"))
            self.assertEqual(proposal["status"], "proposed")
            self.assertTrue(proposal["reason"])
            self.assertTrue(proposal["suggested_changes"])
        for proposal in data["monitoring_action_proposals"]:
            self.assertTrue(set(proposal["source_ids"]) <= sources)
        self.assertTrue(data["overview"]["summary"])
        self.assertIn("OVERVIEW", report)


if __name__ == "__main__":
    unittest.main()
