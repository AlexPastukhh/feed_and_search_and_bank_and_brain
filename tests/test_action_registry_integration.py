"""Action Registry API + immutable storage, against a disposable migrated PostgreSQL DB.

Run only with RUN_DB_INTEGRATION_TESTS=1 and an isolated DATABASE_URL.
"""
import os

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import DBAPIError

from info_hub.action_models import ActionVersion
from info_hub.db import open_session
from info_hub.main import app

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DB_INTEGRATION_TESTS") != "1",
    reason="Only enable against migrated disposable PostgreSQL",
)

FIRST_YAML = """\
name: Read the RSS archive
instruction: |
  Check the configured source for new publications.
workflow:
  schema: 1
  steps:
    - id: refresh
      capability: information.sync
      with:
        source: ai_articles
schedule:
  every_minutes: 60
"""

SECOND_YAML = """\
name: Refresh selected publications
instruction: |
  Check new publications and prepare a summary for later analysis.
workflow:
  schema: 1
  steps:
    - id: refresh
      capability: information.sync
      with:
        source: ai_articles
"""


def test_action_registry_version_history_and_immutable_database():
    client = TestClient(app)

    created = client.post("/actions", json={"definition_yaml": FIRST_YAML})
    assert created.status_code == 201, created.text
    action_id = created.json()["id"]
    assert created.json()["name"] == "Read the RSS archive"
    assert created.json()["current_version_number"] == 1
    first = created.json()["current_version"]
    assert first["definition_yaml"] == FIRST_YAML
    assert first["definition"]["workflow"]["steps"][0]["with"]["source"] == "ai_articles"
    assert first["definition"]["schedule"] == {"every_minutes": 60}
    assert first["schedule_active"] is False

    listed = client.get("/actions", params={"limit": 100})
    assert listed.status_code == 200
    assert any(item["id"] == action_id for item in listed.json())

    detail = client.get(f"/actions/{action_id}")
    assert detail.status_code == 200
    assert detail.json()["current_version"]["version_number"] == 1

    newer = client.post(
        f"/actions/{action_id}/versions",
        json={"definition_yaml": SECOND_YAML, "expected_version": 1},
    )
    assert newer.status_code == 201, newer.text
    assert newer.json()["name"] == "Refresh selected publications"
    assert newer.json()["current_version_number"] == 2

    versions = client.get(f"/actions/{action_id}/versions")
    assert versions.status_code == 200
    assert [v["version_number"] for v in versions.json()] == [2, 1]

    original = client.get(f"/actions/{action_id}/versions/1")
    assert original.status_code == 200
    assert original.json()["definition_yaml"] == FIRST_YAML
    assert original.json()["definition"]["schedule"] == {"every_minutes": 60}
    assert original.json()["schedule_active"] is False

    newest = client.get(f"/actions/{action_id}/versions/2")
    assert newest.status_code == 200
    assert newest.json()["definition_yaml"] == SECOND_YAML
    assert newest.json()["definition"]["schedule"] is None

    # Stale editors cannot overwrite the current version or create a third one.
    stale = client.post(
        f"/actions/{action_id}/versions",
        json={"definition_yaml": FIRST_YAML, "expected_version": 1},
    )
    assert stale.status_code == 409
    assert client.get(f"/actions/{action_id}").json()["current_version_number"] == 2
    assert len(client.get(f"/actions/{action_id}/versions").json()) == 2

    # The database blocks mutation even if a caller bypasses the API.
    with open_session() as session:
        saved = session.scalar(
            select(ActionVersion).where(
                ActionVersion.action_id == action_id, ActionVersion.version_number == 1,
            )
        )
        saved.source_yaml = "changed behind the API"
        with pytest.raises(DBAPIError, match="ActionVersion records are append-only"):
            session.commit()
        session.rollback()

    assert client.get(f"/actions/{action_id}/versions/1").json()["definition_yaml"] == FIRST_YAML


def test_action_registry_errors_and_instruction_only_action():
    client = TestClient(app)
    no_workflow = client.post(
        "/actions",
        json={"definition_yaml": "name: Simple note\ninstruction: Research new methods\n"},
    )
    assert no_workflow.status_code == 201
    action_id = no_workflow.json()["id"]
    assert no_workflow.json()["current_version"]["definition"]["workflow"] is None

    bad = client.post("/actions", json={
        "definition_yaml": "name: A\nname: B\ninstruction: Work\n",
    })
    assert bad.status_code == 422
    unknown_flag = client.post(
        "/actions", json={"definition_yaml": FIRST_YAML, "execute": True},
    )
    assert unknown_flag.status_code == 422
    unsupported = client.post("/actions", json={
        "definition_yaml": "name: A\ninstruction: Work\nworkflow:\n  schema: 1\n"
                           "  steps:\n    - id: one\n      capability: system.shell\n"
                           "      script: 'rm -rf /'\n",
    })
    assert unsupported.status_code == 422

    assert client.get("/actions/2147483647").status_code == 404
    assert client.get(f"/actions/{action_id}/versions/4444").status_code == 404
    assert client.get("/actions/2147483647/versions").status_code == 404
    assert client.post(
        "/actions/2147483647/versions",
        json={"definition_yaml": FIRST_YAML, "expected_version": 1},
    ).status_code == 404
    assert client.post(
        f"/actions/{action_id}/versions",
        json={"definition_yaml": SECOND_YAML, "expected_version": 0},
    ).status_code == 422
