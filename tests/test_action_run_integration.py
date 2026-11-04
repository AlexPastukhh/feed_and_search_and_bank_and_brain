"""Action V1 queue/worker/API tests using a disposable, migrated PostgreSQL database.

Explicitly gated: never run on the persistent Windows Feedbrain database.
HTTP responses of Feedbrain are simulated; real RSS sync is a separate smoke test.
"""
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from info_hub.action_broker import CapabilityBroker
from info_hub.action_models import utc_now
from info_hub.action_run_models import ActionRun, ActionStepRun
from info_hub.action_run_services import (
    claim_next_action_run, process_action_run, recover_abandoned_action_runs,
)
from info_hub.db import open_session
from info_hub.feedbrain_adapter import FeedbrainSyncAdapter
from info_hub.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Only run on isolated, migrated, disposable PostgreSQL",
)

V1 = """\
name: Research feed sync
instruction: Collect the latest publications for future analysis
workflow:
  schema: 1
  steps:
    - id: collect
      tool: feedbrain
      capability: information.sync
      with:
        source:
          type: subscription
          id: 11
schedule:
  every_minutes: 60
"""

V2 = """\
name: Research feed sync (revised)
instruction: Collect the latest publications for future analysis
workflow:
  schema: 1
  steps:
    - id: collect
      tool: feedbrain
      capability: information.sync
      with:
        source:
          type: subscription
          id: 11
    - id: collect_again
      tool: feedbrain
      capability: information.sync
      with:
        source:
          type: subscription
          id: 11
"""


class FakeFeedbrain:
    """Real broker/adapter logic, fake network transport only."""
    def __init__(self, *, fail=False):
        self.calls = []
        self.id = 73
        self.fail = fail

    def request(self, method, url, timeout):
        self.calls.append((method, url))
        if method == "POST":
            self.id += 1
            return 202, {"id": self.id, "subscription_id": 11, "status": "queued"}
        if self.fail:
            return 200, {
                "id": self.id, "subscription_id": 11, "status": "failed",
                "error": "simulated private error",
            }
        return 200, {
            "id": self.id, "subscription_id": 11, "status": "completed",
            "items_seen": 4, "items_created": 1, "items_updated": 0,
        }


def broker_for(fake: FakeFeedbrain):
    adapter = FeedbrainSyncAdapter(
        base_url="http://api:8000",
        transport=fake.request, poll_interval=0.01, max_wait_seconds=10,
    )
    return CapabilityBroker([adapter])


def create(client, yaml=V1):
    response = client.post("/actions", json={"definition_yaml": yaml})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_version_pinned_manual_run_and_history(monkeypatch):
    client = TestClient(app)
    fake = FakeFeedbrain()
    broker = broker_for(fake)
    monkeypatch.setattr("info_hub.action_run_api.configured_broker", lambda: broker)
    action_id = create(client)

    start = client.post(f"/actions/{action_id}/runs")
    assert start.status_code == 202, start.text
    run_id = start.json()["id"]
    assert start.json()["status"] == "queued"
    assert start.json()["action_version_number"] == 1
    assert start.json()["initiated_by"] == "api"
    assert client.post(f"/actions/{action_id}/runs").status_code == 409

    # Publish v2 while v1 is queued; the run still executes the original snapshot.
    published = client.post(
        f"/actions/{action_id}/versions",
        json={"definition_yaml": V2, "expected_version": 1},
    )
    assert published.status_code == 201
    assert published.json()["current_version_number"] == 2

    assert claim_next_action_run() == run_id
    process_action_run(run_id, broker)
    result = client.get(f"/action-runs/{run_id}")
    assert result.status_code == 200
    data = result.json()
    assert data["status"] == "completed"
    assert data["action_version_number"] == 1
    assert [s["step_id"] for s in data["steps"]] == ["collect"]
    assert data["steps"][0]["tool"] == "feedbrain"
    assert data["steps"][0]["external_run_ref"] == "feedbrain:ingestion_run:74"
    assert data["result"]["status"] == "completed"
    assert data["result"]["details"]["steps"][0]["details"]["counts"]["items_created"] == 1
    assert fake.calls == [
        ("POST", "http://api:8000/subscriptions/11/sync"),
        ("GET", "http://api:8000/runs/74"),
    ]

    listing = client.get(f"/actions/{action_id}/runs")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == run_id
    assert listing.json()[0]["action_version_number"] == 1

    # Explicitly launching the older version and the latest are both supported.
    second = client.post(
        f"/actions/{action_id}/runs", json={"version_number": 2},
    )
    assert second.status_code == 202
    second_id = second.json()["id"]
    assert claim_next_action_run() == second_id
    process_action_run(second_id, broker)
    latest = client.get(f"/action-runs/{second_id}").json()
    assert latest["status"] == "completed"
    assert latest["action_version_number"] == 2
    assert [s["step_id"] for s in latest["steps"]] == ["collect", "collect_again"]
    assert client.get(f"/actions/{action_id}/versions/1").json()["definition_yaml"] == V1


def test_action_without_schedule_still_executes(monkeypatch):
    client = TestClient(app)
    fake = FakeFeedbrain()
    broker = broker_for(fake)
    monkeypatch.setattr("info_hub.action_run_api.configured_broker", lambda: broker)
    unscheduled = V1.replace("schedule:\n  every_minutes: 60\n", "")
    action_id = create(client, unscheduled)
    response = client.post(f"/actions/{action_id}/runs")
    assert response.status_code == 202, response.text
    run_id = response.json()["id"]
    assert claim_next_action_run() == run_id
    process_action_run(run_id, broker)
    result = client.get(f"/action-runs/{run_id}").json()
    assert result["status"] == "completed"
    assert result["steps"][0]["status"] == "completed"


def test_failed_feedbrain_job_is_saved_without_leaking_private_error(monkeypatch):
    client = TestClient(app)
    fake = FakeFeedbrain(fail=True)
    broker = broker_for(fake)
    monkeypatch.setattr("info_hub.action_run_api.configured_broker", lambda: broker)
    action_id = create(client)

    response = client.post(f"/actions/{action_id}/runs")
    assert response.status_code == 202
    run_id = response.json()["id"]
    assert claim_next_action_run() == run_id
    process_action_run(run_id, broker)

    run = client.get(f"/action-runs/{run_id}").json()
    assert run["status"] == "failed"
    assert run["error_code"] == "external_run_failed"
    assert run["steps"][0]["status"] == "failed"
    assert run["steps"][0]["external_run_ref"] == "feedbrain:ingestion_run:74"
    assert run["result"]["status"] == "failed"
    assert "simulated private error" not in str(run)


def test_preflight_rejects_unsupported_resource_and_instruction_only(monkeypatch):
    client = TestClient(app)
    fake = FakeFeedbrain()
    broker = broker_for(fake)
    monkeypatch.setattr("info_hub.action_run_api.configured_broker", lambda: broker)
    incompatible = V1.replace("type: subscription", "type: collection")
    action_id = create(client, incompatible)
    response = client.post(f"/actions/{action_id}/runs")
    assert response.status_code == 409
    assert client.get(f"/actions/{action_id}/runs").json() == []
    assert fake.calls == []

    only_instruction_id = create(
        client, "name: Plain instruction\ninstruction: Research this market\n",
    )
    response = client.post(f"/actions/{only_instruction_id}/runs")
    assert response.status_code == 409
    assert client.get("/action-runs/2147483647").status_code == 404
    assert client.get("/actions/2147483647/runs").status_code == 404
    assert client.post(
        f"/actions/{action_id}/runs", json={"version_number": 999},
    ).status_code == 404
    assert client.post(
        f"/actions/{action_id}/runs", json={"execute": True},
    ).status_code == 422


def test_ambiguous_crash_is_interrupted_and_never_requeued(monkeypatch):
    client = TestClient(app)
    fake = FakeFeedbrain()
    broker = broker_for(fake)
    monkeypatch.setattr("info_hub.action_run_api.configured_broker", lambda: broker)
    action_id = create(client)
    run_id = client.post(f"/actions/{action_id}/runs").json()["id"]
    assert claim_next_action_run() == run_id

    with open_session() as session:
        run = session.get(ActionRun, run_id)
        run.started_at = utc_now() - timedelta(hours=3)
        session.add(ActionStepRun(
            action_run_id=run_id, step_id="collect", capability="information.sync",
            status="running",
        ))
        session.commit()

    assert recover_abandoned_action_runs() >= 1
    detail = client.get(f"/action-runs/{run_id}").json()
    assert detail["status"] == "interrupted"
    assert detail["error_code"] == "worker_interrupted"
    assert detail["steps"][0]["status"] == "interrupted"
    assert detail["result"]["details"]["external_outcome"] == "may_be_unknown"
    assert claim_next_action_run() is None
    assert fake.calls == []
