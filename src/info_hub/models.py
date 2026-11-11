"""Persisted contracts for sources, subscriptions and retrieved materials."""
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column, relationship

from info_hub.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    connector_key: Mapped[str] = mapped_column(String(60), nullable=False, default="rss_atom")
    config: Mapped[dict] = mapped_column(JSONB, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    subscriptions: Mapped[list["Subscription"]] = relationship(back_populates="source")


class Subscription(Base):
    __tablename__ = "subscriptions"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    operation: Mapped[str] = mapped_column(String(40), nullable=False, default="sync")
    parameters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    interval_minutes: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    read_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    research_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(String(500))
    last_modified: Mapped[str | None] = mapped_column(String(500))
    source: Mapped[Source] = relationship(back_populates="subscriptions")


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    subscription_id: Mapped[int | None] = mapped_column(ForeignKey("subscriptions.id"), index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_seen: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_created: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    items_updated: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class Resource(Base):
    __tablename__ = "resources"
    __table_args__ = (UniqueConstraint("source_id", "external_id", name="uq_source_external_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("sources.id"), index=True)
    external_id: Mapped[str] = mapped_column(String(700), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), default="article")
    title: Mapped[str] = mapped_column(String(1000), nullable=False)
    canonical_url: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str | None] = mapped_column(String(500))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    current_version_id: Mapped[int | None] = mapped_column(
        ForeignKey("resource_versions.id", name="fk_resources_current_version_id"),
    )
    versions: Mapped[list["ResourceVersion"]] = relationship(
        back_populates="resource", foreign_keys="ResourceVersion.resource_id",
    )


class ResourceVersion(Base):
    __tablename__ = "resource_versions"
    __table_args__ = (UniqueConstraint("resource_id", "version_number", name="uq_resource_version"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), index=True)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)
    content_status: Mapped[str] = mapped_column(String(30), nullable=False)
    content_origin: Mapped[str] = mapped_column(String(20), nullable=False, default="feed")
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    resource: Mapped[Resource] = relationship(
        back_populates="versions", foreign_keys=[resource_id],
    )


class SubscriptionResource(Base):
    """Many-to-many provenance: a resource may match multiple subscriptions."""
    __tablename__ = "subscription_resources"
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id"), primary_key=True
    )
    resource_id: Mapped[int] = mapped_column(ForeignKey("resources.id"), primary_key=True)


class ContentChunk(Base):
    """Citable offsets into a specific immutable ResourceVersion."""
    __tablename__ = "content_chunks"
    __table_args__ = (
        UniqueConstraint("resource_version_id", "ordinal", name="uq_chunk_position"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    resource_version_id: Mapped[int] = mapped_column(
        ForeignKey("resource_versions.id"), index=True,
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    char_start: Mapped[int] = mapped_column(Integer, nullable=False)
    char_end: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR, Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
    )
