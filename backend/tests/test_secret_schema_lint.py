from __future__ import annotations

import app.models.registry  # noqa: F401
from app.database import Base
from app.schema_policy.registry import is_secret_like_column, is_protected_secret_column


# Transitional allowlist for existing columns not yet migrated to *_hash/*_ciphertext/*_fingerprint/*_secret_ref.
TRANSITIONAL_SECRET_COLUMNS_ALLOWLIST = {
    "email_verification_tokens.attempt_count",
    "password_reset_tokens.attempt_count",
    "oauth_credentials.credential_owner_type",
    "oauth_credentials.credential_owner_id",
    "provider_request_logs.credential_id",
    "business_legal_acceptances.document_version",
}


def test_secret_like_columns_follow_storage_contract() -> None:
    violations: list[str] = []
    for table in Base.metadata.tables.values():
        for column in table.columns:
            if not is_secret_like_column(column.name):
                continue
            fq = f"{table.name}.{column.name}"
            if fq in TRANSITIONAL_SECRET_COLUMNS_ALLOWLIST:
                continue
            if not is_protected_secret_column(column.name):
                violations.append(fq)
    assert not violations, (
        "Secret-like columns must be hash/ciphertext/fingerprint/secret_ref. Violations: "
        + ", ".join(sorted(violations))
    )
