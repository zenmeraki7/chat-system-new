"""campaign preview signature fields

Revision ID: 037_campaign_preview_signature_fields
Revises: 036_contact_message_frequency
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = "037_campaign_preview_signature_fields"
down_revision = "036_contact_message_frequency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("preview_signature_hash", sa.String(length=128), nullable=True))
    op.add_column("campaigns", sa.Column("preview_generated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("campaigns", sa.Column("preview_invalidated_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_campaigns_preview_signature_hash", "campaigns", ["preview_signature_hash"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_campaigns_preview_signature_hash", table_name="campaigns")
    op.drop_column("campaigns", "preview_invalidated_at")
    op.drop_column("campaigns", "preview_generated_at")
    op.drop_column("campaigns", "preview_signature_hash")

