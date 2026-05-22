from __future__ import annotations

import base64
import hashlib
import hmac
import json
from typing import Any

from app.config import settings


class InvalidCursorError(Exception):
    pass


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _b64decode(raw: str) -> bytes:
    padding = "=" * (-len(raw) % 4)
    return base64.urlsafe_b64decode(raw + padding)


def _secret() -> str:
    secret = getattr(settings, "CURSOR_SECRET", None) or settings.SECRET_KEY
    if not secret:
        raise RuntimeError("CURSOR_SECRET or SECRET_KEY is required")
    return str(secret)


def _sign(payload_json: str) -> str:
    digest = hmac.new(
        _secret().encode("utf-8"),
        payload_json.encode("utf-8"),
        hashlib.sha256,
    ).digest()
    return _b64encode(digest)


def encode_cursor(payload: dict[str, Any]) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signature = _sign(payload_json)
    envelope = {"p": payload, "s": signature}
    return _b64encode(json.dumps(envelope, separators=(",", ":")).encode("utf-8"))


def decode_cursor(cursor: str) -> dict[str, Any]:
    try:
        raw = _b64decode(cursor)
        envelope = json.loads(raw.decode("utf-8"))
        payload = envelope["p"]
        signature = envelope["s"]

        payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        expected_signature = _sign(payload_json)

        if not hmac.compare_digest(signature, expected_signature):
            raise InvalidCursorError("Cursor signature mismatch")

        return payload
    except Exception as exc:
        if isinstance(exc, InvalidCursorError):
            raise
        raise InvalidCursorError("Invalid cursor") from exc


def stable_filters_hash(filters: dict[str, Any]) -> str:
    raw = json.dumps(filters, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def stable_hash(value: Any) -> str:
    raw = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
