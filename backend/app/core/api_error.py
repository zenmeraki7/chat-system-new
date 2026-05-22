from __future__ import annotations

from uuid import uuid4
from fastapi import HTTPException


def build_api_error(*, code: str, user_message: str, request_id: str | None = None, retryable: bool = False) -> dict:
    return {
        "code": str(code or "UNKNOWN_ERROR"),
        "user_message": str(user_message or "Something went wrong. Contact support with request ID."),
        "request_id": str(request_id or uuid4()),
        "retryable": bool(retryable),
    }


def normalize_http_exception(exc: HTTPException, *, request_id: str | None = None) -> dict:
    detail = exc.detail
    if isinstance(detail, dict):
        code = str(detail.get("code") or f"HTTP_{exc.status_code}")
        user_message = str(detail.get("user_message") or detail.get("message") or detail.get("detail") or "Request failed")
        retryable = bool(detail.get("retryable") is True)
        incoming_request_id = detail.get("request_id")
        return build_api_error(
            code=code,
            user_message=user_message,
            request_id=str(incoming_request_id or request_id or ""),
            retryable=retryable,
        )
    return build_api_error(
        code=f"HTTP_{exc.status_code}",
        user_message=str(detail or "Request failed"),
        request_id=request_id,
        retryable=False,
    )
