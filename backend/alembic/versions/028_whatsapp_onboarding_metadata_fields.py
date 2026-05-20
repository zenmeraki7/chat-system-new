"""Add WhatsApp onboarding metadata fields

Revision ID: 028_whatsapp_onboarding_metadata_fields
Revises: 027_messages_non_blank_content_check
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "028_whatsapp_onboarding_metadata_fields"
down_revision = "027_messages_non_blank_content_check"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("whatsapp_business_accounts", sa.Column("display_name", sa.String(length=255), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("currency", sa.String(length=16), nullable=True))
    op.add_column("whatsapp_business_accounts", sa.Column("timezone", sa.String(length=64), nullable=True))
    op.add_column("whatsapp_phone_numbers", sa.Column("verified_name", sa.String(length=255), nullable=True))
    op.add_column("whatsapp_phone_numbers", sa.Column("quality_rating", sa.String(length=30), nullable=True))
    op.add_column("whatsapp_phone_numbers", sa.Column("messaging_limit_tier", sa.String(length=60), nullable=True))
    op.add_column("whatsapp_phone_numbers", sa.Column("verification_status", sa.String(length=40), nullable=True))


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")

