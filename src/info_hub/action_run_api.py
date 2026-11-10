"""Manual Action execution API. Enqueue, don't wait for external HTTP in a request."""
import hashlib
import json
import logging
import re
from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import (
    AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator,
)
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_broker import ToolExecutionError, configured_broker
from info_hub.action_models import Action
from info_hub.external_run_auth import authenticated_external_executor
from info_hub.external_run_registration import register_external_run
from info_hub.action_run_models import ActionRun
from info_hub.action_run_services import RunConflict, RunNotFound, queue_action_run
from info_hub.action_workflow import WorkflowValidationError
from info_hub.db import get_session

logger = logging.getLogger(__name__)
router = APIRouter(tags=["action-runs"])


class ActionRunCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_number: int | None = Field(default=None, ge=1)


def _run_summary(run: ActionRun) -> dict:
    return {
        "id": run.id,
        "action_id": run.action_id,
        "action_version_number": run.version.version_number,
        "status": run.status,
        "initiated_by": run.initiated_by,
        "execution_kind": run.execution_kind,
        "executor_id": run.executor_id,
        "external_run_key": run.external_run_key,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
        "error_code": run.error_code,
        "error_message": run.error_message,
    }


def _run_detail(run: ActionRun) -> dict:
    return {
        **_run_summary(run),
        "steps": [{
            "id": step.id,
            "step_id": step.step_id,
            "capability": step.capability,
            "tool": step.tool,
            "status": step.status,
            "external_run_ref": step.external_run_ref,
            "details": step.details,
            "error_code": step.error_code,
            "error_message": step.error_message,
            "started_at": step.started_at,
            "finished_at": step.finished_at,
        } for step in run.steps],
        "result": None if run.result is None else {
            "status": run.result.status,
            "summary": run.result.summary,
            "details": run.result.details,
            "created_at": run.result.created_at,
        },
    }


@router.post("/actions/{action_id}/runs", status_code=status.HTTP_202_ACCEPTED)
def start_action_run(
    action_id: int, payload: ActionRunCreate | None = None,
    session: Session = Depends(get_session),
) -> dict:
    try:
        broker = configured_broker()
    except ValueError:
        logger.exception("Invalid Action Broker configuration")
        raise HTTPException(
            status_code=503, detail="Action Broker configuration is invalid",
        ) from None
    try:
        run = queue_action_run(
            session, action_id=action_id, broker=broker,
            version_number=payload.version_number if payload else None,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ToolExecutionError, WorkflowValidationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_summary(run)




class ExternalRunCreate(BaseModel):
    """An immutable report of an already finished external AI execution.

    Posting this does not start an AI, the Broker, or a managed worker.
    Storage references are executor claims; Core never dereferences them.
    """
    model_config = ConfigDict(extra="forbid")

    version_number: int = Field(ge=1)
    external_run_key: str = Field(
        min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$",
    )
    initiated_by: Literal["user", "ai", "api", "schedule", "unknown"]
    status: Literal["completed", "failed", "interrupted"]
    summary: str = Field(min_length=1, max_length=320)
    started_at: AwareDatetime | None = None
    finished_at: AwareDatetime | None = None
    error_code: str | None = Field(
        default=None, min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$",
    )
    output_refs: list[str] = Field(default_factory=list, max_length=8)
    storage_status: Literal["reported_saved", "reported_not_saved", "unknown"]

    @field_validator("external_run_key")
    @classmethod
    def validate_key(cls, value: str) -> str:
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,159}", value) is None:
            raise ValueError("Invalid external run key")
        return value

    @field_validator("output_refs")
    @classmethod
    def validate_refs(cls, refs: list[str]) -> list[str]:
        if len(set(refs)) != len(refs):
            raise ValueError("Duplicate output reference")
        for uri in refs:
            if len(uri) > 600 or any(ord(ch) < 33 or ord(ch) == 127 for ch in uri):
                raise ValueError("Invalid output reference")
            try:
                parts = urlsplit(uri)
            except ValueError:
                raise ValueError("Invalid output reference") from None
            if (parts.scheme != "https" or not parts.hostname
                    or parts.username is not None or parts.password is not None
                    or parts.query or parts.fragment or not parts.path):
                raise ValueError("Use HTTPS references without credentials or query strings")
        return refs

    @model_validator(mode="after")
    def validate_claim(self):
        if self.started_at and self.finished_at and self.finished_at < self.started_at:
            raise ValueError("finished_at precedes started_at")
        if self.status == "completed" and self.error_code is not None:
            raise ValueError("Completed run must not have an error_code")
        if self.storage_status == "reported_saved" and not self.output_refs:
            raise ValueError("Reported saved result requires an output reference")
        if self.storage_status == "reported_not_saved" and self.output_refs:
            raise ValueError("Unstored result must not have output references")
        return self


@router.post("/actions/{action_id}/external-runs", status_code=status.HTTP_201_CREATED)
def record_external_action_run(
    action_id: int, payload: ExternalRunCreate, response: Response,
    executor_id: str = Depends(authenticated_external_executor),
    session: Session = Depends(get_session),
) -> dict:
    """Authenticated, post-hoc registration in the existing ActionRun history."""
    fingerprint_data = {
        "action_id": action_id,
        "executor_id": executor_id,
        "payload": payload.model_dump(mode="json"),
    }
    fingerprint = hashlib.sha256(json.dumps(
        fingerprint_data, sort_keys=True, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    try:
        run, created = register_external_run(
            session, action_id=action_id, version_number=payload.version_number,
            external_run_key=payload.external_run_key, executor_id=executor_id,
            initiated_by=payload.initiated_by, status=payload.status,
            summary=payload.summary, started_at=payload.started_at,
            finished_at=payload.finished_at, output_refs=payload.output_refs,
            storage_status=payload.storage_status, error_code=payload.error_code,
            registration_fingerprint=fingerprint,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    response.status_code = status.HTTP_201_CREATED if created else status.HTTP_200_OK
    return _run_detail(run)

@router.get("/actions/{action_id}/runs")
def list_action_runs(
    action_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[dict]:
    if session.get(Action, action_id) is None:
        raise HTTPException(status_code=404, detail="Action not found")
    runs = session.scalars(
        select(ActionRun).where(ActionRun.action_id == action_id)
        .order_by(ActionRun.id.desc()).offset(offset).limit(limit)
    ).all()
    return [_run_summary(run) for run in runs]


@router.get("/action-runs/{run_id}")
def get_action_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(ActionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Action run not found")
    return _run_detail(run)
