"""campaign preview/config hash alignment

Revision ID: 038_campaign_preview_and_config_hash
Revises: 037_campaign_preview_signature_fields
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa


revision = "038_campaign_preview_and_config_hash"
down_revision = "037_campaign_preview_signature_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("campaigns", sa.Column("preview_hash", sa.String(length=128), nullable=True))
    op.add_column("campaigns", sa.Column("campaign_config_hash", sa.String(length=128), nullable=True))
    op.create_index("ix_campaigns_preview_hash", "campaigns", ["preview_hash"], unique=False)
    op.create_index("ix_campaigns_campaign_config_hash", "campaigns", ["campaign_config_hash"], unique=False)
    # Keep legacy column for compatibility if present.
    # If DB already has preview_signature_hash, leave as-is; app no longer uses it.


def downgrade() -> None:
    op.drop_index("ix_campaigns_campaign_config_hash", table_name="campaigns")
    op.drop_index("ix_campaigns_preview_hash", table_name="campaigns")
    op.drop_column("campaigns", "campaign_config_hash")
    op.drop_column("campaigns", "preview_hash")

