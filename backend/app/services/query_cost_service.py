from __future__ import annotations

from dataclasses import dataclass


@dataclass
class QueryRisk:
    risk_class: str
    reasons: list[str]


def classify_table_query(*, table: str, sort_by: str, limit: int, filters: dict) -> QueryRisk:
    reasons: list[str] = []
    risk = "SAFE"
    search = str((filters or {}).get("search") or "").strip()
    opt_in_status = (filters or {}).get("opt_in_status")
    suppressed = (filters or {}).get("suppressed")

    if limit > 250:
        risk = "BLOCKED"
        reasons.append("limit_exceeds_backend_budget")
    if "*" in search or "%" in search:
        risk = "BLOCKED"
        reasons.append("unsupported_wildcard_search")
    if search and len(search) >= 2:
        risk = "EXPENSIVE"
        reasons.append("broad_search_scan")
    if table == "contacts":
        if not opt_in_status and suppressed is None:
            if risk == "SAFE":
                risk = "EXPENSIVE"
            reasons.append("no_optin_or_suppression_filter")
        if sort_by not in {"updated_at"}:
            if risk != "BLOCKED":
                risk = "DANGEROUS"
            reasons.append("non_hotpath_sort_field")
    if not reasons:
        reasons.append("indexed_filters_and_sort")
    return QueryRisk(risk_class=risk, reasons=reasons)


def classify_bulk_action(
    *,
    action: str,
    approx_affected: int,
    includes_sensitive_columns: bool,
    has_opt_in_filter: bool,
) -> QueryRisk:
    reasons: list[str] = []
    risk = "SAFE"
    if approx_affected > 50000:
        risk = "DANGEROUS"
        reasons.append("large_scale_mutation")
    if includes_sensitive_columns:
        if risk != "BLOCKED":
            risk = "DANGEROUS"
        reasons.append("sensitive_columns_requested")
    if action in {"export_contacts", "bulk_suppress_contacts", "bulk_tag_contacts"} and approx_affected > 10000:
        if risk == "SAFE":
            risk = "EXPENSIVE"
        reasons.append("high_volume_action")
    if action in {"campaign_send", "export_contacts"} and not has_opt_in_filter:
        risk = "BLOCKED"
        reasons.append("missing_opt_in_filter_for_marketing")
    if not reasons:
        reasons.append("bounded_and_policy_compliant")
    return QueryRisk(risk_class=risk, reasons=reasons)

