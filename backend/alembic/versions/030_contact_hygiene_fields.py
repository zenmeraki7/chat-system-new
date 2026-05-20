"""Add contact hygiene and CRM fields

Revision ID: 030_contact_hygiene_fields
Revises: 029_team_inbox_foundations
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "030_contact_hygiene_fields"
down_revision = "029_team_inbox_foundations"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS wa_id VARCHAR(255)")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email VARCHAR(255)")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS tags JSONB NOT NULL DEFAULT '[]'::jsonb")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS custom_attributes JSONB NOT NULL DEFAULT '{}'::jsonb")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS opt_in_status VARCHAR(30) NOT NULL DEFAULT 'unknown'")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS opt_in_source VARCHAR(80)")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS opt_in_timestamp TIMESTAMPTZ")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS unsubscribed_at TIMESTAMPTZ")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS blocked_at TIMESTAMPTZ")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ")
    op.execute("ALTER TABLE contacts ADD COLUMN IF NOT EXISTS last_message_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_wa_id ON contacts (wa_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_contacts_email ON contacts (email)")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")
