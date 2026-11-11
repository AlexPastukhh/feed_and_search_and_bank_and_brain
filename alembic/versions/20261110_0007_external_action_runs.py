"""Add external AI execution provenance to existing ActionRun history.

Revision ID: 20261110_0007
Revises: 20261104_0006
"""
import sqlalchemy as sa

from alembic import op

revision = "20261110_0007"
down_revision = "20261104_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("action_runs", sa.Column(
        "execution_kind", sa.String(24), nullable=False,
        server_default="programmatic",
    ))
    op.add_column("action_runs", sa.Column("executor_id", sa.String(100)))
    op.add_column("action_runs", sa.Column("external_run_key", sa.String(160)))
    op.add_column("action_runs", sa.Column("registration_fingerprint", sa.String(64)))
    op.create_unique_constraint(
        "uq_action_runs_external_key", "action_runs",
        ["action_id", "external_run_key"],
    )
    op.create_check_constraint(
        "ck_action_runs_execution_kind", "action_runs",
        "execution_kind IN ('programmatic', 'external_ai')",
    )
    op.create_check_constraint(
        "ck_action_runs_external_terminal", "action_runs",
        "(execution_kind = 'programmatic' AND external_run_key IS NULL "
        "AND registration_fingerprint IS NULL) OR "
        "(execution_kind = 'external_ai' AND "
        "status IN ('completed', 'failed', 'interrupted') "
        "AND external_run_key IS NOT NULL AND "
        "registration_fingerprint IS NOT NULL AND executor_id IS NOT NULL)",
    )


def downgrade() -> None:
    op.drop_constraint("ck_action_runs_external_terminal", "action_runs", type_="check")
    op.drop_constraint("ck_action_runs_execution_kind", "action_runs", type_="check")
    op.drop_constraint("uq_action_runs_external_key", "action_runs", type_="unique")
    op.drop_column("action_runs", "registration_fingerprint")
    op.drop_column("action_runs", "external_run_key")
    op.drop_column("action_runs", "executor_id")
    op.drop_column("action_runs", "execution_kind")
