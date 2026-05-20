from datetime import datetime, timedelta, timezone
from uuid import UUID
import secrets

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_token
from app.models.business_domains import EmbeddedSignupSession


class EmbeddedSignupService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_session(
        self,
        *,
        business_id: UUID,
        user_id: UUID,
        expected_origin: str,
        ttl_minutes: int = 15,
    ) -> tuple[EmbeddedSignupSession, str]:
        raw_state = secrets.token_urlsafe(48)
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(minutes=ttl_minutes)

        # Invalidate any pending sessions for this actor before issuing a new one.
        await self.db.execute(
            update(EmbeddedSignupSession)
            .where(
                EmbeddedSignupSession.business_id == business_id,
                EmbeddedSignupSession.user_id == user_id,
                EmbeddedSignupSession.status == "pending",
                EmbeddedSignupSession.deleted_at.is_(None),
            )
            .values(status="failed", failed_at=now, failure_reason="superseded_by_new_session")
        )

        row = EmbeddedSignupSession(
            business_id=business_id,
            user_id=user_id,
            state_hash=hash_token(raw_state),
            status="pending",
            expected_origin=expected_origin,
            expires_at=expires_at,
        )
        self.db.add(row)
        await self.db.flush()
        return row, raw_state

