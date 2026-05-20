"""Campaign template variable mapping column

Revision ID: 034_campaign_template_variable_mapping
Revises: 033_message_outbox_status_events_and_billing_ledger
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "034_campaign_template_variable_mapping"
down_revision = "033_message_outbox_status_events_and_billing_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "campaigns",
        sa.Column("variable_mapping_json", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")
