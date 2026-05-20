# Foreign-Key Delete Policy Standard

## Principle
Never hard-cascade-delete business-critical history, evidence, ledgers, or auditability data.

## Required policy for `businesses` parent FKs

- `RESTRICT` or `SET NULL` for:
  - messages
  - audit logs
  - campaigns
  - usage/billing ledgers
  - compliance evidence
  - provider request/webhook ledgers
  - immutable business events
- `CASCADE` allowed only for ephemeral/setup resources:
  - widget settings
  - temporary onboarding sessions

## ORM alignment
For each relationship:

1. ORM cascade must be explicit.
2. DB `ON DELETE` must be explicit.
3. `delete-orphan` is allowed only when the underlying child FK has `ON DELETE CASCADE`.

## Enforcement
- `backend/tests/test_fk_delete_policy.py`
- Transitional exceptions are documented in-test and should be burned down migration-by-migration.
