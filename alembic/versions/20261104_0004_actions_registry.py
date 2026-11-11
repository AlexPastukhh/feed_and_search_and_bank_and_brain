"""Append-only Action and ActionVersion registry.

Revision ID: 20261104_0004
Revises: 20261104_0003
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261104_0004"
down_revision = "20261104_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "current_version_number", sa.Integer(), nullable=False, server_default="1",
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint("current_version_number >= 1", name="ck_actions_current_version"),
    )
    op.create_table(
        "action_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("action_id", sa.Integer(), sa.ForeignKey("actions.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_yaml", sa.Text(), nullable=False),
        sa.Column("definition", JSONB(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint("action_id", "version_number", name="uq_action_version_number"),
        sa.CheckConstraint("version_number >= 1", name="ck_action_versions_version_number"),
    )
    # The API never modifies versions; the database enforces that contract for
    # all writers, including accidental SQL/ORM updates.
    op.execute("""
        CREATE FUNCTION reject_action_version_mutation()
        RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'ActionVersion records are append-only';
        END;
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER trg_action_versions_immutable
        BEFORE UPDATE OR DELETE ON action_versions
        FOR EACH ROW EXECUTE FUNCTION reject_action_version_mutation()
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER trg_action_versions_immutable ON action_versions")
    op.execute("DROP FUNCTION reject_action_version_mutation()")
    op.drop_table("action_versions")
    op.drop_table("actions")
