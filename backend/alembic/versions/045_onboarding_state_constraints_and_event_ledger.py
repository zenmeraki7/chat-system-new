"""onboarding state constraints and immutable event ledger

Revision ID: 045_onboarding_state_constraints_and_event_ledger
Revises: 044_phone_registration_attempt_history
Create Date: 2026-05-21 03:05:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "045_onboarding_state_constraints_and_event_ledger"
down_revision = "044_phone_registration_attempt_history"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE onboarding_operations
        SET status = CASE
          WHEN lower(coalesce(status,'')) IN ('pending','completed','failed') THEN lower(status)
          ELSE 'failed'
        END
        """
    )
    op.execute(
        """
        UPDATE onboarding_operations
        SET current_step = CASE
          WHEN current_step IS NULL THEN NULL
          WHEN lower(current_step) IN (
            'embedded_signup_session_created',
            'oauth_code_received',
            'phone_registration_queued',
            'phone_registration_pending',
            'phone_registration_verified',
            'phone_registration_failed',
            'failed'
          ) THEN lower(current_step)
          WHEN lower(current_step) = 'whatsapp_connected' THEN 'phone_registration_verified'
          ELSE 'failed'
        END
        """
    )
    op.execute(
        """
        UPDATE whatsapp_integrations
        SET status = CASE
          WHEN lower(coalesce(status,'')) IN ('disconnected','provisioning','connected','reconnect_required','disconnecting') THEN lower(status)
          ELSE 'reconnect_required'
        END
        """
    )
    op.create_check_constraint(
        "ck_onboarding_operations_status_enum",
        "onboarding_operations",
        "status IN ('pending','completed','failed')",
    )
    op.create_check_constraint(
        "ck_onboarding_operations_current_step_enum",
        "onboarding_operations",
        "current_step IS NULL OR current_step IN ("
        "'embedded_signup_session_created',"
        "'oauth_code_received',"
        "'phone_registration_queued',"
        "'phone_registration_pending',"
        "'phone_registration_verified',"
        "'phone_registration_failed',"
        "'failed'"
        ")",
    )
    op.create_check_constraint(
        "ck_whatsapp_integrations_status_enum",
        "whatsapp_integrations",
        "status IN ('disconnected','provisioning','connected','reconnect_required','disconnecting')",
    )

    op.create_table(
        "onboarding_event_ledger",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", sa.String(length=120), nullable=True),
        sa.Column("event_type", sa.String(length=120), nullable=False),
        sa.Column("event_status", sa.String(length=30), nullable=False, server_default="info"),
        sa.Column("merchant_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("waba_id", sa.String(length=255), nullable=True),
        sa.Column("phone_number_id", sa.String(length=255), nullable=True),
        sa.Column("meta_app_id", sa.String(length=255), nullable=True),
        sa.Column("graph_api_endpoint", sa.String(length=255), nullable=True),
        sa.Column("graph_request_id", sa.String(length=120), nullable=True),
        sa.Column("graph_error_code", sa.String(length=80), nullable=True),
        sa.Column("graph_error_subcode", sa.String(length=80), nullable=True),
        sa.Column("fbtrace_id", sa.String(length=120), nullable=True),
        sa.Column("trace_id", sa.String(length=120), nullable=True),
        sa.Column("graph_response_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["business_id"], ["businesses.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["merchant_user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_onboarding_event_ledger_business_created", "onboarding_event_ledger", ["business_id", "created_at"], unique=False)
    op.create_index("ix_onboarding_event_ledger_operation_id", "onboarding_event_ledger", ["operation_id"], unique=False)
    op.create_index("ix_onboarding_event_ledger_trace_id", "onboarding_event_ledger", ["trace_id"], unique=False)

    op.execute(
        """
        CREATE OR REPLACE FUNCTION block_onboarding_event_ledger_mutation()
        RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'onboarding_event_ledger is immutable';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_block_onboarding_event_ledger_update
        BEFORE UPDATE ON onboarding_event_ledger
        FOR EACH ROW
        EXECUTE FUNCTION block_onboarding_event_ledger_mutation();
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_block_onboarding_event_ledger_delete
        BEFORE DELETE ON onboarding_event_ledger
        FOR EACH ROW
        EXECUTE FUNCTION block_onboarding_event_ledger_mutation();
        """
    )


def downgrade() -> None:
    raise NotImplementedError("Downgrade is intentionally not supported for this migration.")
