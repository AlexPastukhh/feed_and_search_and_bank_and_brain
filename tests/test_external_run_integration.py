"""Requires RUN_DB_INTEGRATION_TESTS=1 and a migrated disposable PostgreSQL."""
import json
import os
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError

from info_hub.action_models import ActionVersion
from info_hub.action_run_models import ActionRun, ActionStepRun
from info_hub.db import open_session
from info_hub.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Never use a persistent Windows PostgreSQL database for these tests",
)
DOC = "name: AI report\ncategory: research\ninstruction: Gather evidence\n"
TOKENS = ["a" * 48, "b" * 48]
REF = "https://github.com/owner/repo/blob/abc123/report.json"


def test_posthoc_idempotent_registration_without_broker(monkeypatch):
    from info_hub import external_run_auth
    client = TestClient(app)
    created = client.post("/actions", json={"definition_yaml": DOC})
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]
    scoped = [
        {"token": token, "action_ids": [action_id]} for token in TOKENS
    ]
    monkeypatch.setattr(external_run_auth, "get_settings", lambda: SimpleNamespace(
        action_external_run_tokens=SecretStr(json.dumps(scoped)),
    ))
    url = f"/actions/{action_id}/external-runs"
    payload = dict(
        version_number=1, external_run_key="research-v1-result01",
        initiated_by="user", status="completed", summary="Evidence archived",
        output_refs=[REF], storage_status="reported_saved",
    )
    auth = {"Authorization": "Bearer " + TOKENS[0]}
    assert client.post(url, json=payload).status_code == 401
    assert client.post(url, json=payload, headers={"Authorization": "Bearer wrong"}).status_code == 403
    assert client.post(
        f"/actions/{action_id + 999999}/external-runs", json=payload, headers=auth,
    ).status_code == 403
    first = client.post(url, json=payload, headers=auth)
    assert first.status_code == 201, first.text
    run_id = first.json()["id"]
    assert first.json()["execution_kind"] == "external_ai"
    assert "executor_id" not in first.json()
    assert first.json()["steps"] == []
    assert first.json()["started_at"] is None
    assert first.json()["result"]["details"]["storage_evidence"] == "executor_reported"
    replay = client.post(url, json=payload, headers=auth)
    assert replay.status_code == 200 and replay.json()["id"] == run_id
    assert client.post(
        url, json={**payload, "summary": "overwrite"}, headers=auth,
    ).status_code == 409
    alternate_grant = client.post(
        url, json=payload,
        headers={"Authorization": "Bearer " + TOKENS[1]},
    )
    assert alternate_grant.status_code == 200
    assert alternate_grant.json()["id"] == run_id
    assert "executor_id" not in alternate_grant.json()
    assert client.post(
        url, json={**payload, "summary": "overwrite from another grant"},
        headers={"Authorization": "Bearer " + TOKENS[1]},
    ).status_code == 409
    assert client.post(
        url, json={**payload, "version_number": 999}, headers=auth,
    ).status_code == 404
    listing = client.get(f"/actions/{action_id}/runs")
    assert listing.status_code == 200
    assert [r["id"] for r in listing.json()] == [run_id]
    assert "executor_id" not in listing.json()[0]
    detail = client.get(f"/action-runs/{run_id}").json()
    assert detail["steps"] == []
    assert "executor_id" not in detail
    with open_session() as session:
        rows = session.scalars(
            select(ActionRun).where(ActionRun.action_id == action_id)
        ).all()
        assert len(rows) == 1 and rows[0].status == "completed"
        assert "executor_id" not in {
            column["name"] for column in inspect(session.bind).get_columns("action_runs")
        }
        assert session.scalars(
            select(ActionStepRun).where(ActionStepRun.action_run_id == run_id)
        ).all() == []


def test_failed_external_run_and_worker_queue_guard(monkeypatch):
    """A failed AI report stays terminal; even raw SQL cannot queue an AI Run."""
    from info_hub import external_run_auth

    client = TestClient(app)
    created = client.post("/actions", json={"definition_yaml": DOC})
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]
    config = [{"token": TOKENS[0], "action_ids": [action_id]}]
    monkeypatch.setattr(external_run_auth, "get_settings", lambda: SimpleNamespace(
        action_external_run_tokens=SecretStr(json.dumps(config)),
    ))
    payload = dict(
        version_number=1, external_run_key="research-v1-failure01",
        initiated_by="ai", status="failed", error_code="source_unavailable",
        summary="Authorized source was unavailable", output_refs=[],
        storage_status="reported_not_saved",
    )
    response = client.post(
        f"/actions/{action_id}/external-runs", json=payload,
        headers={"Authorization": "Bearer " + TOKENS[0]},
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["execution_kind"] == "external_ai"
    assert result["status"] == "failed" and result["steps"] == []
    assert result["error_code"] == "source_unavailable"
    assert result["result"]["details"]["storage_status"] == "reported_not_saved"

    with open_session() as session:
        version_id = session.scalar(select(ActionVersion.id).where(
            ActionVersion.action_id == action_id, ActionVersion.version_number == 1,
        ))
        assert version_id is not None
        # Direct database insertion must still reject a queued external AI run.
        illegal = ActionRun(
            action_id=action_id, action_version_id=version_id,
            status="queued", initiated_by="ai", execution_kind="external_ai",
            external_run_key="illegal-queued-run",
            registration_fingerprint="f" * 64,
        )
        session.add(illegal)
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
