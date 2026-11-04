"""Manual Action execution API. Enqueue, don't wait for external HTTP in a request."""
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_broker import ToolExecutionError, configured_broker
from info_hub.action_models import Action
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
