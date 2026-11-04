"""Durable ActionRun, StepRun and result history.

Revision ID: 20261104_0005
Revises: 20261104_0004
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "20261104_0005"
down_revision = "20261104_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id"), nullable=False),
        sa.Column(
            "action_version_id", sa.Integer(),
            sa.ForeignKey("action_versions.id"), nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("initiated_by", sa.String(30), nullable=False, server_default="api"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'completed', 'failed', 'interrupted')",
            name="ck_action_runs_status",
        ),
    )
    op.create_index("ix_action_runs_action_id", "action_runs", ["action_id"])
    op.create_index("ix_action_runs_action_version_id", "action_runs", ["action_version_id"])
    op.create_index(
        "ix_action_runs_queued", "action_runs", ["id"],
        postgresql_where=sa.text("status = 'queued'"),
    )
    op.create_table(
        "action_step_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "action_run_id", sa.Integer(),
            sa.ForeignKey("action_runs.id"), nullable=False,
        ),
        sa.Column("step_id", sa.String(64), nullable=False),
        sa.Column("capability", sa.String(100), nullable=False),
        sa.Column("tool", sa.String(80)),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("external_run_ref", sa.String(240)),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.Column("error_code", sa.String(80)),
        sa.Column("error_message", sa.Text()),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("action_run_id", "step_id", name="uq_action_run_step_id"),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'interrupted')",
            name="ck_action_step_runs_status",
        ),
    )
    op.create_index("ix_action_step_runs_action_run_id", "action_step_runs", ["action_run_id"])
    op.create_table(
        "action_results",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "action_run_id", sa.Integer(),
            sa.ForeignKey("action_runs.id"), nullable=False, unique=True,
        ),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("details", JSONB(), nullable=False, server_default="{}"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            nullable=False, server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("action_results")
    op.drop_table("action_step_runs")
    op.drop_table("action_runs")
