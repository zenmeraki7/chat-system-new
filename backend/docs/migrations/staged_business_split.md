# Staged Migration Strategy: Legacy Business Columns

This project must not do a big-bang cutover for legacy `businesses` columns.

## Sequence

1. Create normalized destination tables (`users`, `business_memberships`, `business_api_keys`, `oauth_credentials`, `whatsapp_business_accounts`, `whatsapp_phone_numbers`, `webhook_subscriptions`).
2. Backfill users from legacy `businesses.email`/`password_hash` using `lower(trim(email))`.
3. Backfill owner memberships and owner role mapping.
4. Backfill API keys into hashed `business_api_keys`.
5. Backfill WhatsApp credentials into encrypted `oauth_credentials`.
6. Backfill WABA and phone-number assets.
7. Switch services to read normalized tables first.
8. Run dual-read/dual-validate during transition.
9. Stop writing old columns.
10. Drop old columns only after verification and rollback window.

## Safety Checks

- Enforce active-email uniqueness with partial index:
  - `CREATE UNIQUE INDEX uq_users_email_lower_active ON users (lower(email)) WHERE deleted_at IS NULL;`
- Verify no unresolved legacy rows remain before column drops.
- Keep per-step audit logs and backfill metrics.
