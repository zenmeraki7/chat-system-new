"""phone registration attempt history

Revision ID: 044_phone_registration_attempt_history
Revises: 043_active_tenant_asset_uniqueness_and_resolver_safety
Create Date: 2026-05-21 02:10:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "044_phone_registration_attempt_history"
down_revision = "043_active_tenant_asset_uniqueness_and_resolver_safety"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "phone_registration_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number_id", sa.String(length=255), nullable=False),
        sa.Column("waba_id", sa.String(length=255), nullable=True),
        sa.Column("onboarding_operation_id", sa.String(length=120), nullable=True),
        sa.Column("outbox_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attempt_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("result_status", sa.String(length=30), nullable=False),
        sa.Column("http_status_code", sa.Integer(), nullable=True),
        sa.Column("provider_error_code", sa.String(length=80), nullable=True),
        sa.Column("provider_error_subcode", sa.String(length=80), nullable=True),
        sa.Column("response_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["outbox_event_id"], ["outbox_events.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_phone_registration_attempts_business_phone_created",
        "phone_registration_attempts",
        ["business_id", "phone_number_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_phone_registration_attempts_operation_id",
        "phone_registration_attempts",
        ["onboarding_operation_id"],
        unique=False,
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

