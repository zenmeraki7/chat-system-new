"""Message provenance grouping/import fields and customer webhook linkage

Revision ID: 026_message_provenance_grouping_and_webhook_linkage
Revises: 025_message_tenant_fk_and_provider_accepted_at
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "026_message_provenance_grouping_and_webhook_linkage"
down_revision = "025_message_tenant_fk_and_provider_accepted_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("actor_type", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("actor_id", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("operation_id", sa.String(length=120), nullable=True))

    op.add_column("messages", sa.Column("rendered_content_text", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("render_source_type", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("render_source_id", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("render_snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.add_column("messages", sa.Column("message_group_id", sa.String(length=120), nullable=True))
    op.add_column("messages", sa.Column("group_sequence", sa.Integer(), nullable=True))

    op.add_column("messages", sa.Column("raw_payload_ref", sa.String(length=255), nullable=True))
    op.add_column("messages", sa.Column("ingestion_source", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("import_batch_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("messages", sa.Column("backfilled_at", sa.DateTime(timezone=True), nullable=True))

    op.create_foreign_key(
        "fk_messages_import_batch_id",
        "messages",
        "contact_import_jobs",
        ["import_batch_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.create_index("ix_messages_actor_type", "messages", ["actor_type"])
    op.create_index("ix_messages_actor_id", "messages", ["actor_id"])
    op.create_index("ix_messages_operation_id", "messages", ["operation_id"])
    op.create_index("ix_messages_render_source_type", "messages", ["render_source_type"])
    op.create_index("ix_messages_render_source_id", "messages", ["render_source_id"])
    op.create_index("ix_messages_message_group_id", "messages", ["message_group_id"])
    op.create_index("ix_messages_raw_payload_ref", "messages", ["raw_payload_ref"])
    op.create_index("ix_messages_ingestion_source", "messages", ["ingestion_source"])
    op.create_index("ix_messages_import_batch_id", "messages", ["import_batch_id"])

    op.create_unique_constraint(
        "uq_messages_group_sequence",
        "messages",
        ["business_id", "message_group_id", "group_sequence"],
    )

    op.add_column("customer_webhook_deliveries", sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("customer_webhook_deliveries", sa.Column("source_type", sa.String(length=40), nullable=True))
    op.add_column("customer_webhook_deliveries", sa.Column("source_id", sa.String(length=255), nullable=True))
    op.add_column("customer_webhook_deliveries", sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"))

    op.execute(
        """
        UPDATE customer_webhook_deliveries d
        SET business_id = e.business_id
        FROM customer_webhook_endpoints e
        WHERE d.endpoint_id = e.id
        """
    )

    op.alter_column("customer_webhook_deliveries", "business_id", nullable=False)
    op.create_foreign_key(
        "fk_customer_webhook_deliveries_business_id",
        "customer_webhook_deliveries",
        "businesses",
        ["business_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_customer_webhook_deliveries_business_id", "customer_webhook_deliveries", ["business_id"])
    op.create_index("ix_customer_webhook_deliveries_source_type", "customer_webhook_deliveries", ["source_type"])
    op.create_index("ix_customer_webhook_deliveries_source_id", "customer_webhook_deliveries", ["source_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")
