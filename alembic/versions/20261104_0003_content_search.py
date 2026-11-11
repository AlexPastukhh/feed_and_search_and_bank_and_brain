"""Citable text chunks and preferred content version.

Revision ID: 20261104_0003
Revises: 20261104_0002
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import TSVECTOR

from alembic import op

revision = "20261104_0003"
down_revision = "20261104_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "resource_versions",
        sa.Column("content_origin", sa.String(20), nullable=False, server_default="feed"),
    )
    op.add_column(
        "resources",
        sa.Column("current_version_id", sa.Integer(), nullable=True),
    )
    op.execute("""
        UPDATE resources r
        SET current_version_id = (
          SELECT v.id
          FROM resource_versions v
          WHERE v.resource_id = r.id
          ORDER BY v.version_number DESC
          LIMIT 1
        )
    """)
    op.create_foreign_key(
        "fk_resources_current_version_id",
        "resources", "resource_versions", ["current_version_id"], ["id"],
    )
    op.create_table(
        "content_chunks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_version_id", sa.Integer(),
                  sa.ForeignKey("resource_versions.id"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "search_vector", TSVECTOR(),
            sa.Computed("to_tsvector('simple'::regconfig, text)", persisted=True),
            nullable=False,
        ),
        sa.UniqueConstraint("resource_version_id", "ordinal", name="uq_chunk_position"),
    )
    op.create_index("ix_content_chunks_resource_version_id",
                    "content_chunks", ["resource_version_id"])
    op.create_index(
        "ix_content_chunks_search_vector", "content_chunks", ["search_vector"],
        postgresql_using="gin",
    )
    # Worker backfills existing versions in bounded batches.


def downgrade() -> None:
    op.drop_table("content_chunks")
    op.drop_constraint("fk_resources_current_version_id", "resources", type_="foreignkey")
    op.drop_column("resources", "current_version_id")
    op.drop_column("resource_versions", "content_origin")
