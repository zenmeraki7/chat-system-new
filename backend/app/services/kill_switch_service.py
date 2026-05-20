from app.models.business_domains import KillSwitch
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ForbiddenException
from datetime import datetime, timezone


class KillSwitchService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def assert_not_blocked(self, scope_type: str, scope_id: str | None = None):
        now = datetime.now(timezone.utc)
        q = select(KillSwitch).where(
            KillSwitch.scope_type == scope_type,
            KillSwitch.enabled.is_(True),
            KillSwitch.deleted_at.is_(None),
        )
        if scope_id is not None:
            q = q.where((KillSwitch.scope_id == scope_id) | (KillSwitch.scope_id.is_(None)))
        row = (await self.db.execute(q)).scalars().first()
        if row and (row.expires_at is None or row.expires_at > now):
            raise ForbiddenException(f"Operation blocked by kill switch: {scope_type}")
