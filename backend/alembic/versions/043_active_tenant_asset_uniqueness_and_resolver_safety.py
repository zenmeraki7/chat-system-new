"""active tenant asset uniqueness and resolver safety

Revision ID: 043_active_tenant_asset_uniqueness_and_resolver_safety
Revises: 042_message_outbox_source_priority_schedule
Create Date: 2026-05-21 01:20:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "043_active_tenant_asset_uniqueness_and_resolver_safety"
down_revision = "042_message_outbox_source_priority_schedule"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replace earlier phone-number uniqueness index with a stricter active-live partial index.
    op.drop_index("uq_active_phone_number_global", table_name="whatsapp_phone_numbers", if_exists=True)
    op.create_index(
        "uq_active_phone_number_live_global",
        "whatsapp_phone_numbers",
        ["phone_number_id"],
        unique=True,
        postgresql_where=sa.text(
            "disconnected_at IS NULL AND deleted_at IS NULL AND environment = 'live'"
        ),
    )

    # Enforce that one active WABA can map to only one tenant at a time.
    op.create_index(
        "uq_active_waba_global",
        "whatsapp_business_accounts",
        ["waba_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    # Enforce one active webhook subscription per provider+asset mapping.
    op.create_index(
        "uq_active_webhook_subscription_asset_map",
        "webhook_subscriptions",
        ["provider", "waba_id", "phone_number_id", "environment"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")

