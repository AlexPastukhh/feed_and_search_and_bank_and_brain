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
            "alembic/versions/20261104_0006_action_schedules.py",
            "src/info_hub/action_schedule_api.py",
            "src/info_hub/gateway_action_api.py",
            "src/info_hub/gateway_read_auth.py",
            "src/info_hub/gateway_read_main.py",
            "src/info_hub/gateway_https_server.py",
            "src/info_hub/action_schedule_services.py",
            "src/info_hub/main.py",
            "src/info_hub/action_worker.py",
            "src/info_hub/worker.py",
            ".env.example",
            ".gitignore",
        ):
            with self.subTest(path=path):
                self.assertTrue((ROOT / path).is_file())

    def test_native_gateway_https_entry_is_not_mounted_in_local_http(self):
        local = (ROOT / "src/info_hub/main.py").read_text(encoding="utf-8")
        narrow = (ROOT / "src/info_hub/gateway_read_main.py").read_text(encoding="utf-8")
        server = (ROOT / "src/info_hub/gateway_https_server.py").read_text(encoding="utf-8")
        compose = (ROOT / "compose.yaml").read_text(encoding="utf-8")

        self.assertNotIn("gateway_action_api", local)
        self.assertIn("gateway_action_api", narrow)
        self.assertIn("openapi_url=None", narrow)
        self.assertIn("redirect_slashes=False", narrow)
        self.assertIn("port=443", server)
        self.assertIn("ssl_keyfile=str(KEY_PATH)", server)
        self.assertIn("ssl_certfile=str(CERT_PATH)", server)
        self.assertIn("proxy_headers=False", server)
        self.assertNotIn("ACTION_GATEWAY_READ_TOKEN_SHA256:", compose.split("  action-core-gw:", 1)[0])

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
