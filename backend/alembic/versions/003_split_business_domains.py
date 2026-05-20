"""Split overloaded business domains

Revision ID: 003_split_business_domains
Revises: 002_add_whatsapp_fields
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "003_split_business_domains"
down_revision = "002_add_whatsapp_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "business_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
        sa.UniqueConstraint("email"),
    )
    op.create_index("ix_business_users_id", "business_users", ["id"])
    op.create_index("ix_business_users_business_id", "business_users", ["business_id"])
    op.create_index("ix_business_users_email", "business_users", ["email"])

    op.create_table(
        "business_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("api_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
        sa.UniqueConstraint("api_key"),
    )
    op.create_index("ix_business_api_keys_id", "business_api_keys", ["id"])
    op.create_index("ix_business_api_keys_business_id", "business_api_keys", ["business_id"])
    op.create_index("ix_business_api_keys_api_key", "business_api_keys", ["api_key"])

    op.create_table(
        "business_widget_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("widget_color", sa.String(length=20), nullable=False, server_default="#6366f1"),
        sa.Column("widget_title", sa.String(length=100), nullable=False, server_default="Chat with us"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )
    op.create_index("ix_business_widget_settings_id", "business_widget_settings", ["id"])
    op.create_index("ix_business_widget_settings_business_id", "business_widget_settings", ["business_id"])

    op.create_table(
        "business_ai_settings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system_prompt", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("business_id"),
    )
    op.create_index("ix_business_ai_settings_id", "business_ai_settings", ["id"])
    op.create_index("ix_business_ai_settings_business_id", "business_ai_settings", ["business_id"])

    op.create_table(
        "meta_business_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meta_business_account_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("meta_business_account_id"),
    )
    op.create_index("ix_meta_business_accounts_id", "meta_business_accounts", ["id"])
    op.create_index("ix_meta_business_accounts_business_id", "meta_business_accounts", ["business_id"])
    op.create_index("ix_meta_business_accounts_meta_business_account_id", "meta_business_accounts", ["meta_business_account_id"])

    op.create_table(
        "whatsapp_business_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("meta_business_account_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("waba_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["meta_business_account_id"], ["meta_business_accounts.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("waba_id"),
    )
    op.create_index("ix_whatsapp_business_accounts_id", "whatsapp_business_accounts", ["id"])
    op.create_index("ix_whatsapp_business_accounts_business_id", "whatsapp_business_accounts", ["business_id"])
    op.create_index("ix_whatsapp_business_accounts_meta_business_account_id", "whatsapp_business_accounts", ["meta_business_account_id"])
    op.create_index("ix_whatsapp_business_accounts_waba_id", "whatsapp_business_accounts", ["waba_id"])

    op.create_table(
        "whatsapp_phone_numbers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("whatsapp_business_account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phone_number_id", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["whatsapp_business_account_id"], ["whatsapp_business_accounts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_number_id"),
    )
    op.create_index("ix_whatsapp_phone_numbers_id", "whatsapp_phone_numbers", ["id"])
    op.create_index("ix_whatsapp_phone_numbers_whatsapp_business_account_id", "whatsapp_phone_numbers", ["whatsapp_business_account_id"])
    op.create_index("ix_whatsapp_phone_numbers_phone_number_id", "whatsapp_phone_numbers", ["phone_number_id"])

    op.create_table(
        "oauth_credentials",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("access_token", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_oauth_credentials_id", "oauth_credentials", ["id"])
    op.create_index("ix_oauth_credentials_business_id", "oauth_credentials", ["business_id"])
    op.create_index("ix_oauth_credentials_provider", "oauth_credentials", ["provider"])

    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("verify_token", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("verify_token"),
    )
    op.create_index("ix_webhook_subscriptions_id", "webhook_subscriptions", ["id"])
    op.create_index("ix_webhook_subscriptions_business_id", "webhook_subscriptions", ["business_id"])
    op.create_index("ix_webhook_subscriptions_provider", "webhook_subscriptions", ["provider"])
    op.create_index("ix_webhook_subscriptions_verify_token", "webhook_subscriptions", ["verify_token"])

    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
    op.execute(
        """
        INSERT INTO business_users (id, business_id, email, password_hash, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), id, email, password_hash, true, NOW(), NOW() FROM businesses
        """
    )
    op.execute(
        """
        INSERT INTO business_api_keys (id, business_id, api_key, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), id, api_key, true, NOW(), NOW() FROM businesses
        """
    )
    op.execute(
        """
        INSERT INTO business_widget_settings (id, business_id, widget_color, widget_title, created_at, updated_at)
        SELECT gen_random_uuid(), id, widget_color, widget_title, NOW(), NOW() FROM businesses
        """
    )
    op.execute(
        """
        INSERT INTO business_ai_settings (id, business_id, system_prompt, created_at, updated_at)
        SELECT gen_random_uuid(), id, system_prompt, NOW(), NOW() FROM businesses
        """
    )
    op.execute(
        """
        INSERT INTO meta_business_accounts (id, business_id, meta_business_account_id, created_at, updated_at)
        SELECT gen_random_uuid(), id, whatsapp_business_account_id, NOW(), NOW()
        FROM businesses
        WHERE whatsapp_business_account_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO whatsapp_business_accounts (id, business_id, meta_business_account_id, waba_id, created_at, updated_at)
        SELECT gen_random_uuid(), b.id, mba.id, b.whatsapp_business_account_id, NOW(), NOW()
        FROM businesses b
        JOIN meta_business_accounts mba
          ON mba.business_id = b.id
         AND mba.meta_business_account_id = b.whatsapp_business_account_id
        WHERE b.whatsapp_business_account_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO whatsapp_phone_numbers (id, whatsapp_business_account_id, phone_number_id, created_at, updated_at)
        SELECT gen_random_uuid(), wba.id, b.whatsapp_phone_number_id, NOW(), NOW()
        FROM businesses b
        JOIN whatsapp_business_accounts wba
          ON wba.business_id = b.id
         AND wba.waba_id = b.whatsapp_business_account_id
        WHERE b.whatsapp_phone_number_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO oauth_credentials (id, business_id, provider, access_token, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'whatsapp', whatsapp_access_token, NOW(), NOW()
        FROM businesses
        WHERE whatsapp_access_token IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO webhook_subscriptions (id, business_id, provider, verify_token, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), id, 'whatsapp', whatsapp_verify_token, true, NOW(), NOW()
        FROM businesses
        WHERE whatsapp_verify_token IS NOT NULL
        """
    )

    op.drop_index("ix_businesses_email", table_name="businesses")
    op.drop_index("ix_businesses_api_key", table_name="businesses")
    op.drop_constraint("businesses_email_key", "businesses", type_="unique")
    op.drop_constraint("businesses_api_key_key", "businesses", type_="unique")
    op.drop_column("businesses", "email")
    op.drop_column("businesses", "password_hash")
    op.drop_column("businesses", "api_key")
    op.drop_column("businesses", "system_prompt")
    op.drop_column("businesses", "widget_color")
    op.drop_column("businesses", "widget_title")
    op.drop_column("businesses", "whatsapp_access_token")
    op.drop_column("businesses", "whatsapp_business_account_id")
    op.drop_column("businesses", "whatsapp_phone_number_id")
    op.drop_column("businesses", "whatsapp_verify_token")


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")
