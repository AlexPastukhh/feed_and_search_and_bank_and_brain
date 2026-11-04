"""Explicit opt-in schedule management; declaring YAML never enables a schedule."""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_models import Action
from info_hub.action_broker import ToolExecutionError, configured_broker
from info_hub.action_workflow import WorkflowValidationError
from info_hub.action_schedule_models import ActionSchedule
from info_hub.action_schedule_services import (
    ScheduleIntervalRequired, schedule_summary, set_action_schedule,
)
from info_hub.action_run_services import RunNotFound
from info_hub.db import get_session

router = APIRouter(tags=["action-schedules"])


class ScheduleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(strict=True)
    every_minutes: int | None = Field(default=None, strict=True, ge=1, le=10_080)


@router.get("/actions/{action_id}/schedule")
def read_action_schedule(
    action_id: int, session: Session = Depends(get_session),
) -> dict:
    if session.get(Action, action_id) is None:
        raise HTTPException(status_code=404, detail="Action not found")
    schedule = session.scalar(
        select(ActionSchedule).where(ActionSchedule.action_id == action_id)
    )
    return schedule_summary(schedule, action_id)


@router.put("/actions/{action_id}/schedule")
def update_action_schedule(
    action_id: int, payload: ScheduleUpdate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        broker = configured_broker() if payload.enabled else None
    except ValueError:
        raise HTTPException(
            status_code=503, detail="Action Broker configuration is invalid",
        ) from None
    try:
        schedule = set_action_schedule(
            session, action_id=action_id,
            enabled=payload.enabled, every_minutes=payload.every_minutes,
            broker=broker,
        )
    except RunNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except (ToolExecutionError, WorkflowValidationError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except (ScheduleIntervalRequired, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return schedule_summary(schedule, action_id)
