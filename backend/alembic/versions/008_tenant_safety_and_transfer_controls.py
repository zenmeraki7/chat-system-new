"""Tenant safety and transfer controls

Revision ID: 008_tenant_safety_and_transfer_controls
Revises: 007_business_identity_and_compliance_ops
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "008_tenant_safety_and_transfer_controls"
down_revision = "007_business_identity_and_compliance_ops"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_phone_numbers", sa.Column("disconnected_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index(
        "uq_active_phone_number_global",
        "whatsapp_phone_numbers",
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text("disconnected_at IS NULL"),
    )

    op.create_table(
        "whatsapp_asset_transfers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_type", sa.String(length=40), nullable=False),
        sa.Column("asset_id", sa.String(length=255), nullable=False),
        sa.Column("from_business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("to_business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["from_business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requested_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["approved_by_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_whatsapp_asset_transfers_asset_id", "whatsapp_asset_transfers", ["asset_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")
