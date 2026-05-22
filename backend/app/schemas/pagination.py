from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class PageInfo(BaseModel):
    limit: int
    hasNextPage: bool
    nextCursor: Optional[str] = None


class CursorPage(BaseModel, Generic[T]):
    data: list[T]
    pageInfo: PageInfo
    meta: Optional[dict[str, Any]] = None
