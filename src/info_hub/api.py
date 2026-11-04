"""Small HTTP surface for the first end-to-end RSS ingestion feature."""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from info_hub.db import get_session
from info_hub.models import (
    IngestionRun, Resource, ResourceVersion, Source, Subscription, SubscriptionResource,
)
from info_hub.services import create_source, create_subscription, queue_sync

router = APIRouter(tags=["sources"])


class SourceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    feed_url: str = Field(min_length=8, max_length=2048)


class SubscriptionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    interval_minutes: int = Field(default=60, ge=10, le=10_080)
    read_enabled: bool = True
    research_enabled: bool = True
    enabled: bool = True


def _source_dict(source: Source) -> dict:
    return {
        "id": source.id, "name": source.name,
        "connector_key": source.connector_key, "config": source.config,
        "enabled": source.enabled,
    }


def _subscription_dict(subscription: Subscription) -> dict:
    return {
        "id": subscription.id, "source_id": subscription.source_id,
        "name": subscription.name, "operation": subscription.operation,
        "interval_minutes": subscription.interval_minutes,
        "read_enabled": subscription.read_enabled,
        "research_enabled": subscription.research_enabled,
        "enabled": subscription.enabled,
        "next_run_at": subscription.next_run_at,
        "last_success_at": subscription.last_success_at,
        "last_error": subscription.last_error,
    }


def _run_dict(run: IngestionRun) -> dict:
    return {
        "id": run.id, "source_id": run.source_id,
        "subscription_id": run.subscription_id, "status": run.status,
        "attempts": run.attempts,
        "items_seen": run.items_seen,
        "items_created": run.items_created,
        "items_updated": run.items_updated,
        "error": run.error,
        "created_at": run.created_at,
        "started_at": run.started_at,
        "finished_at": run.finished_at,
    }


def _resource_dict(resource: Resource, version: ResourceVersion | None) -> dict:
    return {
        "id": resource.id, "source_id": resource.source_id,
        "external_id": resource.external_id, "resource_type": resource.resource_type,
        "title": resource.title, "canonical_url": resource.canonical_url,
        "author": resource.author, "published_at": resource.published_at,
        "first_seen_at": resource.first_seen_at,
        "last_seen_at": resource.last_seen_at,
        "content_status": version.content_status if version else "unavailable",
        "content_origin": version.content_origin if version else None,
        "version": version.version_number if version else None,
        "content_text": version.content_text if version else None,
    }


def _latest_version(session: Session, resource: Resource) -> ResourceVersion | None:
    if resource.current_version_id is not None:
        return session.get(ResourceVersion, resource.current_version_id)
    return session.scalar(
        select(ResourceVersion).where(ResourceVersion.resource_id == resource.id)
        .order_by(ResourceVersion.version_number.desc()).limit(1)
    )


@router.post("/sources", status_code=status.HTTP_201_CREATED)
def add_source(payload: SourceCreate, session: Session = Depends(get_session)) -> dict:
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Source name cannot be empty")
    try:
        source = create_source(
            session, name=payload.name.strip(), feed_url=payload.feed_url.strip(),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _source_dict(source)


@router.get("/sources")
def list_sources(session: Session = Depends(get_session)) -> list[dict]:
    sources = session.scalars(select(Source).order_by(Source.id)).all()
    return [_source_dict(source) for source in sources]


@router.post("/sources/{source_id}/subscriptions", status_code=status.HTTP_201_CREATED)
def add_subscription(
    source_id: int, payload: SubscriptionCreate, session: Session = Depends(get_session),
) -> dict:
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    if not payload.name.strip():
        raise HTTPException(status_code=422, detail="Subscription name cannot be empty")
    subscription = create_subscription(
        session, source=source, name=payload.name.strip(),
        interval_minutes=payload.interval_minutes,
        read_enabled=payload.read_enabled,
        research_enabled=payload.research_enabled,
        enabled=payload.enabled,
    )
    return _subscription_dict(subscription)


@router.get("/subscriptions")
def list_subscriptions(
    source_id: int | None = None, session: Session = Depends(get_session),
) -> list[dict]:
    query = select(Subscription).order_by(Subscription.id)
    if source_id is not None:
        query = query.where(Subscription.source_id == source_id)
    return [_subscription_dict(s) for s in session.scalars(query)]


@router.post("/subscriptions/{subscription_id}/sync", status_code=status.HTTP_202_ACCEPTED)
def sync_subscription(subscription_id: int, session: Session = Depends(get_session)) -> dict:
    try:
        run = queue_sync(session, subscription_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _run_dict(run)


@router.get("/runs/{run_id}")
def get_run(run_id: int, session: Session = Depends(get_session)) -> dict:
    run = session.get(IngestionRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return _run_dict(run)


@router.get("/resources")
def list_resources(
    source_id: int | None = None,
    subscription_id: int | None = None,
    limit: int = Query(default=30, ge=1, le=100),
    session: Session = Depends(get_session),
) -> list[dict]:
    query = select(Resource)
    if source_id is not None:
        query = query.where(Resource.source_id == source_id)
    if subscription_id is not None:
        query = query.join(
            SubscriptionResource, SubscriptionResource.resource_id == Resource.id,
        ).where(SubscriptionResource.subscription_id == subscription_id)
    query = query.order_by(Resource.published_at.desc().nullslast(), Resource.id.desc())
    resources = session.scalars(query.limit(limit)).all()
    return [_resource_dict(resource, _latest_version(session, resource)) for resource in resources]


@router.get("/resources/{resource_id}")
def get_resource(resource_id: int, session: Session = Depends(get_session)) -> dict:
    resource = session.get(Resource, resource_id)
    if resource is None:
        raise HTTPException(status_code=404, detail="Resource not found")
    data = _resource_dict(resource, _latest_version(session, resource))
    data["versions_available"] = session.scalars(
        select(ResourceVersion.version_number)
        .where(ResourceVersion.resource_id == resource.id)
        .order_by(ResourceVersion.version_number)
    ).all()
    return data
