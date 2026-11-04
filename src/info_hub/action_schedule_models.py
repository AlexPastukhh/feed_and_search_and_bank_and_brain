"""Mutable, opt-in Action cadence; never embedded in immutable ActionVersion rows."""
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from info_hub.action_models import utc_now
from info_hub.db import Base


class ActionSchedule(Base):
    __tablename__ = "action_schedules"
    __table_args__ = (
        CheckConstraint(
            "every_minutes BETWEEN 1 AND 10080", name="ck_action_schedules_interval",
        ),
        CheckConstraint(
            "NOT enabled OR next_run_at IS NOT NULL", name="ck_action_schedules_enabled_due",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(
        ForeignKey("actions.id"), nullable=False, unique=True,
    )
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    every_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_enqueued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_skipped_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_skip_reason: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)

    action = relationship("Action")
