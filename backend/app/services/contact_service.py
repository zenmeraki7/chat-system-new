from __future__ import annotations

from datetime import datetime
from uuid import UUID

from app.repositories.contact_repo import ContactRepository
from app.sorting.contact_sorts import CONTACT_SORTS
from app.schemas.list_query import ListQueryRequest
from app.utils.cursor import InvalidCursorError, decode_cursor, encode_cursor, stable_hash
from app.utils.sorting import resolve_sort


MAX_PAGE_SIZE = 100
DEFAULT_PAGE_SIZE = 50


class ContactService:
    def __init__(self, repository: ContactRepository):
        self.repository = repository

    def _normalize_limit(self, limit: int | None) -> int:
        if limit is None:
            return DEFAULT_PAGE_SIZE

        if limit < 1:
            return DEFAULT_PAGE_SIZE

        return min(limit, MAX_PAGE_SIZE)

    def _serialize_sort_value(self, value):
        if hasattr(value, "isoformat"):
            return value.isoformat()
        return value

    def _parse_sort_value(self, value, cursor_type: str):
        if value is None:
            return None
        if cursor_type == "datetime":
            parsed = datetime.fromisoformat(str(value))
            return parsed
        return value

    async def search_contacts(
        self,
        *,
        business_id: UUID,
        query: ListQueryRequest,
    ) -> dict:
        limit = self._normalize_limit(query.limit)
        query_fingerprint = stable_hash(
            {
                "resource": "contacts",
                "businessId": str(business_id),
                "search": query.search or "",
                "filters": query.filterGroup.model_dump(mode="json", by_alias=True),
                "sort": query.sort.model_dump(),
            }
        )

        resolved_sort = resolve_sort(
            sort_key=query.sort.key,
            sort_dir=query.sort.dir,
            sort_registry=CONTACT_SORTS,
            default_sort_key="updated_at",
        )

        cursor_sort_value = None
        cursor_id = None
        if query.cursor:
            payload = decode_cursor(query.cursor)
            if payload.get("resource") != "contacts":
                raise InvalidCursorError("Cursor resource mismatch")
            if str(payload.get("businessId")) != str(business_id):
                raise InvalidCursorError("Cursor business mismatch")
            if payload.get("queryFingerprint") != query_fingerprint:
                raise InvalidCursorError("CURSOR_QUERY_MISMATCH")
            if payload.get("sortKey") != resolved_sort.key or payload.get("sortDir") != resolved_sort.dir:
                raise InvalidCursorError("Cursor sort mismatch")
            cursor_sort_value = self._parse_sort_value(payload.get("sortValue"), resolved_sort.cursor_type)
            cursor_id = UUID(str(payload.get("id")))

        rows, resolved_sort, total_estimate = await self.repository.search_contacts(
            business_id=business_id,
            limit=limit,
            search=query.search,
            filter_group=query.filterGroup,
            sort_key=resolved_sort.key,
            sort_dir=resolved_sort.dir,
            cursor_sort_value=cursor_sort_value,
            cursor_id=cursor_id,
        )

        has_next_page = len(rows) > limit
        page_rows = rows[:limit]

        next_cursor = None
        if has_next_page and page_rows:
            last = page_rows[-1]
            next_cursor = encode_cursor(
                {
                    "resource": "contacts",
                    "businessId": str(business_id),
                    "queryFingerprint": query_fingerprint,
                    "sortKey": resolved_sort.key,
                    "sortDir": resolved_sort.dir,
                    "sortValue": self._serialize_sort_value(getattr(last, resolved_sort.model_attr)),
                    "id": str(last.id),
                }
            )

        data = [
            {
                "id": str(row.id),
                "name": row.display_name,
                "phoneNumber": row.normalized_phone,
                "status": row.status,
                "optInStatus": row.opt_in_status,
                "source": row.opt_in_source,
                "createdAt": row.created_at.isoformat() if row.created_at else None,
                "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
            }
            for row in page_rows
        ]

        return {
            "data": data,
            "pageInfo": {
                "limit": limit,
                "hasNextPage": has_next_page,
                "nextCursor": next_cursor,
            },
            "meta": {
                "search": query.search,
                "filters": query.filterGroup.model_dump(mode="json", by_alias=True),
                "sort": {
                    "key": resolved_sort.key,
                    "dir": resolved_sort.dir,
                },
                "allowedFilters": ["status", "optInStatus", "source", "createdAt", "tags"],
                "allowedSorts": list(CONTACT_SORTS.keys()),
                "queryFingerprint": query_fingerprint,
                "totalEstimate": total_estimate,
            },
        }
