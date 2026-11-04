"""Durable Action execution history, separate from Feedbrain ingestion records."""
from datetime import datetime

from sqlalchemy import (
    CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from info_hub.action_models import utc_now
from info_hub.db import Base


class ActionRun(Base):
    __tablename__ = "action_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'interrupted')",
            name="ck_action_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action_id: Mapped[int] = mapped_column(ForeignKey("actions.id"), nullable=False, index=True)
    action_version_id: Mapped[int] = mapped_column(
        ForeignKey("action_versions.id"), nullable=False, index=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    initiated_by: Mapped[str] = mapped_column(String(30), nullable=False, default="api")
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    version = relationship("ActionVersion")
    steps: Mapped[list["ActionStepRun"]] = relationship(
        back_populates="run", order_by="ActionStepRun.id",
    )
    result: Mapped["ActionResult | None"] = relationship(
        back_populates="run", uselist=False,
    )


class ActionStepRun(Base):
    __tablename__ = "action_step_runs"
    __table_args__ = (
        UniqueConstraint("action_run_id", "step_id", name="uq_action_run_step_id"),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'interrupted')",
            name="ck_action_step_runs_status",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    action_run_id: Mapped[int] = mapped_column(
        ForeignKey("action_runs.id"), nullable=False, index=True,
    )
    step_id: Mapped[str] = mapped_column(String(64), nullable=False)
    capability: Mapped[str] = mapped_column(String(100), nullable=False)
    tool: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    external_run_ref: Mapped[str | None] = mapped_column(String(240))
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run: Mapped[ActionRun] = relationship(back_populates="steps")


class ActionResult(Base):
    __tablename__ = "action_results"

    id: Mapped[int] = mapped_column(primary_key=True)
    action_run_id: Mapped[int] = mapped_column(
        ForeignKey("action_runs.id"), nullable=False, unique=True,
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    run: Mapped[ActionRun] = relationship(back_populates="result")
