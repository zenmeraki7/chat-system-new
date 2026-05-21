from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import OnboardingEventLedger


class OnboardingEventLedgerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def append(
        self,
        *,
        business_id: UUID,
        event_type: str,
        event_status: str = "info",
        operation_id: str | None = None,
        merchant_user_id: UUID | None = None,
        waba_id: str | None = None,
        phone_number_id: str | None = None,
        meta_app_id: str | None = None,
        graph_api_endpoint: str | None = None,
        graph_request_id: str | None = None,
        graph_error_code: str | None = None,
        graph_error_subcode: str | None = None,
        fbtrace_id: str | None = None,
        trace_id: str | None = None,
        graph_response_json: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> OnboardingEventLedger:
        row = OnboardingEventLedger(
            business_id=business_id,
            event_type=event_type,
            event_status=event_status,
            operation_id=operation_id,
            merchant_user_id=merchant_user_id,
            waba_id=waba_id,
            phone_number_id=phone_number_id,
            meta_app_id=meta_app_id,
            graph_api_endpoint=graph_api_endpoint,
            graph_request_id=graph_request_id,
            graph_error_code=graph_error_code,
            graph_error_subcode=graph_error_subcode,
            fbtrace_id=fbtrace_id,
            trace_id=trace_id,
            graph_response_json=graph_response_json,
            error_message=error_message,
        )
        self.db.add(row)
        await self.db.flush()
        return row

