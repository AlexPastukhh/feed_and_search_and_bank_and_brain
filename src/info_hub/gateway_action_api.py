"""Narrow, authenticated READ projection for the Fortis Gateway."""
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.action_models import Action
from info_hub.action_schedule_models import ActionSchedule
from info_hub.action_services import get_action_version
from info_hub.db import get_session
from info_hub.gateway_read_auth import authorize_gateway_read

MAX_RESPONSE_BYTES = 65_536
router = APIRouter(prefix="/gateway/v1", tags=["gateway-action-core"])


class GatewayActionRead(BaseModel):
    """Closed public projection; never return ORM or raw database objects."""

    model_config = ConfigDict(extra="forbid", strict=True)
    action_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    category: str = Field(min_length=1, max_length=80)
    current_version_number: int = Field(ge=1)
    definition_yaml: str = Field(min_length=1, max_length=65_536)
    schedule_active: bool


@router.get("/actions/{action_id}", response_model=GatewayActionRead)
def read_gateway_action(
    action_id: int,
    _authorized: None = Depends(authorize_gateway_read),
    session: Session = Depends(get_session),
) -> JSONResponse:
    """Read only the current immutable Action definition for IDs 3 and 4."""
    action = session.get(Action, action_id)
    if action is None:
        raise HTTPException(status_code=404, detail="Action not found")

    version = get_action_version(
        session,
        action_id=action_id,
        version_number=action.current_version_number,
    )
    if version is None or not isinstance(version.definition, dict):
        raise HTTPException(status_code=500, detail="Current Action version is unavailable")

    enabled = session.scalar(
        select(ActionSchedule.enabled).where(ActionSchedule.action_id == action_id)
    )
    try:
        projection = GatewayActionRead.model_validate({
            "action_id": action.id,
            "name": action.name,
            "category": version.definition.get("category", "general"),
            "current_version_number": action.current_version_number,
            "definition_yaml": version.source_yaml,
            "schedule_active": bool(enabled),
        })
        response = JSONResponse(
            content=projection.model_dump(mode="json"),
            headers={
                "Cache-Control": "no-store",
                "Pragma": "no-cache",
                "X-Content-Type-Options": "nosniff",
            },
        )
    except (TypeError, ValueError, ValidationError):
        raise HTTPException(
            status_code=500, detail="Current Action version is invalid",
        ) from None

    if len(response.body) > MAX_RESPONSE_BYTES:
        raise HTTPException(
            status_code=500, detail="Gateway READ response exceeds the configured limit",
        )
    return response


@router.api_route(
    "/actions/{action_id}",
    methods=["HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
def reject_gateway_non_get_method(action_id: int) -> None:
    """Only the explicitly declared GET method is supported."""
    raise HTTPException(status_code=405, detail="Gateway READ supports GET only")


@router.api_route(
    "/actions/{action_id}/",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
def reject_noncanonical_gateway_route(action_id: int) -> None:
    """Reject trailing-slash variants rather than redirecting Gateway requests."""
    raise HTTPException(status_code=404, detail="Gateway route not found")


@router.api_route(
    "/{unmatched:path}",
    methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    include_in_schema=False,
)
def reject_unknown_gateway_route(unmatched: str) -> None:
    """Reject all other paths so the Gateway namespace never redirects."""
    raise HTTPException(status_code=404, detail="Gateway route not found")
