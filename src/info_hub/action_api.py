"""Action Registry HTTP API: create, read and publish append-only definition versions."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_models import Action, ActionVersion
from info_hub.action_schedule_models import ActionSchedule
from info_hub.action_services import (
    ActionNotFound, ActionVersionConflict, create_action, get_action_version,
    publish_action_version,
)
from info_hub.action_workflow import MAX_DOCUMENT_CHARS, WorkflowValidationError
from info_hub.db import get_session

router = APIRouter(tags=["actions"])


class ActionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    definition_yaml: str = Field(min_length=1, max_length=MAX_DOCUMENT_CHARS)


class ActionVersionCreate(ActionCreate):
    expected_version: int = Field(ge=1)


def _action_summary(action: Action) -> dict:
    return {
        "id": action.id,
        "name": action.name,
        "current_version_number": action.current_version_number,
        "created_at": action.created_at,
        "updated_at": action.updated_at,
    }


def _version_detail(
    version: ActionVersion, *, schedule_active: bool = False,
) -> dict:
    return {
        "id": version.id,
        "action_id": version.action_id,
        "version_number": version.version_number,
        "definition_yaml": version.source_yaml,
        "definition": version.definition,
        "created_at": version.created_at,
        # Only the current version can be targeted by a mutable active schedule.
        "schedule_active": schedule_active,
    }


def _action_detail(
    action: Action, version: ActionVersion, *, schedule_active: bool = False,
) -> dict:
    return {
        **_action_summary(action),
        "current_version": _version_detail(version, schedule_active=schedule_active),
    }


def _schedule_is_active(session: Session, action_id: int) -> bool:
    enabled = session.scalar(
        select(ActionSchedule.enabled).where(ActionSchedule.action_id == action_id)
    )
    return bool(enabled)


def _require_action(session: Session, action_id: int) -> Action:
    action = session.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")
    return action


@router.post("/actions", status_code=status.HTTP_201_CREATED)
def add_action(payload: ActionCreate, session: Session = Depends(get_session)) -> dict:
    try:
        action, version = create_action(session, source_yaml=payload.definition_yaml)
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _action_detail(action, version)


@router.get("/actions")
def list_actions(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[dict]:
    actions = session.scalars(select(Action).order_by(Action.id).offset(offset).limit(limit))
    return [_action_summary(action) for action in actions]


@router.get("/actions/{action_id}")
def read_action(action_id: int, session: Session = Depends(get_session)) -> dict:
    action = _require_action(session, action_id)
    version = get_action_version(
        session, action_id=action.id, version_number=action.current_version_number,
    )
    if version is None:
        raise HTTPException(status_code=500, detail="Current Action version is missing")
    return _action_detail(
        action, version, schedule_active=_schedule_is_active(session, action_id),
    )


@router.post("/actions/{action_id}/versions", status_code=status.HTTP_201_CREATED)
def add_action_version(
    action_id: int, payload: ActionVersionCreate,
    session: Session = Depends(get_session),
) -> dict:
    try:
        action, version = publish_action_version(
            session, action_id=action_id,
            expected_version=payload.expected_version,
            source_yaml=payload.definition_yaml,
        )
    except WorkflowValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except ActionNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ActionVersionConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _action_detail(
        action, version, schedule_active=_schedule_is_active(session, action_id),
    )


@router.get("/actions/{action_id}/versions")
def list_action_versions(
    action_id: int,
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[dict]:
    action = _require_action(session, action_id)
    active = _schedule_is_active(session, action_id)
    versions = session.scalars(
        select(ActionVersion).where(ActionVersion.action_id == action_id)
        .order_by(ActionVersion.version_number.desc()).offset(offset).limit(limit)
    )
    return [
        _version_detail(
            version,
            schedule_active=active
            and version.version_number == action.current_version_number,
        )
        for version in versions
    ]


@router.get("/actions/{action_id}/versions/{version_number}")
def read_action_version(
    action_id: int, version_number: int, session: Session = Depends(get_session),
) -> dict:
    action = _require_action(session, action_id)
    version = get_action_version(
        session, action_id=action_id, version_number=version_number,
    )
    if version is None:
        raise HTTPException(status_code=404, detail="Action version not found")
    return _version_detail(
        version,
        schedule_active=(
            version_number == action.current_version_number
            and _schedule_is_active(session, action_id)
        ),
    )
