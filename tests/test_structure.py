"""Dependency-free repository smoke tests, runnable in Fortis Repo."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class ProjectStructureTests(unittest.TestCase):
    def test_required_files_exist(self):
        for path in (
            "pyproject.toml",
            "Dockerfile",
            "compose.yaml",
            "alembic.ini",
            "alembic/env.py",
            "alembic/versions/20261104_0001_baseline.py",
            "alembic/versions/20261104_0005_action_execution.py",
            "src/info_hub/main.py",
            "src/info_hub/action_worker.py",
            "src/info_hub/worker.py",
            ".env.example",
            ".gitignore",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())

    def test_environment_is_not_tracked(self):
        ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn(".env\n", ignore)
        self.assertIn("!.env.example", ignore)

    def test_compose_separates_app_and_database(self):
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")
        for service in ("  api:", "  worker:", "  action-worker:", "  db:", "  migrate:"):
            with self.subTest(service=service):
                self.assertIn(service, compose)


if __name__ == "__main__":
    unittest.main()
