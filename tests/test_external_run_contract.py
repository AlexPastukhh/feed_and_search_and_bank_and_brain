"""Offline contract tests: no database or running ChatGPT/Tools required."""
import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import SecretStr, ValidationError
from starlette.requests import Request

from info_hub.action_run_api import ExternalRunCreate
from info_hub.external_run_auth import authenticated_external_executor

EXECUTORS = {"fortis-chatgpt": "a" * 48, "other-ai": "b" * 48}
REF = "https://github.com/owner/repo/blob/abc123/docs/report.json"


def _request(authorization: str = "") -> Request:
    hdrs = [] if not authorization else [
        (b"authorization", authorization.encode("ascii")),
    ]
    return Request({"type": "http", "method": "POST", "path": "/", "headers": hdrs})


def _payload(**overrides) -> dict:
    data = {
        "version_number": 3,
        "external_run_key": "action3-v3-manual01",
        "initiated_by": "user",
        "status": "completed",
        "summary": "Completed external research",
        "output_refs": [REF],
        "storage_status": "reported_saved",
    }
    data.update(overrides)
    return data


def test_registration_disabled_by_default(monkeypatch):
    from info_hub import external_run_auth
    monkeypatch.setattr(
        external_run_auth, "get_settings",
        lambda: SimpleNamespace(action_external_run_tokens=SecretStr("")),
    )
    with pytest.raises(HTTPException) as exc:
        authenticated_external_executor(_request("Bearer " + EXECUTORS["fortis-chatgpt"]))
    assert exc.value.status_code == 503


def test_executor_identity_is_bound_to_secret(monkeypatch):
    from info_hub import external_run_auth
    monkeypatch.setattr(
        external_run_auth, "get_settings",
        lambda: SimpleNamespace(
            action_external_run_tokens=SecretStr(json.dumps(EXECUTORS)),
        ),
    )
    assert authenticated_external_executor(
        _request("Bearer " + EXECUTORS["fortis-chatgpt"])
    ) == "fortis-chatgpt"
    assert authenticated_external_executor(
        _request("Bearer " + EXECUTORS["other-ai"])
    ) == "other-ai"
    for header, expected in [
        ("", 401),
        ("Bearer wrong", 403),
        ("Basic " + EXECUTORS["fortis-chatgpt"], 401),
    ]:
        with pytest.raises(HTTPException) as exc:
            authenticated_external_executor(_request(header))
        assert exc.value.status_code == expected


@pytest.mark.parametrize("bad", [
    {"output_refs": ["http://localhost:8000/private"]},
    {"output_refs": ["https://x.example/file?token=secret"]},
    {"output_refs": ["https://u:p@example.com/file"]},
    {"output_refs": [REF, REF]},
    {"storage_status": "reported_saved", "output_refs": []},
    {"storage_status": "reported_not_saved", "output_refs": [REF]},
    {"status": "queued"},
    {"status": "running"},
    {"external_run_key": "bad key"},
    {"status": "completed", "error_code": "foo"},
    {"started_at": "2026-11-10T17:00:00Z", "finished_at": "2026-11-10T16:00:00Z"},
    {"started_at": "2026-11-10T17:00:00"},
])
def test_invalid_external_claims_rejected(bad):
    with pytest.raises(ValidationError):
        ExternalRunCreate.model_validate(_payload(**bad))


def test_known_and_unknown_timestamps_are_not_fabricated():
    record = ExternalRunCreate.model_validate(_payload())
    assert record.started_at is None
    assert record.finished_at is None
    assert record.status == "completed"
    assert record.storage_status == "reported_saved"
    record = ExternalRunCreate.model_validate(
        _payload(started_at=datetime(2026, 11, 10, 8, tzinfo=timezone.utc))
    )
    assert record.finished_at is None
    assert record.started_at.tzinfo is not None
