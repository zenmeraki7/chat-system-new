"""Message webhook dedupe/idempotency partitions and send-attempt provider correlation

Revision ID: 022_message_reliability_and_correlation
Revises: 021_message_sequence_and_visibility
Create Date: 2026-05-19
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "022_message_reliability_and_correlation"
down_revision = "021_message_sequence_and_visibility"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("send_operation_id", sa.String(length=120), nullable=True))
    op.add_column("messages", sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("lock_owner", sa.String(length=120), nullable=True))
    op.add_column("messages", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("messages", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column("messages", sa.Column("failure_category", sa.String(length=40), nullable=True))
    op.add_column("messages", sa.Column("retry_after", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_messages_send_operation_id", "messages", ["send_operation_id"])

    op.execute(
        "ALTER TABLE messages ADD CONSTRAINT chk_message_failure_category "
        "CHECK (failure_category IS NULL OR failure_category IN "
        "('provider_rate_limit','invalid_recipient','template_not_approved','token_revoked','phone_number_disabled','billing_blocked','policy_violation','network_timeout','unknown'))"
    )

    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_inbound_provider_message
        ON messages (business_id, provider, provider_message_id)
        WHERE direction = 'inbound' AND provider_message_id IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_outbound_message_idempotency
        ON messages (business_id, idempotency_key)
        WHERE direction = 'outbound' AND idempotency_key IS NOT NULL
        """
    )

    op.add_column("message_send_attempts", sa.Column("credential_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.add_column("message_send_attempts", sa.Column("provider_request_id", sa.String(length=120), nullable=True))
    op.add_column("message_send_attempts", sa.Column("provider_error_subcode", sa.String(length=120), nullable=True))
    op.add_column("message_send_attempts", sa.Column("response_body_redacted", sa.Text(), nullable=True))
    op.add_column("message_send_attempts", sa.Column("request_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("message_send_attempts", sa.Column("request_finished_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key(
        "fk_message_send_attempts_credential_id",
        "message_send_attempts",
        "oauth_credentials",
        ["credential_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_message_send_attempts_credential_id", "message_send_attempts", ["credential_id"])
    op.create_index("ix_message_send_attempts_provider_request_id", "message_send_attempts", ["provider_request_id"])


def downgrade() -> None:
    raise NotImplementedError("Downgrade is not supported for this migration")
