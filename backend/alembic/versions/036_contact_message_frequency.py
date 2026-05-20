"""contact message frequency caps

Revision ID: 036_contact_message_frequency
Revises: 035_contact_import_storage_key
Create Date: 2026-05-20
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision = "036_contact_message_frequency"
down_revision = "035_contact_import_storage_key"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contact_message_frequency",
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("contact_id", sa.String(length=255), nullable=False),
        sa.Column("phone_e164", sa.String(length=20), nullable=False),
        sa.Column("marketing_messages_24h", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("marketing_messages_7d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("marketing_messages_30d", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_marketing_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), server_default="1", nullable=False),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_contact_message_frequency_business_id", "contact_message_frequency", ["business_id"], unique=False)
    op.create_index("ix_contact_message_frequency_contact_id", "contact_message_frequency", ["contact_id"], unique=False)
    op.create_index("ix_contact_message_frequency_phone_e164", "contact_message_frequency", ["phone_e164"], unique=False)
    op.create_index(
        "ix_contact_message_frequency_last_marketing_message_at",
        "contact_message_frequency",
        ["last_marketing_message_at"],
        unique=False,
    )
    op.create_index("ix_contact_message_frequency_deleted_at", "contact_message_frequency", ["deleted_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_contact_message_frequency_deleted_at", table_name="contact_message_frequency")
    op.drop_index("ix_contact_message_frequency_last_marketing_message_at", table_name="contact_message_frequency")
    op.drop_index("ix_contact_message_frequency_phone_e164", table_name="contact_message_frequency")
    op.drop_index("ix_contact_message_frequency_contact_id", table_name="contact_message_frequency")
    op.drop_index("ix_contact_message_frequency_business_id", table_name="contact_message_frequency")
    op.drop_table("contact_message_frequency")

