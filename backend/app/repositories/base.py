from typing import TypeVar, Generic, Type, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.database import Base

ModelType = TypeVar("ModelType", bound=Base)


class BaseReadRepository(Generic[ModelType]):
    def __init__(self, model: Type[ModelType], db: AsyncSession):
        self.model = model
        self.db = db

    async def get_by_id(self, id: UUID) -> Optional[ModelType]:
        result = await self.db.execute(
            select(self.model).where(self.model.id == id)
        )
        return result.scalar_one_or_none()


class ReadOnlyBaseRepository(BaseReadRepository[ModelType], Generic[ModelType]):
    pass


class ReadModelRepository(BaseReadRepository[ModelType], Generic[ModelType]):
    pass


class SecretRepository(BaseReadRepository[ModelType], Generic[ModelType]):
    async def create(self, **kwargs) -> ModelType:
        raise NotImplementedError(
            "SecretRepository must expose explicit safe methods (hash/encrypt), not generic create"
        )


class MutableRepository(BaseReadRepository[ModelType], Generic[ModelType]):
    async def create(self, **kwargs) -> ModelType:
        instance = self.model(**kwargs)
        self.db.add(instance)
        await self.db.flush()
        return instance


class TenantRepository(MutableRepository[ModelType], Generic[ModelType]):
    async def get_by_id_for_business(
        self,
        *,
        business_id: UUID,
        id: UUID,
    ) -> Optional[ModelType]:
        result = await self.db.execute(
            select(self.model).where(
                self.model.business_id == business_id,
                self.model.id == id,
                self.model.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()


class TenantMutableRepository(TenantRepository[ModelType], Generic[ModelType]):
    pass


class AppendOnlyRepository(BaseReadRepository[ModelType], Generic[ModelType]):
    async def append(self, **kwargs) -> ModelType:
        instance = self.model(**kwargs)
        self.db.add(instance)
        await self.db.flush()
        return instance


class TenantAppendOnlyRepository(AppendOnlyRepository[ModelType], Generic[ModelType]):
    async def get_by_id_for_business(
        self,
        *,
        business_id: UUID,
        id: UUID,
    ) -> Optional[ModelType]:
        result = await self.db.execute(
            select(self.model).where(
                self.model.business_id == business_id,
                self.model.id == id,
                self.model.deleted_at.is_(None),
            )
        )
        return result.scalar_one_or_none()
