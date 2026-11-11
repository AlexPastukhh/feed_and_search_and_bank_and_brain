"""RSS core: sources, subscriptions, ingestion runs and resource versions.

Revision ID: 20261104_0002
Revises: 20261104_0001
"""
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "20261104_0002"
down_revision = "20261104_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("connector_key", sa.String(60), nullable=False),
        sa.Column("config", JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("operation", sa.String(40), nullable=False),
        sa.Column("parameters", JSONB(), nullable=False),
        sa.Column("interval_minutes", sa.Integer(), nullable=False),
        sa.Column("read_enabled", sa.Boolean(), nullable=False),
        sa.Column("research_enabled", sa.Boolean(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_success_at", sa.DateTime(timezone=True)),
        sa.Column("last_error", sa.Text()),
        sa.Column("etag", sa.String(500)),
        sa.Column("last_modified", sa.String(500)),
    )
    op.create_index("ix_subscriptions_source_id", "subscriptions", ["source_id"])
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id")),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("items_seen", sa.Integer(), nullable=False),
        sa.Column("items_created", sa.Integer(), nullable=False),
        sa.Column("items_updated", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text()),
    )
    op.create_index("ix_ingestion_runs_source_id", "ingestion_runs", ["source_id"])
    op.create_index("ix_ingestion_runs_subscription_id", "ingestion_runs", ["subscription_id"])
    op.create_table(
        "resources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id"), nullable=False),
        sa.Column("external_id", sa.String(700), nullable=False),
        sa.Column("resource_type", sa.String(40), nullable=False),
        sa.Column("title", sa.String(1000), nullable=False),
        sa.Column("canonical_url", sa.Text()),
        sa.Column("author", sa.String(500)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("source_id", "external_id", name="uq_source_external_id"),
    )
    op.create_index("ix_resources_source_id", "resources", ["source_id"])
    op.create_table(
        "resource_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("resources.id"), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content_text", sa.Text()),
        sa.Column("content_status", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("raw_payload", JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("resource_id", "version_number", name="uq_resource_version"),
    )
    op.create_index("ix_resource_versions_resource_id", "resource_versions", ["resource_id"])
    op.create_table(
        "subscription_resources",
        sa.Column("subscription_id", sa.Integer(), sa.ForeignKey("subscriptions.id"), primary_key=True),
        sa.Column("resource_id", sa.Integer(), sa.ForeignKey("resources.id"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("subscription_resources")
    op.drop_table("resource_versions")
    op.drop_table("resources")
    op.drop_table("ingestion_runs")
    op.drop_table("subscriptions")
    op.drop_table("sources")
