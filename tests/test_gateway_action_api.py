"""Offline contract tests for the narrow Action Core Gateway READ endpoint."""
import hashlib
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from info_hub import gateway_action_api, gateway_read_auth
from info_hub.db import get_session
from info_hub.gateway_read_main import app

TOKEN = "gateway-read-token-" + ("x" * 40)
DIGEST = hashlib.sha256(TOKEN.encode("ascii")).hexdigest()
PATH = "/gateway/v1/actions/3"


class FakeSession:
    def __init__(self, *, action_exists=True, schedule_active=False):
        self.action_exists = action_exists
        self.schedule_active = schedule_active
        self.get_calls = 0
        self.scalar_calls = 0

    def get(self, model, action_id):
        self.get_calls += 1
        if not self.action_exists or action_id not in (3, 4):
            return None
        return SimpleNamespace(
            id=action_id,
            name="Research" if action_id == 3 else "Monitoring",
            current_version_number=3 if action_id == 3 else 1,
        )

    def scalar(self, _statement):
        self.scalar_calls += 1
        return self.schedule_active


@pytest.fixture
def gateway_client(monkeypatch):
    session = FakeSession()

    def override_session():
        yield session

    app.dependency_overrides[get_session] = override_session
    monkeypatch.setattr(
        gateway_action_api,
        "get_action_version",
        lambda _session, action_id, version_number: SimpleNamespace(
            source_yaml="name: Research\ninstruction: Read only\n",
            definition={"category": "research" if action_id == 3 else "monitoring"},
        ) if version_number in (1, 3) else None,
    )
    monkeypatch.setattr(
        gateway_read_auth,
        "get_settings",
        lambda: SimpleNamespace(action_gateway_read_token_sha256=SecretStr(DIGEST)),
    )
    with TestClient(app, base_url="https://action-core-gw") as client:
        yield client, session
    app.dependency_overrides.pop(get_session, None)


def _headers(token=TOKEN):
    return {"Authorization": f"Bearer {token}"}


def test_gateway_https_app_is_not_the_local_http_app(gateway_client):
    from info_hub.main import app as local_http_app

    client, _session = gateway_client
    for path in ("/actions/3", "/health/live", "/health/ready", "/docs",
                 "/openapi.json", "/redoc", "/sources", "/search"):
        response = client.get(path, headers=_headers(), follow_redirects=False)
        assert response.status_code == 404, (path, response.status_code)
    with TestClient(local_http_app, base_url="http://127.0.0.1:8000") as local:
        assert local.get(PATH, headers=_headers(), follow_redirects=False).status_code == 404


def test_gateway_read_returns_only_closed_current_action_projection(gateway_client):
    client, _session = gateway_client
    response = client.get(PATH, headers=_headers())

    assert response.status_code == 200, response.text
    payload = response.json()
    assert set(payload) == {
        "action_id", "name", "category", "current_version_number",
        "definition_yaml", "schedule_active",
    }
    assert payload == {
        "action_id": 3,
        "name": "Research",
        "category": "research",
        "current_version_number": 3,
        "definition_yaml": "name: Research\ninstruction: Read only\n",
        "schedule_active": False,
    }
    assert len(response.content) <= 65_536
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "executor_id" not in response.text
    assert "database_url" not in response.text


def test_gateway_read_supports_only_action_ids_three_and_four(gateway_client):
    client, session = gateway_client
    assert client.get("/gateway/v1/actions/4", headers=_headers()).status_code == 200
    before = session.get_calls
    assert client.get("/gateway/v1/actions/2", headers=_headers()).status_code == 403
    assert client.get("/gateway/v1/actions/5", headers=_headers()).status_code == 403
    assert session.get_calls == before


def test_gateway_read_rejects_missing_and_wrong_bearer(gateway_client):
    client, session = gateway_client
    missing = client.get(PATH)
    wrong = client.get(PATH, headers=_headers("z" * 48))

    assert missing.status_code == 401
    assert missing.headers["www-authenticate"] == "Bearer"
    assert wrong.status_code == 403
    assert session.get_calls == 0
    assert session.scalar_calls == 0


def test_gateway_read_fails_closed_when_verifier_is_missing_or_malformed(
    gateway_client, monkeypatch,
):
    client, _session = gateway_client
    monkeypatch.setattr(
        gateway_read_auth,
        "get_settings",
        lambda: SimpleNamespace(action_gateway_read_token_sha256=SecretStr("")),
    )
    assert client.get(PATH, headers=_headers()).status_code == 503

    monkeypatch.setattr(
        gateway_read_auth,
        "get_settings",
        lambda: SimpleNamespace(action_gateway_read_token_sha256=SecretStr("not-a-sha256")),
    )
    assert client.get(PATH, headers=_headers()).status_code == 503


def test_gateway_read_rejects_wrong_host_query_body_and_noncanonical_path(gateway_client):
    client, _session = gateway_client
    wrong_host = client.get(PATH, headers={**_headers(), "Host": "attacker.example"})
    query = client.get(PATH + "?version=3", headers=_headers())
    body = client.request("GET", PATH, headers=_headers(), content=b"{}")
    trailing_slash = client.get(PATH + "/", headers=_headers())
    double_slash = client.get(PATH + "//", headers=_headers())
    suffix = client.get(PATH + "/runs/", headers=_headers())

    assert wrong_host.status_code == 421
    assert query.status_code == 400
    assert body.status_code == 400
    assert trailing_slash.status_code == 404
    assert double_slash.status_code == 404
    assert suffix.status_code == 404


def test_gateway_read_rejects_non_get_methods(gateway_client):
    client, _session = gateway_client
    assert client.head(PATH, headers=_headers()).status_code == 405
    assert client.post(PATH, headers=_headers()).status_code == 405
    assert client.put(PATH, headers=_headers()).status_code == 405


def test_gateway_read_returns_not_found_without_exposing_other_action_ids(
    gateway_client,
):
    client, session = gateway_client
    session.action_exists = False
    response = client.get(PATH, headers=_headers())
    assert response.status_code == 404
    assert response.json() == {"detail": "Action not found"}


def test_gateway_read_rejects_oversized_projection(gateway_client, monkeypatch):
    client, _session = gateway_client
    monkeypatch.setattr(
        gateway_action_api,
        "get_action_version",
        lambda *_args, **_kwargs: SimpleNamespace(
            source_yaml="x" * 65_536,
            definition={"category": "research"},
        ),
    )
    response = client.get(PATH, headers=_headers())
    assert response.status_code == 500
    assert response.json() == {
        "detail": "Gateway READ response exceeds the configured limit",
    }


def test_gateway_read_rejects_missing_or_invalid_current_version(
    gateway_client, monkeypatch,
):
    client, _session = gateway_client
    monkeypatch.setattr(gateway_action_api, "get_action_version", lambda *_a, **_k: None)
    response = client.get(PATH, headers=_headers())
    assert response.status_code == 500
    assert response.json() == {"detail": "Current Action version is unavailable"}
