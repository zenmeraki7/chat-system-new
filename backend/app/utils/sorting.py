from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal


SortDir = Literal["asc", "desc"]


@dataclass(frozen=True)
class ResolvedSort:
    key: str
    dir: SortDir
    column: Any
    model_attr: str
    nullable: bool
    cursor_type: str


class InvalidSortError(Exception):
    pass


def resolve_sort(
    *,
    sort_key: str | None,
    sort_dir: str | None,
    sort_registry: dict[str, dict[str, Any]],
    default_sort_key: str,
) -> ResolvedSort:
    key = str(sort_key or default_sort_key).strip()
    if key not in sort_registry:
        raise InvalidSortError(f"Unsupported sort key: {key}")

    config = sort_registry[key]
    direction = str(sort_dir or config.get("default_dir", "desc")).lower().strip()
    if direction not in {"asc", "desc"}:
        raise InvalidSortError("Unsupported sort direction")

    return ResolvedSort(
        key=key,
        dir=direction,  # type: ignore[arg-type]
        column=config["column"],
        model_attr=config["model_attr"],
        nullable=bool(config.get("nullable", False)),
        cursor_type=str(config["cursor_type"]),
    )


def build_order_by(resolved_sort: ResolvedSort, id_column):
    if resolved_sort.dir == "desc":
        primary = resolved_sort.column.desc()
        secondary = id_column.desc()
    else:
        primary = resolved_sort.column.asc()
        secondary = id_column.asc()
    if resolved_sort.nullable:
        primary = primary.nullslast()
    return [primary, secondary]

