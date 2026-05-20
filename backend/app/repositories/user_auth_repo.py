from dataclasses import dataclass
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.business import Business
from app.models.business_domains import User, BusinessMembership


@dataclass(frozen=True)
class UserAuthRecord:
    user_id: UUID
    email: str
    password_hash: str
    password_rehash_required: bool
    business_id: UUID
    business_status: str


class UserAuthRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_user_by_normalized_email(self, email: str) -> User | None:
        normalized = email.strip().lower()
        result = await self.db.execute(
            select(User).where(
                func.lower(User.email) == normalized,
                User.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def get_auth_record_by_email(self, email: str) -> UserAuthRecord | None:
        normalized = email.strip().lower()
        result = await self.db.execute(
            select(
                User.id,
                User.email,
                User.password_hash,
                User.password_rehash_required,
                Business.id,
                Business.status,
            )
            .join(BusinessMembership, BusinessMembership.user_id == User.id)
            .join(Business, Business.id == BusinessMembership.business_id)
            .where(
                func.lower(User.email) == normalized,
                User.deleted_at.is_(None),
                Business.deleted_at.is_(None),
                BusinessMembership.status == "active",
            )
            .order_by(BusinessMembership.created_at.asc())
            .limit(1)
        )
        row = result.first()
        if not row:
            return None
        return UserAuthRecord(
            user_id=row[0],
            email=row[1],
            password_hash=row[2],
            password_rehash_required=row[3],
            business_id=row[4],
            business_status=row[5],
        )
