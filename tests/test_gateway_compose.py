"""Compose contract for the opt-in native Action Core HTTPS/443 service."""
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


class GatewayComposeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.compose = yaml.safe_load((ROOT / "compose.yaml").read_text(encoding="utf-8"))

    def test_gateway_service_is_opt_in_and_native_tls_only(self):
        service = self.compose["services"]["action-core-gw"]
        self.assertEqual(["gateway"], service["profiles"])
        self.assertEqual(["python", "-m", "info_hub.gateway_https_server"], service["command"])
        self.assertEqual(["443"], service["expose"])
        self.assertNotIn("ports", service)
        self.assertEqual(["default", "fortis-actioncore-net"], service["networks"])
        self.assertEqual("${ACTION_GATEWAY_READ_TOKEN_SHA256:-}", service["environment"]["ACTION_GATEWAY_READ_TOKEN_SHA256"])
        self.assertEqual([{"type": "volume", "source": "action_core_gateway_tls", "target": "/run/action-core-gateway-tls", "read_only": True}], service["volumes"])
        self.assertTrue(service["read_only"])
        self.assertEqual("10001:10001", service["user"])
        self.assertEqual(["ALL"], service["cap_drop"])
        self.assertEqual(["NET_BIND_SERVICE"], service["cap_add"])
        self.assertEqual(["no-new-privileges:true"], service["security_opt"])
        self.assertEqual("unless-stopped", service["restart"])
        self.assertEqual("service_healthy", service["depends_on"]["db"]["condition"])
        self.assertNotIn("migrate", service["depends_on"])

    def test_existing_local_api_remains_http_8000_without_gateway_verifier(self):
        api = self.compose["services"]["api"]
        self.assertEqual(["uvicorn", "info_hub.main:app", "--host", "0.0.0.0", "--port", "8000"], api["command"])
        self.assertEqual(["127.0.0.1:${API_PORT:-8000}:8000"], api["ports"])
        self.assertNotIn("ACTION_GATEWAY_READ_TOKEN_SHA256", api["environment"])
        self.assertEqual(["gateway"], self.compose["services"]["action-core-gw"]["profiles"])

    def test_gateway_network_and_tls_volume_are_owner_provisioned(self):
        network = self.compose["networks"]["fortis-actioncore-net"]
        self.assertEqual("fortis-actioncore-net", network["name"])
        self.assertEqual("bridge", network["driver"])
        self.assertTrue(network["internal"])
        volume = self.compose["volumes"]["action_core_gateway_tls"]
        self.assertTrue(volume["external"])
        self.assertEqual("fortis-actioncore-gateway-tls", volume["name"])


if __name__ == "__main__":
    unittest.main()
