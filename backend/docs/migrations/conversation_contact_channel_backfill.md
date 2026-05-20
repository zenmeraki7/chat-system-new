# Conversation contact/channel backfill safety

For migrating `conversations.contact_id` and `conversations.channel_id` from demo data:

1. Add `contact_id` nullable.
2. Add `channel_id` nullable.
3. Backfill contacts from existing visitor identity metadata.
4. Backfill `contact_identities` (include `identity_type`, `identity_value_hash`, verification status).
5. Backfill channels and map conversation traffic source.
6. Verify row counts and unresolved rows.
7. Set `contact_id` NOT NULL only after verification.
8. Set `channel_id` NOT NULL only after verification.

Do not apply strict NOT NULL constraints before backfill completion.
