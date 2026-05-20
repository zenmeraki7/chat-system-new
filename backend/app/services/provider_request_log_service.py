from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.business_domains import ProviderRequestLog


class ProviderRequestLogService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def write(
        self,
        provider: str,
        operation: str,
        request_id: str,
        credential_id: UUID | None = None,
        business_id: UUID | None = None,
        operation_id: str | None = None,
        request_correlation_id: str | None = None,
        provider_response_id: str | None = None,
        channel_id: UUID | None = None,
        phone_number_id: str | None = None,
        message_id: UUID | None = None,
        campaign_id: UUID | None = None,
        external_asset_id: str | None = None,
        response_status: int | None = None,
        provider_error_code: str | None = None,
        retryable: bool = False,
    ) -> ProviderRequestLog:
        row = ProviderRequestLog(
            business_id=business_id,
            credential_id=credential_id,
            provider=provider,
            operation=operation,
            operation_id=operation_id,
            request_correlation_id=request_correlation_id,
            provider_response_id=provider_response_id,
            channel_id=channel_id,
            phone_number_id=phone_number_id,
            message_id=message_id,
            campaign_id=campaign_id,
            external_asset_id=external_asset_id,
            request_id=request_id,
            response_status=response_status,
            provider_error_code=provider_error_code,
            retryable=retryable,
        )
        self.db.add(row)
        await self.db.flush()
        return row
