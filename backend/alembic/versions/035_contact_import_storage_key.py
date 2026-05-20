"""Add storage key to contact import jobs

Revision ID: 035_contact_import_storage_key
Revises: 034_campaign_template_variable_mapping
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa


revision = "035_contact_import_storage_key"
down_revision = "034_campaign_template_variable_mapping"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("contact_import_jobs", sa.Column("storage_key", sa.String(length=512), nullable=True))
    op.create_index("ix_contact_import_jobs_storage_key", "contact_import_jobs", ["storage_key"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")
