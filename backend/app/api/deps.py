from uuid import UUID
from dataclasses import dataclass
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.core.security import decode_access_token
from app.repositories.business_repo import BusinessRepository
from app.models.business import Business
from app.models.business_domains import User, BusinessMembership

bearer_scheme = HTTPBearer()

@dataclass
class CurrentActor:
    business: Business
    user: User
    membership: BusinessMembership
    permissions: set[str]


def _parse_subject(subject: str) -> tuple[UUID, UUID | None]:
    parts = subject.split(":")
    if len(parts) == 2:
        return UUID(parts[0]), UUID(parts[1])
    return UUID(subject), None


async def get_current_business(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> Business:
    actor = await get_current_actor(credentials=credentials, db=db)
    return actor.business


async def get_current_actor(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> CurrentActor:
    token = credentials.credentials
    subject = decode_access_token(token)
    if not subject:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        business_id, user_id = _parse_subject(subject)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Malformed authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    repo = BusinessRepository(db)
    business = await repo.get_by_id(business_id)
    if not business or business.status != "active":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Business account not found or deactivated",
        )

    membership = await repo.get_membership(business.id, user_id) if user_id else await repo.get_first_active_membership(business.id)
    if not membership:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Active membership not found for this business",
        )
    if not membership.role:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Membership role is not configured",
        )
    permissions = {perm.permission_code for perm in membership.role.permissions}
    if membership.role.code == "owner":
        permissions.add("*")
    if "*" in permissions:
        permissions.add("admin:*")
    return CurrentActor(
        business=business,
        user=membership.user,
        membership=membership,
        permissions=permissions,
    )


def require_permissions(*required: str):
    async def _guard(actor: CurrentActor = Depends(get_current_actor)) -> CurrentActor:
        if "*" in actor.permissions:
            return actor
        missing = [code for code in required if code not in actor.permissions]
        if missing:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Missing required permissions: {', '.join(missing)}",
            )
        return actor

    return _guard
