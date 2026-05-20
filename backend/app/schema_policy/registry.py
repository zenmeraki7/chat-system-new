from __future__ import annotations

GLOBAL_TABLES = {
    "users",
    "plans",
    "pricing_catalog_versions",
    "global_feature_flags",
    "system_jobs",
    "countries",
    "currencies",
    "roles",
    "permissions",
    "entitlements",
    "feature_flags",
    "widget_theme_presets",
    "kill_switches",
    "pii_classification_rules",
}

PUBLIC_API_TABLES = {
    "businesses",
    "campaigns",
}

TABLE_CLASSIFICATION = {
    "businesses": "global_entity",
    "messages": "tenant_mutable_entity",
    "audit_logs": "global_entity",
    "message_status_events": "global_entity",
    "usage_ledger": "tenant_immutable_event",
    "outbound_message_attempts": "global_entity",
    "message_send_attempts": "tenant_mutable_entity",
    "webhook_processing_attempts": "global_entity",
    "webhook_dead_letters": "global_entity",
    "campaign_recipient_snapshots": "global_entity",
    "campaign_recipient_snapshot_items": "global_entity",
    "campaign_send_attempts": "global_entity",
    "campaign_status_events": "global_entity",
    "user_login_attempts": "global_entity",
    "email_verification_tokens": "global_entity",
    "password_reset_tokens": "global_entity",
    "user_sessions": "global_entity",
    "external_identities": "global_entity",
    "whatsapp_asset_transfers": "global_entity",
    "team_members": "global_entity",
    "business_status_events": "tenant_mutable_entity",
    "conversation_status_events": "global_entity",
    "whatsapp_asset_connection_events": "tenant_mutable_entity",
    "outbox_events": "tenant_mutable_entity",
    "business_dashboard_stats": "tenant_read_model",
    "oauth_credentials": "tenant_secret_container",
}

IMMUTABLE_EVENT_TABLE_SUFFIXES = (
    "_ledger",
)

READ_MODEL_TABLE_SUFFIXES = (
    "_stats",
    "_summary",
    "_summary_stats",
    "_view",
    "_daily",
)

# Broad lint tokens for secret-like columns.
SECRET_COLUMN_TOKENS = (
    "token",
    "secret",
    "key",
    "password",
    "credential",
    "otp",
    "reset",
    "verify",
    "signature",
)

SECRET_SAFE_SUFFIXES = (
    "_hash",
    "_ciphertext",
    "_fingerprint",
    "_secret_ref",
)

SECRET_ALLOWLIST_COLUMNS = {
    "key_prefix",
    "public_id",
    "phone_number_id",
    "waba_id",
    "external_id",
    "provider_user_id",
    "request_id",
    "event_id",
    "idempotency_key",
    "identity_key",
    "feature_key",
    "scope_key",
    "key",
    "step_key",
    "credential_id",
    "dedupe_key",
    "owner_token",
    "metric_key",
    "dimension_key",
    "storage_key",
    "plan_key",
    "secret_version",
    "password_changed_at",
    "password_rehash_required",
    "widget_theme_preset_id",
    "verified_by_credential_id",
    "credential_purpose",
}


def classify_table(table_name: str) -> str:
    if table_name in TABLE_CLASSIFICATION:
        return TABLE_CLASSIFICATION[table_name]
    if table_name.startswith("brand_"):
        return "global_entity"
    if table_name.startswith("whatsapp_"):
        return "global_entity"
    if table_name.startswith("webchat_"):
        return "global_entity"
    if table_name.endswith("_channels"):
        return "global_entity"
    if table_name.endswith("_assignments") or table_name.endswith("_members"):
        return "global_entity"
    if table_name.endswith("_memberships"):
        return "global_entity"
    if table_name.endswith("_participants"):
        return "global_entity"
    if table_name.endswith("_events"):
        return "global_entity"
    if table_name.endswith("_messages"):
        return "global_entity"
    if table_name.endswith("_tags"):
        return "global_entity"
    if table_name.endswith("_notes"):
        return "global_entity"
    if table_name.startswith("provider_sync_"):
        return "global_entity"
    if table_name.endswith("_rows") or table_name.endswith("_items"):
        return "global_entity"
    if table_name.endswith("_errors"):
        return "global_entity"
    if table_name in GLOBAL_TABLES:
        return "global_entity"
    if table_name.endswith(READ_MODEL_TABLE_SUFFIXES):
        return "tenant_read_model"
    if table_name.endswith(IMMUTABLE_EVENT_TABLE_SUFFIXES):
        return "tenant_immutable_event"
    return "global_entity"


def requires_business_id(table_name: str) -> bool:
    return classify_table(table_name).startswith("tenant_")


def is_immutable_event(table_name: str) -> bool:
    return classify_table(table_name) == "tenant_immutable_event"


def is_read_model(table_name: str) -> bool:
    return classify_table(table_name) == "tenant_read_model"


def is_public_api_entity(table_name: str) -> bool:
    return table_name in PUBLIC_API_TABLES


def is_secret_like_column(column_name: str) -> bool:
    if column_name in SECRET_ALLOWLIST_COLUMNS:
        return False
    lowered = column_name.lower()
    return any(tok in lowered for tok in SECRET_COLUMN_TOKENS)


def is_protected_secret_column(column_name: str) -> bool:
    lowered = column_name.lower()
    return lowered.endswith(SECRET_SAFE_SUFFIXES)
