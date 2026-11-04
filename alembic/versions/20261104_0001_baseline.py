"""Create the initial migration baseline.

Revision ID: 20261104_0001
Revises:
Create Date: 2026-11-04

This is intentionally an empty schema baseline. Domain tables arrive in Phase 1.
"""

revision = "20261104_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create only Alembic's version marker (managed by Alembic)."""


def downgrade() -> None:
    """Roll back the empty baseline."""
