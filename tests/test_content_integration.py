"""Database integration: RSS, web extraction and chunk search.

Only enabled against disposable PostgreSQL.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from info_hub.db import open_session
from info_hub.main import app
from info_hub.models import ContentChunk, ResourceVersion
from info_hub.services import claim_next_run, process_run
from info_hub.web_content import ExtractedPage
from tests.test_feeds import RSS

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Requires disposable PostgreSQL",
)


def test_rss_chunks_then_web_extraction(monkeypatch):
    monkeypatch.setattr(
        "info_hub.connectors.fetch_feed",
        lambda *_args, **_kwargs: (200, RSS, None, None),
    )
    client = TestClient(app)
    source_response = client.post("/sources", json={
        "name": "Content fixture", "feed_url": "https://example.org/rss",
    })
    assert source_response.status_code == 201
    source_id = source_response.json()["id"]
    subscription = client.post(f"/sources/{source_id}/subscriptions", json={
        "name": "Content fixture subscription",
    })
    assert subscription.status_code == 201
    subscription_id = subscription.json()["id"]
    run = client.post(f"/subscriptions/{subscription_id}/sync")
    assert run.status_code == 202
    run_id = run.json()["id"]
    assert claim_next_run() == run_id
    process_run(run_id)
    assert client.get(f"/runs/{run_id}").json()["status"] == "completed"

    entries = client.get("/resources", params={"source_id": source_id}).json()
    assert len(entries) == 1
    resource_id = entries[0]["id"]
    assert entries[0]["content_origin"] == "feed"
    assert entries[0]["content_status"] == "partial"
    original_hits = client.get("/search", params={
        "q": "Longer", "source_id": source_id,
    })
    assert original_hits.status_code == 200
    assert original_hits.json()

    full_text = "This is a substantial extracted article. " * 20 + " uniquesearchword"
    monkeypatch.setattr(
        "info_hub.content_services.fetch_public_article",
        lambda _url: ExtractedPage(
            source_url="https://example.org/post-1",
            text=full_text,
            content_hash="contenthash-1",
        ),
    )
    extracted = client.post(f"/resources/{resource_id}/extract")
    assert extracted.status_code == 200, extracted.text
    assert extracted.json()["created"] is True
    current = client.get(f"/resources/{resource_id}").json()
    assert current["content_origin"] == "web"
    assert current["content_status"] == "full"
    assert current["content_text"] == full_text
    assert current["versions_available"] == [1, 2]

    search = client.get("/search", params={
        "q": "uniquesearchword", "source_id": source_id,
    })
    assert search.status_code == 200, search.text
    hits = search.json()
    assert hits and hits[0]["resource_id"] == resource_id
    assert hits[0]["chunk_id"] is not None

    repeated = client.post(f"/resources/{resource_id}/extract")
    assert repeated.status_code == 200
    assert repeated.json()["created"] is False

    with open_session() as session:
        versions = session.scalars(
            select(ResourceVersion).where(ResourceVersion.resource_id == resource_id)
            .order_by(ResourceVersion.version_number)
        ).all()
        assert len(versions) == 2
        chunks = session.scalars(select(ContentChunk).where(
            ContentChunk.resource_version_id == versions[1].id,
        )).all()
        assert len(chunks) > 0
        for chunk in chunks:
            assert chunk.text == full_text[chunk.char_start:chunk.char_end]


def test_metadata_only_title_search_keeps_current_version(monkeypatch):
    from info_hub.contracts import ConnectorItem, SyncBatch

    item = ConnectorItem(
        external_id="meta-only-guid",
        title="Distinctive Metadata Only Title",
        url="https://example.org/metadata-only",
        author=None,
        published_at=None,
        content_text="",
        content_status="metadata_only",
        content_hash="test-meta-hash",
        raw_payload={"kind": "test"},
    )
    monkeypatch.setattr(
        "info_hub.connectors.RssAtomConnector.sync",
        lambda _self, _config, *, etag, last_modified: SyncBatch(items=[item]),
    )
    client = TestClient(app)
    source = client.post("/sources", json={
        "name": "Metadata fixture", "feed_url": "https://example.org/meta-feed",
    })
    assert source.status_code == 201
    source_id = source.json()["id"]
    sub = client.post(f"/sources/{source_id}/subscriptions", json={
        "name": "Metadata subscription",
    })
    assert sub.status_code == 201
    run = client.post(f"/subscriptions/{sub.json()['id']}/sync")
    assert run.status_code == 202
    assert claim_next_run() == run.json()["id"]
    process_run(run.json()["id"])
    assert client.get(f"/runs/{run.json()['id']}").json()["status"] == "completed"

    entries = client.get("/resources", params={"source_id": source_id}).json()
    assert len(entries) == 1
    resource = entries[0]
    assert resource["content_status"] == "metadata_only"
    assert resource["version"] == 1

    response = client.get("/search", params={
        "q": "Metadata Only", "source_id": source_id,
    })
    assert response.status_code == 200, response.text
    hits = response.json()
    assert hits and hits[0]["resource_id"] == resource["id"]
    assert hits[0]["chunk_id"] is None
