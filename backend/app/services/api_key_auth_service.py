from dataclasses import dataclass
from datetime import datetime, timezone
import hmac
import logging
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import hash_token
from app.models.business import Business
from app.models.business_domains import BusinessApiKey
from app.services.api_key_parser import ApiKeyParser


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ApiKeyPrincipal:
    business_id: UUID
    api_key_id: UUID
    scopes: frozenset[str]
    environment: str
    is_active: bool


class ApiKeyAuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def authenticate(
        self,
        raw_api_key: str,
        required_scope: str | None = None,
        expected_environment: str | None = None,
    ) -> ApiKeyPrincipal | None:
        parsed = ApiKeyParser.parse(raw_api_key)
        matched = None
        if parsed:
            candidate_hash = hash_token(parsed.raw)
            result = await self.db.execute(
                select(BusinessApiKey, Business)
                .join(Business, Business.id == BusinessApiKey.business_id)
                .where(
                    BusinessApiKey.key_prefix == parsed.prefix,
                    BusinessApiKey.revoked_at.is_(None),
                    BusinessApiKey.disabled_at.is_(None),
                    Business.deleted_at.is_(None),
                ).order_by(BusinessApiKey.created_at.desc(), BusinessApiKey.id.desc())
            )
            rows = result.all()
            for key, business in rows:
                if hmac.compare_digest(candidate_hash, key.key_hash):
                    matched = (key, business)
                    break
        elif ApiKeyParser.is_legacy_uuid(raw_api_key):
            logger.warning("legacy_uuid_api_key_used")
            legacy_hash = hash_token(raw_api_key.strip())
            legacy_result = await self.db.execute(
                select(BusinessApiKey, Business)
                .join(Business, Business.id == BusinessApiKey.business_id)
                .where(
                    BusinessApiKey.key_hash == legacy_hash,
                    BusinessApiKey.revoked_at.is_(None),
                    BusinessApiKey.disabled_at.is_(None),
                    Business.deleted_at.is_(None),
                )
                .order_by(BusinessApiKey.created_at.desc(), BusinessApiKey.id.desc())
                .limit(1)
            )
            matched = legacy_result.first()
        else:
            logger.warning("malformed_api_key")
            return None

        if not matched:
            logger.warning("invalid_api_key")
            return None

        key, business = matched
        now = datetime.now(timezone.utc)
        if key.expires_at is not None and key.expires_at <= now:
            logger.warning("expired_api_key")
            return None
        if business.status != "active":
            logger.warning("inactive_business_api_key")
            return None
        if business.billing_status in {"payment_failed", "suspended"}:
            logger.warning("api_access_blocked_by_billing_status")
            return None

        scopes = frozenset(key.scopes or [])
        if required_scope and required_scope not in scopes and "*" not in scopes:
            logger.warning("insufficient_api_key_scope")
            return None
        if expected_environment and key.environment != expected_environment:
            logger.warning("api_key_environment_mismatch")
            return None

        key.last_used_at = now
        await self.db.flush()
        return ApiKeyPrincipal(
            business_id=business.id,
            api_key_id=key.id,
            scopes=scopes,
            environment=key.environment,
            is_active=True,
        )
