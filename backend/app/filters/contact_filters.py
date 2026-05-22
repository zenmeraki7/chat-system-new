from __future__ import annotations

from datetime import datetime

from sqlalchemy import and_

from app.models.business_domains import Contact


class InvalidFilterError(Exception):
    pass


def _parse_datetime(value: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception as exc:  # pragma: no cover - defensive parse guard
        raise InvalidFilterError("Invalid datetime value") from exc


def compile_status_filter(expression):
    if expression.operator == "equals":
        return Contact.status == str(expression.value or "").strip().lower()
    if expression.operator == "in":
        values = [str(v).strip().lower() for v in (expression.values or []) if str(v).strip()]
        return Contact.status.in_(values)
    raise InvalidFilterError("Unsupported operator for status")


def compile_opt_in_filter(expression):
    if expression.operator == "equals":
        return Contact.opt_in_status == str(expression.value or "").strip().lower()
    if expression.operator == "in":
        values = [str(v).strip().lower() for v in (expression.values or []) if str(v).strip()]
        return Contact.opt_in_status.in_(values)
    raise InvalidFilterError("Unsupported operator for optInStatus")


def compile_source_filter(expression):
    if expression.operator == "equals":
        return Contact.opt_in_source == (str(expression.value).strip() or None)
    if expression.operator == "in":
        values = [str(v).strip() for v in (expression.values or []) if str(v).strip()]
        return Contact.opt_in_source.in_(values)
    raise InvalidFilterError("Unsupported operator for source")


def compile_created_at_filter(expression):
    if expression.operator == "between":
        return and_(
            Contact.created_at >= _parse_datetime(str(expression.from_)),
            Contact.created_at <= _parse_datetime(str(expression.to)),
        )
    if expression.operator == "gte":
        return Contact.created_at >= _parse_datetime(str(expression.value))
    if expression.operator == "lte":
        return Contact.created_at <= _parse_datetime(str(expression.value))
    raise InvalidFilterError("Unsupported operator for createdAt")


def compile_tags_filter(expression):
    if expression.operator == "includes_any":
        values = [str(v).strip().lower() for v in (expression.values or []) if str(v).strip()]
        if not values:
            raise InvalidFilterError("tags includes_any requires values")
        clauses = [Contact.tags.contains([value]) for value in values]
        from sqlalchemy import or_
        return or_(*clauses)
    raise InvalidFilterError("Unsupported operator for tags")


CONTACT_FILTERS = {
    "status": compile_status_filter,
    "optInStatus": compile_opt_in_filter,
    "source": compile_source_filter,
    "createdAt": compile_created_at_filter,
    "tags": compile_tags_filter,
}

