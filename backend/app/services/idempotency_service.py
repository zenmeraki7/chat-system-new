import hashlib
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.models.business_domains import IdempotencyRecord
from app.core.exceptions import ConflictException


class IdempotencyService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _hash_payload(payload: dict) -> str:
        blob = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(blob).hexdigest()

    async def begin_or_replay(self, business_id: UUID, key: str, payload: dict) -> dict | None:
        req_hash = self._hash_payload(payload)
        result = await self.db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.business_id == business_id,
                IdempotencyRecord.key == key,
                IdempotencyRecord.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if record:
            if record.request_hash != req_hash:
                raise ConflictException("Idempotency-Key reused with different request payload")
            if record.status == "completed" and record.response_json is not None:
                return record.response_json
            return None

        self.db.add(
            IdempotencyRecord(
                business_id=business_id,
                key=key,
                request_hash=req_hash,
                status="pending",
                expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
            )
        )
        await self.db.commit()
        return None

    async def finalize(self, business_id: UUID, key: str, response_json: dict) -> None:
        result = await self.db.execute(
            select(IdempotencyRecord).where(
                IdempotencyRecord.business_id == business_id,
                IdempotencyRecord.key == key,
                IdempotencyRecord.deleted_at.is_(None),
            )
        )
        record = result.scalar_one_or_none()
        if not record:
            return
        record.status = "completed"
        record.response_json = response_json
        await self.db.commit()
