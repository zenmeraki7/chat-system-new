from __future__ import annotations

from dataclasses import dataclass
import asyncio
from typing import Any
import json

import httpx

from app.config import settings


@dataclass
class WabaSubscriptionResult:
    app_subscribed: bool
    subscribed_fields: list[str]
    raw_response: dict[str, Any]


class WabaSubscriptionServiceError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        response_body: str | None = None,
        error_code: int | None = None,
        error_subcode: int | None = None,
        fbtrace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.fbtrace_id = fbtrace_id


class WabaSubscriptionService:
    def __init__(self, *, base_url: str = "https://graph.facebook.com") -> None:
        self.base_url = base_url.rstrip("/")

    async def ensure_subscribed(
        self,
        *,
        waba_id: str,
        access_token: str,
        app_id: str,
        max_attempts: int = 4,
    ) -> WabaSubscriptionResult:
        # First attempt is subscribe; retries are only for transient errors.
        await self._subscribe_with_retry(
            waba_id=waba_id,
            access_token=access_token,
            max_attempts=max_attempts,
        )
        # Verify authoritative state using GET subscribed_apps.
        verify = await self.verify_subscription(
            waba_id=waba_id,
            access_token=access_token,
            app_id=app_id,
            max_attempts=max_attempts,
        )
        if not verify.app_subscribed:
            raise WabaSubscriptionServiceError(
                "WABA subscribed_apps verification failed after successful subscribe request"
            )
        return verify

    async def verify_subscription(
        self,
        *,
        waba_id: str,
        access_token: str,
        app_id: str,
        max_attempts: int = 3,
    ) -> WabaSubscriptionResult:
        last_error: WabaSubscriptionServiceError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                payload = await self._get_subscribed_apps(waba_id=waba_id, access_token=access_token)
                apps = payload.get("data") or []
                subscribed = any(str((row or {}).get("id") or "") == str(app_id) for row in apps)
                fields = self._extract_subscribed_fields(payload=payload, app_id=app_id)
                return WabaSubscriptionResult(
                    app_subscribed=subscribed,
                    subscribed_fields=fields,
                    raw_response=payload,
                )
            except WabaSubscriptionServiceError as exc:
                last_error = exc
                if not self._is_transient_status(exc.status_code) or attempt == max_attempts:
                    break
                await asyncio.sleep(min(8.0, (2 ** (attempt - 1)) + 0.25))
        raise last_error or WabaSubscriptionServiceError("Unable to verify WABA subscription state")

    async def _subscribe_with_retry(self, *, waba_id: str, access_token: str, max_attempts: int) -> None:
        last_error: WabaSubscriptionServiceError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                await self._post_subscribed_apps(waba_id=waba_id, access_token=access_token)
                return
            except WabaSubscriptionServiceError as exc:
                last_error = exc
                if not self._is_transient_status(exc.status_code) or attempt == max_attempts:
                    break
                await asyncio.sleep(min(8.0, (2 ** (attempt - 1)) + 0.25))
        raise last_error or WabaSubscriptionServiceError("Unable to subscribe app to WABA")

    async def _post_subscribed_apps(self, *, waba_id: str, access_token: str) -> dict[str, Any]:
        version = settings.META_GRAPH_API_VERSION or "v21.0"
        url = f"{self.base_url}/{version}/{waba_id}/subscribed_apps"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.post(url, data={"access_token": access_token})
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text
                if self._is_already_subscribed_response(body):
                    return {"success": True, "already_subscribed": True}
                raise WabaSubscriptionServiceError(
                    "POST subscribed_apps failed",
                    status_code=exc.response.status_code,
                    response_body=body,
                    **self._extract_meta_error_fields(body),
                ) from exc
            except Exception as exc:
                raise WabaSubscriptionServiceError(
                    "POST subscribed_apps failed unexpectedly",
                    status_code=0,
                    response_body=str(exc),
                ) from exc

    async def _get_subscribed_apps(self, *, waba_id: str, access_token: str) -> dict[str, Any]:
        version = settings.META_GRAPH_API_VERSION or "v21.0"
        url = f"{self.base_url}/{version}/{waba_id}/subscribed_apps"
        async with httpx.AsyncClient() as client:
            try:
                resp = await client.get(url, params={"access_token": access_token})
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as exc:
                raise WabaSubscriptionServiceError(
                    "GET subscribed_apps failed",
                    status_code=exc.response.status_code,
                    response_body=exc.response.text,
                    **self._extract_meta_error_fields(exc.response.text),
                ) from exc
            except Exception as exc:
                raise WabaSubscriptionServiceError(
                    "GET subscribed_apps failed unexpectedly",
                    status_code=0,
                    response_body=str(exc),
                ) from exc

    @staticmethod
    def _is_transient_status(status_code: int | None) -> bool:
        status = int(status_code or 0)
        return status == 0 or status == 429 or status >= 500

    @staticmethod
    def _is_already_subscribed_response(body: str) -> bool:
        hay = (body or "").lower()
        return "already subscribed" in hay or "duplicate" in hay

    @staticmethod
    def _extract_subscribed_fields(*, payload: dict[str, Any], app_id: str) -> list[str]:
        rows = payload.get("data") or []
        for row in rows:
            if str((row or {}).get("id") or "") != str(app_id):
                continue
            fields = (row or {}).get("subscribed_fields") or []
            if isinstance(fields, list):
                return [str(f) for f in fields if f]
        return []

    @staticmethod
    def _extract_meta_error_fields(body: str | None) -> dict[str, Any]:
        if not body:
            return {"error_code": None, "error_subcode": None, "fbtrace_id": None}
        try:
            payload = json.loads(body)
        except Exception:
            return {"error_code": None, "error_subcode": None, "fbtrace_id": None}
        error = payload.get("error") or {}
        code = error.get("code")
        subcode = error.get("error_subcode")
        fbtrace_id = error.get("fbtrace_id")
        try:
            code = int(code) if code is not None else None
        except Exception:
            code = None
        try:
            subcode = int(subcode) if subcode is not None else None
        except Exception:
            subcode = None
        return {
            "error_code": code,
            "error_subcode": subcode,
            "fbtrace_id": str(fbtrace_id) if fbtrace_id else None,
        }


waba_subscription_service = WabaSubscriptionService()
