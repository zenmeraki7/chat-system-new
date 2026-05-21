"""contact export jobs and query snapshots

Revision ID: 046_contact_export_jobs_and_query_snapshots
Revises: 045_onboarding_state_constraints_and_event_ledger
Create Date: 2026-05-21 06:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "046_contact_export_jobs_and_query_snapshots"
down_revision = "045_onboarding_state_constraints_and_event_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "query_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("resource", sa.String(length=80), nullable=False),
        sa.Column("query_hash", sa.String(length=128), nullable=False),
        sa.Column("query_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="active"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id", "resource", "query_hash", name="uq_query_snapshots_business_resource_hash"),
    )
    op.create_index("ix_query_snapshots_business_id", "query_snapshots", ["business_id"], unique=False)
    op.create_index("ix_query_snapshots_resource", "query_snapshots", ["resource"], unique=False)
    op.create_index("ix_query_snapshots_query_hash", "query_snapshots", ["query_hash"], unique=False)
    op.create_index("ix_query_snapshots_status", "query_snapshots", ["status"], unique=False)
    op.create_index("ix_query_snapshots_expires_at", "query_snapshots", ["expires_at"], unique=False)
    op.create_index(
        "ix_query_snapshots_business_resource_status",
        "query_snapshots",
        ["business_id", "resource", "status", "created_at", "id"],
        unique=False,
    )

    op.create_table(
        "contact_export_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("query_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("selection_mode", sa.String(length=40), nullable=False, server_default="explicit"),
        sa.Column("selected_contact_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("excluded_contact_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("columns_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(length=255), nullable=True),
        sa.Column("download_url", sa.String(length=1024), nullable=True),
        sa.Column("error_code", sa.String(length=120), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["query_snapshot_id"], ["query_snapshots.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contact_export_jobs_business_id", "contact_export_jobs", ["business_id"], unique=False)
    op.create_index("ix_contact_export_jobs_requested_by_user_id", "contact_export_jobs", ["requested_by_user_id"], unique=False)
    op.create_index("ix_contact_export_jobs_query_snapshot_id", "contact_export_jobs", ["query_snapshot_id"], unique=False)
    op.create_index("ix_contact_export_jobs_status", "contact_export_jobs", ["status"], unique=False)
    op.create_index(
        "ix_contact_export_jobs_business_status_created",
        "contact_export_jobs",
        ["business_id", "status", "created_at", "id"],
        unique=False,
    )

    # Contact and conversation pagination/filter indexes for high-volume table scans.
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_contacts_business_updated_id
        ON contacts (business_id, updated_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_contacts_business_phone
        ON contacts (business_id, normalized_phone)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_contacts_business_optin_updated_id
        ON contacts (business_id, opt_in_status, updated_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_conversations_business_last_message_id
        ON conversations (business_id, last_message_at DESC, id DESC)
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_campaign_recipients_campaign_status_updated_id
        ON campaign_recipients (campaign_id, status, updated_at DESC, id DESC)
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

