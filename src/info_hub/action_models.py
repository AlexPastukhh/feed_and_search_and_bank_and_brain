"""Action Registry storage, intentionally independent from Feedbrain domain tables."""
from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from info_hub.db import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Action(Base):
    __tablename__ = "actions"
    __table_args__ = (
        CheckConstraint("current_version_number >= 1", name="ck_actions_current_version"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    current_version_number: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    versions: Mapped[list["ActionVersion"]] = relationship(back_populates="action")


class ActionVersion(Base):
    """Append-only snapshots. PostgreSQL trigger prevents UPDATE/DELETE."""
    __tablename__ = "action_versions"
    __table_args__ = (
        UniqueConstraint("action_id", "version_number", name="uq_action_version_number"),
        CheckConstraint("version_number >= 1", name="ck_action_versions_version_number"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id"), nullable=False)
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_yaml: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    action: Mapped[Action] = relationship(back_populates="versions")
