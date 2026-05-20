# Raw SQL Safety Policy

All raw SQL that touches tenant-owned tables must satisfy:

1. Include `business_id = :business_id` in predicates.
2. Include bounded date/window predicates for ledger/event scans.
3. Use explicit column lists; never `SELECT *`.
4. Use bind parameters only; no string interpolation.
5. Add explain-plan review for large scans (`events`, `messages`, `usage_ledger`).

Applies to:
- repositories
- services
- migrations (except one-time DDL/backfills)
- analytics/report jobs

## Enforcement

- `backend/tests/test_code_safety_policy.py` checks no `SELECT *` and no interpolated `text(f"...")`.
- Repository APIs should expose tenant-scoped methods (`get_for_business`) and avoid naked PK reads for tenant tables.
