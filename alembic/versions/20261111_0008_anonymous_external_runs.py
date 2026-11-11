"""Remove executor identity from post-hoc external ActionRun registrations.

Revision ID: 20261111_0008
Revises: 20261110_0007

An accepted migration history is append-only. 0007 is left intact; 0008
drops the column and redefines the terminal-state constraint.
"""
import sqlalchemy as sa

from alembic import op

revision = "20261111_0008"
down_revision = "20261110_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Do not silently erase attribution if 0007 has already stored named runs.
    # Current Windows runtime has not deployed 0007; other databases may differ.
    conn = op.get_bind()
    if conn.execute(sa.text(
        "SELECT 1 FROM action_runs WHERE executor_id IS NOT NULL LIMIT 1"
    )).first() is not None:
        raise RuntimeError(
            "Executor IDs exist in ActionRun; manual data-retention review "
            "required before removing attribution"
        )
    op.drop_constraint("ck_action_runs_external_terminal", "action_runs", type_="check")
    op.drop_column("action_runs", "executor_id")
    op.create_check_constraint(
        "ck_action_runs_external_terminal", "action_runs",
        "(execution_kind = 'programmatic' AND external_run_key IS NULL "
        "AND registration_fingerprint IS NULL) OR "
        "(execution_kind = 'external_ai' AND "
        "status IN ('completed', 'failed', 'interrupted') "
        "AND external_run_key IS NOT NULL "
        "AND registration_fingerprint IS NOT NULL)",
    )


def downgrade() -> None:
    # New anonymous external records cannot satisfy 0007's identity constraint.
    # Refuse to synthesize a fake executor ID just to make the downgrade pass.
    conn = op.get_bind()
    if conn.execute(sa.text(
        "SELECT 1 FROM action_runs WHERE execution_kind = 'external_ai' LIMIT 1"
    )).first() is not None:
        raise RuntimeError(
            "Cannot downgrade anonymous external runs to revision 0007 "
            "without inventing executor identities"
        )
    op.drop_constraint("ck_action_runs_external_terminal", "action_runs", type_="check")
    op.add_column("action_runs", sa.Column("executor_id", sa.String(100)))
    op.create_check_constraint(
        "ck_action_runs_external_terminal", "action_runs",
        "(execution_kind = 'programmatic' AND external_run_key IS NULL "
        "AND registration_fingerprint IS NULL) OR "
        "(execution_kind = 'external_ai' AND "
        "status IN ('completed', 'failed', 'interrupted') "
        "AND external_run_key IS NOT NULL "
        "AND registration_fingerprint IS NOT NULL AND executor_id IS NOT NULL)",
    )
