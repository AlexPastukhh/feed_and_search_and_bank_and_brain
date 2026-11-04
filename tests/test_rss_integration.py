"""Real-Postgres RSS E2E; only run on an explicitly disposable test database."""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from info_hub.db import open_session
from info_hub.main import app
from info_hub.models import IngestionRun, ResourceVersion
from info_hub.services import claim_next_run, process_run
from tests.test_feeds import RSS


@pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Only enable against disposable PostgreSQL (e.g. CI)",
)
def test_rss_api_worker_and_idempotency(monkeypatch):
    """API -> queued job -> claimed job -> parse -> Postgres -> API."""
    monkeypatch.setattr(
        "info_hub.connectors.fetch_feed",
        lambda *_args, **_kwargs: (200, RSS, "test-etag", None),
    )
    client = TestClient(app)
    created = client.post("/sources", json={
        "name": "Integration fixture", "feed_url": "https://example.org/rss",
    })
    assert created.status_code == 201, created.text
    source_id = created.json()["id"]

    subscription = client.post(f"/sources/{source_id}/subscriptions", json={
        "name": "Test", "interval_minutes": 60,
        "read_enabled": True, "research_enabled": True,
    })
    assert subscription.status_code == 201, subscription.text
    subscription_id = subscription.json()["id"]

    created_run = client.post(f"/subscriptions/{subscription_id}/sync")
    assert created_run.status_code == 202, created_run.text
    first_run_id = created_run.json()["id"]
    assert claim_next_run() == first_run_id
    process_run(first_run_id)

    first = client.get(f"/runs/{first_run_id}")
    assert first.status_code == 200
    assert first.json()["status"] == "completed"
    assert first.json()["items_created"] == 1

    resources = client.get("/resources", params={"source_id": source_id})
    assert resources.status_code == 200
    (resource,) = resources.json()
    assert resource["title"] == "RSS & Python"
    assert resource["content_text"] == "Longer text"
    assert resource["content_status"] == "partial"
    resource_id = resource["id"]

    second_run = client.post(f"/subscriptions/{subscription_id}/sync")
    assert second_run.status_code == 202
    second_run_id = second_run.json()["id"]
    assert claim_next_run() == second_run_id
    process_run(second_run_id)
    second = client.get(f"/runs/{second_run_id}").json()
    assert second["status"] == "completed"
    assert second["items_created"] == 0
    assert second["items_updated"] == 0

    with open_session() as session:
        versions = session.scalars(
            select(ResourceVersion).where(ResourceVersion.resource_id == resource_id)
        ).all()
        assert len(versions) == 1

    # An unmodified feed served as HTTP 304 creates no new versions.
    monkeypatch.setattr(
        "info_hub.connectors.fetch_feed",
        lambda *_args, **_kwargs: (304, b"", "test-etag", None),
    )
    third_run = client.post(f"/subscriptions/{subscription_id}/sync")
    assert third_run.status_code == 202
    third_run_id = third_run.json()["id"]
    assert claim_next_run() == third_run_id
    process_run(third_run_id)
    assert client.get(f"/runs/{third_run_id}").json()["items_seen"] == 0

    # A changed item with the same GUID creates a version, not a duplicate resource.
    changed = RSS.replace(b"Longer", b"Updated")
    monkeypatch.setattr(
        "info_hub.connectors.fetch_feed",
        lambda *_args, **_kwargs: (200, changed, "test-etag", None),
    )
    fourth_run = client.post(f"/subscriptions/{subscription_id}/sync")
    assert fourth_run.status_code == 202
    fourth_run_id = fourth_run.json()["id"]
    assert claim_next_run() == fourth_run_id
    process_run(fourth_run_id)
    fourth = client.get(f"/runs/{fourth_run_id}").json()
    assert fourth["items_created"] == 0
    assert fourth["items_updated"] == 1
    detail = client.get(f"/resources/{resource_id}")
    assert detail.status_code == 200
    assert detail.json()["versions_available"] == [1, 2]
    assert detail.json()["content_text"] == "Updated text"
