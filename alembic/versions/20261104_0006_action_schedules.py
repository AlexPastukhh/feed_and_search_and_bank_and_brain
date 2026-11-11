"""Opt-in Action schedule, independent of immutable ActionVersion.

Revision ID: 20261104_0006
Revises: 20261104_0005
"""
import sqlalchemy as sa

from alembic import op

revision = "20261104_0006"
down_revision = "20261104_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "action_schedules",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id"),
                  nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("every_minutes", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True)),
        sa.Column("last_enqueued_at", sa.DateTime(timezone=True)),
        sa.Column("last_skipped_at", sa.DateTime(timezone=True)),
        sa.Column("last_skip_reason", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "every_minutes BETWEEN 1 AND 10080", name="ck_action_schedules_interval",
        ),
        sa.CheckConstraint(
            "NOT enabled OR next_run_at IS NOT NULL",
            name="ck_action_schedules_enabled_due",
        ),
    )
    op.create_index(
        "ix_action_schedules_due", "action_schedules", ["next_run_at"],
        postgresql_where=sa.text("enabled = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_action_schedules_due", table_name="action_schedules")
    op.drop_table("action_schedules")
