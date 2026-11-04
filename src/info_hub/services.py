"""Application services: Source setup, durable sync jobs and resource persistence."""
import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from info_hub.connectors import get_connector
from info_hub.content_services import index_version
from info_hub.contracts import ConnectorItem
from info_hub.db import open_session
from info_hub.fetch import validate_feed_url
from info_hub.models import (
    IngestionRun, Resource, ResourceVersion, Source, Subscription,
    SubscriptionResource, utc_now,
)

logger = logging.getLogger(__name__)


def create_source(session: Session, *, name: str, feed_url: str) -> Source:
    validate_feed_url(feed_url)
    source = Source(name=name, connector_key="rss_atom", config={"feed_url": feed_url})
    session.add(source)
    session.commit()
    session.refresh(source)
    return source


def create_subscription(
    session: Session, *, source: Source, name: str,
    interval_minutes: int, read_enabled: bool, research_enabled: bool,
    enabled: bool,
) -> Subscription:
    if source.connector_key != "rss_atom":
        raise ValueError("Unsupported source connector")
    subscription = Subscription(
        source_id=source.id, name=name, interval_minutes=interval_minutes,
        read_enabled=read_enabled, research_enabled=research_enabled,
        enabled=enabled, next_run_at=utc_now() + timedelta(minutes=interval_minutes),
    )
    session.add(subscription)
    session.commit()
    session.refresh(subscription)
    return subscription


def queue_sync(session: Session, subscription_id: int) -> IngestionRun:
    subscription = session.get(Subscription, subscription_id)
    if subscription is None:
        raise LookupError("Subscription not found")
    source = session.get(Source, subscription.source_id)
    if not subscription.enabled or source is None or not source.enabled:
        raise ValueError("Source or subscription is disabled")
    active = session.scalars(select(IngestionRun).where(
        IngestionRun.subscription_id == subscription_id,
        IngestionRun.status.in_(["queued", "running"]),
    ).order_by(IngestionRun.id.desc()).limit(1)).first()
    if active is not None:
        return active
    run = IngestionRun(source_id=source.id, subscription_id=subscription_id)
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def queue_due_subscriptions() -> None:
    now = utc_now()
    with open_session() as session:
        due = session.scalars(
            select(Subscription)
            .join(Source)
            .where(
                Subscription.enabled.is_(True), Source.enabled.is_(True),
                Subscription.next_run_at <= now,
            )
            .order_by(Subscription.next_run_at, Subscription.id)
            .limit(20)
            .with_for_update(of=Subscription, skip_locked=True)
        ).all()
        for subscription in due:
            active = session.scalar(select(IngestionRun.id).where(
                IngestionRun.subscription_id == subscription.id,
                IngestionRun.status.in_(["queued", "running"]),
            ).limit(1))
            if active is None:
                session.add(IngestionRun(
                    source_id=subscription.source_id,
                    subscription_id=subscription.id,
                ))
            subscription.next_run_at = now + timedelta(minutes=subscription.interval_minutes)
        session.commit()


def recover_abandoned_runs() -> None:
    threshold = utc_now() - timedelta(minutes=5)
    with open_session() as session:
        session.execute(
            update(IngestionRun).where(
                IngestionRun.status == "running",
                IngestionRun.started_at < threshold,
                IngestionRun.attempts < 3,
            ).values(status="queued", started_at=None)
        )
        session.execute(
            update(IngestionRun).where(
                IngestionRun.status == "running",
                IngestionRun.started_at < threshold,
                IngestionRun.attempts >= 3,
            ).values(status="failed", finished_at=utc_now(), error="Worker interrupted repeatedly")
        )
        session.commit()


def claim_next_run() -> int | None:
    with open_session() as session:
        run = session.scalars(
            select(IngestionRun)
            .where(IngestionRun.status == "queued")
            .order_by(IngestionRun.id)
            .limit(1)
            .with_for_update(skip_locked=True)
        ).first()
        if run is None:
            return None
        run.status = "running"
        run.started_at = utc_now()
        run.attempts += 1
        session.commit()
        return run.id


def _save_items(
    session: Session, source_id: int, subscription_id: int,
    items: list[ConnectorItem],
) -> tuple[int, int]:
    created = 0
    updated = 0
    for item in items:
        resource = session.scalar(select(Resource).where(
            Resource.source_id == source_id, Resource.external_id == item.external_id,
        ))
        if resource is None:
            resource = Resource(
                source_id=source_id, external_id=item.external_id, title=item.title,
                canonical_url=item.url, author=item.author, published_at=item.published_at,
            )
            session.add(resource)
            session.flush()
            version_number = 1
            created += 1
        else:
            resource.last_seen_at = utc_now()
            resource.title = item.title
            resource.canonical_url = item.url
            resource.author = item.author
            resource.published_at = item.published_at
            latest = session.scalar(
                select(ResourceVersion).where(ResourceVersion.resource_id == resource.id)
                .order_by(ResourceVersion.version_number.desc()).limit(1)
            )
            latest_feed = session.scalar(
                select(ResourceVersion)
                .where(ResourceVersion.resource_id == resource.id,
                       ResourceVersion.content_origin == "feed")
                .order_by(ResourceVersion.version_number.desc()).limit(1)
            )
            version_number = (latest.version_number + 1) if latest else 1
            if latest_feed is not None and latest_feed.content_hash == item.content_hash:
                version_number = 0
            else:
                updated += 1
        if version_number:
            new_version = ResourceVersion(
                resource_id=resource.id, version_number=version_number,
                content_text=item.content_text or None,
                content_status=item.content_status,
                content_origin="feed",
                content_hash=item.content_hash,
                raw_payload=item.raw_payload,
            )
            session.add(new_version)
            index_version(session, new_version)
            current = (
                session.get(ResourceVersion, resource.current_version_id)
                if resource.current_version_id is not None else None
            )
            if current is None or current.content_origin != "web":
                resource.current_version_id = new_version.id
        if session.get(SubscriptionResource, (subscription_id, resource.id)) is None:
            session.add(SubscriptionResource(
                subscription_id=subscription_id, resource_id=resource.id,
            ))
    return created, updated


def process_run(run_id: int) -> None:
    try:
        with open_session() as session:
            run = session.get(IngestionRun, run_id)
            if run is None or run.status != "running" or run.subscription_id is None:
                raise ValueError("Run is not active")
            subscription = session.get(Subscription, run.subscription_id)
            if subscription is None:
                raise ValueError("Subscription not found")
            source = session.get(Source, subscription.source_id)
            if source is None:
                raise ValueError("Source not found")
            if not source.enabled or not subscription.enabled:
                raise ValueError("Source or subscription disabled")
            connector = get_connector(source.connector_key)
            connector_config = source.config
            etag = subscription.etag
            last_modified = subscription.last_modified
            subscription_id = subscription.id
            source_id = source.id

        batch = connector.sync(
            connector_config, etag=etag, last_modified=last_modified,
        )
        items = batch.items
        with open_session() as session:
            run = session.get(IngestionRun, run_id)
            subscription = session.get(Subscription, subscription_id)
            if run is None or subscription is None:
                raise ValueError("Run or subscription removed")
            created, updated = _save_items(session, source_id, subscription_id, items)
            run.items_seen = len(items)
            run.items_created = created
            run.items_updated = updated
            run.status = "completed"
            run.finished_at = utc_now()
            subscription.last_success_at = utc_now()
            subscription.last_error = None
            subscription.etag = batch.etag[:500] if batch.etag else None
            subscription.last_modified = batch.last_modified[:500] if batch.last_modified else None
            session.commit()
        logger.info("Sync run %s finished: seen=%s created=%s updated=%s",
                    run_id, len(items), created, updated)
    except Exception as exc:
        message = f"{type(exc).__name__}: {str(exc)[:400]}"
        logger.warning("Sync run %s failed: %s", run_id, message)
        with open_session() as session:
            run = session.get(IngestionRun, run_id)
            if run is not None:
                run.status = "failed"
                run.error = message
                run.finished_at = utc_now()
                if run.subscription_id is not None:
                    subscription = session.get(Subscription, run.subscription_id)
                    if subscription is not None:
                        subscription.last_error = message
                session.commit()
