# Cursor Pagination Index Migration Verification

This runbook step is required after deploying migration `048_cursor_pagination_indexes.py`.

## Deploy Pipeline Gate

1. Run schema migrations in target environment:

```bash
alembic upgrade head
```

2. Verify required keyset indexes are present and ready:

```bash
curl -fsS "$API_BASE_URL/readiness/cursor-indexes"
```

3. Fail the deploy if readiness endpoint returns non-2xx.

## Expected Ready Response

```json
{
  "status": "ready",
  "checkedIndexes": [
    "idx_campaign_recipients_campaign_status_id",
    "idx_contacts_business_updated_id",
    "idx_conversations_business_updated_id",
    "idx_messages_business_conversation_created_id"
  ],
  "indexStatuses": {
    "idx_contacts_business_updated_id": { "is_valid": true, "is_ready": true }
  }
}
```

## Failure Contract

Readiness returns `503` with:

- `missingIndexes`: required index names not found
- `invalidOrUnreadyIndexes`: indexes found but not ready/valid (`indisready=false` or `indisvalid=false`)

Treat either condition as deploy-blocking.
