"""Schedule API + queue + worker integration on isolated, migrated PostgreSQL ONLY.

Set RUN_DB_INTEGRATION_TESTS=1 for a disposable test database. Never run this
against the persistent Windows Feedbrain database/volume.
"""
import os
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from info_hub.action_broker import CapabilityBroker
from info_hub.action_models import utc_now
from info_hub.action_run_services import claim_next_action_run, process_action_run
from info_hub.action_schedule_models import ActionSchedule
from info_hub.action_schedule_services import enqueue_due_action_schedules
from info_hub.db import open_session
from info_hub.feedbrain_adapter import FeedbrainSyncAdapter
from info_hub.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Requires isolated, migrated, disposable PostgreSQL",
)

BASE = """\
name: Scheduled feed test
instruction: Synchronize the selected test feed.
workflow:
  schema: 1
  steps:
    - id: refresh
      tool: feedbrain
      capability: information.sync
      with:
        source:
          type: subscription
          id: 11
schedule:
  every_minutes: 2
"""


class FakeFeedbrain:
    def __init__(self):
        self.requests = []
        self.current = 100

    def transport(self, method, url, timeout):
        self.requests.append((method, url))
        if method == "POST":
            self.current += 1
            return 202, {
                "id": self.current,
                "subscription_id": 11,
                "status": "queued",
            }
        return 200, {
            "id": self.current, "subscription_id": 11, "status": "completed",
            "items_seen": 2, "items_created": 1, "items_updated": 0,
        }


def broker_with_fake():
    fake = FakeFeedbrain()
    adapter = FeedbrainSyncAdapter(
        base_url="http://api:8000", transport=fake.transport,
        poll_interval=0.01, max_wait_seconds=10,
    )
    return CapabilityBroker([adapter]), fake


@pytest.fixture(autouse=True)
def disable_schedules_after_each_test():
    # Tests run only on a disposable DB; never leave enabled schedules that
    # a subsequent test's simulated future timestamp could trigger.
    yield
    if os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1":
        return
    with open_session() as session:
        schedules = session.scalars(
            select(ActionSchedule).where(ActionSchedule.enabled.is_(True))
        ).all()
        for schedule in schedules:
            schedule.enabled = False
            schedule.next_run_at = None
        session.commit()


def create_action(client, yaml=BASE):
    response = client.post("/actions", json={"definition_yaml": yaml})
    assert response.status_code == 201, response.text
    return response.json()["id"]


def make_due(action_id, at):
    with open_session() as session:
        schedule = session.scalar(
            select(ActionSchedule).where(ActionSchedule.action_id == action_id)
        )
        assert schedule is not None and schedule.enabled
        schedule.next_run_at = at
        session.commit()


def action_runs(client, action_id):
    response = client.get(f"/actions/{action_id}/runs")
    assert response.status_code == 200, response.text
    return response.json()


def test_schedule_is_disabled_until_explicitly_enabled(monkeypatch):
    broker, fake = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)

    initial = client.get(f"/actions/{action_id}/schedule")
    assert initial.status_code == 200
    assert initial.json()["enabled"] is False
    assert initial.json()["next_run_at"] is None
    assert client.get(f"/actions/{action_id}").json()["current_version"]["schedule_active"] is False
    assert action_runs(client, action_id) == []

    # Enabling explicitly can use interval declared in YAML.
    enabled = client.put(f"/actions/{action_id}/schedule", json={"enabled": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["enabled"] is True
    assert enabled.json()["every_minutes"] == 2
    assert enabled.json()["next_run_at"] is not None
    assert client.get(f"/actions/{action_id}").json()["current_version"]["schedule_active"] is True
    assert client.get(f"/actions/{action_id}/versions/1").json()["schedule_active"] is True
    assert fake.requests == []  # PUT itself must not run an Action.

    disabled = client.put(f"/actions/{action_id}/schedule", json={"enabled": False})
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    assert disabled.json()["next_run_at"] is None
    assert client.get(f"/actions/{action_id}").json()["current_version"]["schedule_active"] is False


def test_scheduled_runs_pin_version_and_record_results(monkeypatch):
    broker, fake = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)

    assert client.put(
        f"/actions/{action_id}/schedule",
        json={"enabled": True, "every_minutes": 1},
    ).status_code == 200
    now = utc_now()
    make_due(action_id, now - timedelta(seconds=2))
    first = enqueue_due_action_schedules(broker, now=now)
    assert first == {"queued": 1, "busy": 0, "invalid": 0}
    assert enqueue_due_action_schedules(broker, now=now)["queued"] == 0

    runs = action_runs(client, action_id)
    assert len(runs) == 1
    assert runs[0]["initiated_by"] == "schedule"
    assert runs[0]["action_version_number"] == 1
    assert runs[0]["status"] == "queued"

    run_id = runs[0]["id"]
    assert claim_next_action_run() == run_id
    process_action_run(run_id, broker)
    detail = client.get(f"/action-runs/{run_id}").json()
    assert detail["status"] == "completed"
    assert detail["result"]["status"] == "completed"
    assert detail["steps"][0]["external_run_ref"] == "feedbrain:ingestion_run:101"
    assert detail["steps"][0]["details"]["counts"]["items_created"] == 1
    assert fake.requests == [
        ("POST", "http://api:8000/subscriptions/11/sync"),
        ("GET", "http://api:8000/runs/101"),
    ]
    schedule = client.get(f"/actions/{action_id}/schedule").json()
    assert schedule["last_enqueued_at"] is not None
    assert schedule["last_skip_reason"] is None


def test_busy_run_skips_one_tick_without_creating_backlog(monkeypatch):
    broker, _ = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)
    assert client.put(
        f"/actions/{action_id}/schedule",
        json={"enabled": True, "every_minutes": 5},
    ).status_code == 200

    now = utc_now()
    make_due(action_id, now - timedelta(hours=3))
    assert enqueue_due_action_schedules(broker, now=now)["queued"] == 1
    assert enqueue_due_action_schedules(broker, now=now)["queued"] == 0
    # Busy at another due instant: advance cadence, record skip, no duplicate.
    make_due(action_id, now - timedelta(minutes=1))
    skipped = enqueue_due_action_schedules(broker, now=now)
    assert skipped["busy"] == 1
    assert len(action_runs(client, action_id)) == 1
    summary = client.get(f"/actions/{action_id}/schedule").json()
    assert summary["last_skip_reason"] == "active_run"
    assert summary["last_skipped_at"] is not None

    run_id = action_runs(client, action_id)[0]["id"]
    assert claim_next_action_run() == run_id
    process_action_run(run_id, broker)

    # A later tick can start another run without duplicating the previous one.
    later = now + timedelta(hours=1)
    make_due(action_id, later - timedelta(seconds=1))
    assert enqueue_due_action_schedules(broker, now=later)["queued"] == 1
    assert len(action_runs(client, action_id)) == 2
    summary = client.get(f"/actions/{action_id}/schedule").json()
    assert summary["last_skip_reason"] is None
    assert claim_next_action_run() == action_runs(client, action_id)[0]["id"]
    process_action_run(action_runs(client, action_id)[0]["id"], broker)


def test_schedule_uses_latest_immutable_version(monkeypatch):
    broker, _ = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)
    assert client.put(f"/actions/{action_id}/schedule", json={"enabled": True}).status_code == 200
    second_yaml = BASE.replace("Scheduled feed test", "Scheduled feed test v2")
    published = client.post(
        f"/actions/{action_id}/versions",
        json={"definition_yaml": second_yaml, "expected_version": 1},
    )
    assert published.status_code == 201
    assert published.json()["current_version"]["schedule_active"] is True
    versions = client.get(f"/actions/{action_id}/versions").json()
    assert [v["schedule_active"] for v in versions] == [True, False]

    now = utc_now()
    make_due(action_id, now - timedelta(seconds=1))
    assert enqueue_due_action_schedules(broker, now=now)["queued"] == 1
    runs = action_runs(client, action_id)
    assert runs[0]["action_version_number"] == 2
    assert client.get(f"/actions/{action_id}/versions/1").json()["definition_yaml"] == BASE
    assert claim_next_action_run() == runs[0]["id"]
    process_action_run(runs[0]["id"], broker)


def test_unsupported_new_version_is_skipped_and_visible(monkeypatch):
    broker, fake = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)
    assert client.put(f"/actions/{action_id}/schedule", json={"enabled": True}).status_code == 200
    invalid_yaml = BASE.replace("tool: feedbrain", "tool: other_tool")
    assert client.post(
        f"/actions/{action_id}/versions",
        json={"definition_yaml": invalid_yaml, "expected_version": 1},
    ).status_code == 201

    now = utc_now()
    make_due(action_id, now - timedelta(seconds=1))
    result = enqueue_due_action_schedules(broker, now=now)
    assert result["invalid"] == 1
    assert action_runs(client, action_id) == []
    summary = client.get(f"/actions/{action_id}/schedule").json()
    assert summary["last_skip_reason"] == "tool_unavailable"
    assert summary["next_run_at"] is not None
    assert fake.requests == []


def test_schedule_api_rejects_invalid_actions_and_inputs(monkeypatch):
    broker, _ = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)

    assert client.get("/actions/2147483647/schedule").status_code == 404
    assert client.put(
        "/actions/2147483647/schedule", json={"enabled": True, "every_minutes": 5},
    ).status_code == 404
    for payload in (
        {"enabled": True, "every_minutes": 0},
        {"enabled": True, "every_minutes": 10081},
        {"enabled": True, "every_minutes": "2"},
        {"enabled": "yes", "every_minutes": 2},
        {"enabled": True, "every_minutes": 2, "shell": "echo never"},
    ):
        assert client.put(
            f"/actions/{action_id}/schedule", json=payload,
        ).status_code == 422
    assert client.get(f"/actions/{action_id}/schedule").json()["enabled"] is False

    unknown_tool = BASE.replace("tool: feedbrain", "tool: unsupported")
    bad_action_id = create_action(client, unknown_tool)
    assert client.put(
        f"/actions/{bad_action_id}/schedule", json={"enabled": True},
    ).status_code == 409
    assert client.get(f"/actions/{bad_action_id}/schedule").json()["enabled"] is False

    no_interval_id = create_action(
        client, BASE.replace("schedule:\n  every_minutes: 2\n", ""),
    )
    assert client.put(
        f"/actions/{no_interval_id}/schedule", json={"enabled": True},
    ).status_code == 422
    assert client.put(
        f"/actions/{no_interval_id}/schedule",
        json={"enabled": True, "every_minutes": 3},
    ).status_code == 200

    # Idempotent disabled state even without a persisted schedule row.
    never_configured_id = create_action(client)
    disabled = client.put(
        f"/actions/{never_configured_id}/schedule", json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False


def test_manual_run_blocks_due_scheduled_run(monkeypatch):
    broker, _ = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    monkeypatch.setattr("info_hub.action_run_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)

    assert client.put(
        f"/actions/{action_id}/schedule", json={"enabled": True},
    ).status_code == 200
    manual = client.post(f"/actions/{action_id}/runs")
    assert manual.status_code == 202
    now = utc_now()
    make_due(action_id, now - timedelta(seconds=1))
    result = enqueue_due_action_schedules(broker, now=now)
    assert result["busy"] == 1
    assert len(action_runs(client, action_id)) == 1
    assert action_runs(client, action_id)[0]["initiated_by"] == "api"
    run_id = manual.json()["id"]
    assert claim_next_action_run() == run_id
    process_action_run(run_id, broker)


def test_disabling_prevents_due_run(monkeypatch):
    broker, fake = broker_with_fake()
    monkeypatch.setattr("info_hub.action_schedule_api.configured_broker", lambda: broker)
    client = TestClient(app)
    action_id = create_action(client)

    assert client.put(f"/actions/{action_id}/schedule", json={"enabled": True}).status_code == 200
    assert client.put(f"/actions/{action_id}/schedule", json={"enabled": False}).status_code == 200
    tick = enqueue_due_action_schedules(broker, now=utc_now() + timedelta(days=1))
    assert tick["queued"] == 0
    assert action_runs(client, action_id) == []
    assert fake.requests == []
