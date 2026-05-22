from __future__ import annotations

from sqlalchemy import and_, or_


def build_cursor_condition(
    *,
    sort_column,
    id_column,
    sort_dir: str,
    cursor_sort_value,
    cursor_id,
):
    if cursor_sort_value is None or cursor_id is None:
        return None

    if sort_dir == "desc":
        return or_(
            sort_column < cursor_sort_value,
            and_(sort_column == cursor_sort_value, id_column < cursor_id),
        )
    return or_(
        sort_column > cursor_sort_value,
        and_(sort_column == cursor_sort_value, id_column > cursor_id),
    )

