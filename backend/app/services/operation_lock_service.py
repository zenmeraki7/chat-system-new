from datetime import datetime, timezone
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.exceptions import ConflictException
from app.models.business_domains import OperationLock


class OperationLockService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def acquire(self, business_id: UUID, lock_name: str, owner_token: str, expires_at: datetime) -> OperationLock:
        now = datetime.now(timezone.utc)
        existing = await self.db.execute(
            select(OperationLock).where(
                OperationLock.business_id == business_id,
                OperationLock.lock_name == lock_name,
                OperationLock.expires_at > now,
                OperationLock.deleted_at.is_(None),
            )
        )
        lock = existing.scalar_one_or_none()
        if lock:
            raise ConflictException(f"Operation lock is already held: {lock_name}")

        lock = OperationLock(
            business_id=business_id,
            lock_name=lock_name,
            owner_token=owner_token,
            expires_at=expires_at,
        )
        self.db.add(lock)
        await self.db.flush()
        return lock

    async def release(self, business_id: UUID, lock_name: str, owner_token: str) -> int:
        existing = await self.db.execute(
            select(OperationLock).where(
                OperationLock.business_id == business_id,
                OperationLock.lock_name == lock_name,
                OperationLock.owner_token == owner_token,
                OperationLock.deleted_at.is_(None),
            )
        )
        lock = existing.scalar_one_or_none()
        if not lock:
            return 0
        lock.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return 1
