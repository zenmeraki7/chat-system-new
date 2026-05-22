from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class FilterExpression(BaseModel):
    field: str
    operator: str
    value: Any | None = None
    values: list[Any] | None = None
    from_: Any | None = Field(default=None, alias="from")
    to: Any | None = None

    model_config = {"populate_by_name": True}


class FilterGroup(BaseModel):
    logic: Literal["AND"] = "AND"
    filters: list[FilterExpression] = Field(default_factory=list)


class SortRequest(BaseModel):
    key: str = "updated_at"
    dir: Literal["asc", "desc"] = "desc"


class ListQueryRequest(BaseModel):
    limit: int = 50
    cursor: str | None = None
    search: str | None = None
    sort: SortRequest = Field(default_factory=SortRequest)
    filterGroup: FilterGroup = Field(default_factory=FilterGroup)

