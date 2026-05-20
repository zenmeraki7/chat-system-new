from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.auth import RegisterRequest, LoginRequest, TokenResponse
from app.schemas.business import BusinessProfileResponse, BusinessCreatedResponse
from app.services.auth_service import AuthService
from app.api.deps import CurrentActor, require_permissions
from app.config import settings

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=BusinessCreatedResponse, status_code=201)
async def register(payload: RegisterRequest, db: AsyncSession = Depends(get_db)):
    """Register a new business account."""
    svc = AuthService(db)
    business, raw_api_key = await svc.register(
        business_name=payload.business_name,
        email=payload.email,
        password=payload.password,
        accepted_terms=payload.accepted_terms,
        accepted_privacy_policy=payload.accepted_privacy_policy,
    )
    from app.services.business_service import BusinessService
    profile = await BusinessService(db).get_business_profile(business.id)
    return BusinessCreatedResponse(
        business=BusinessProfileResponse(**profile),
        raw_key=raw_api_key,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Login and receive a JWT token."""
    svc = AuthService(db)
    result = await svc.login(email=payload.email, password=payload.password)
    return TokenResponse(
        access_token=result.access_token,
        expires_in=60 * settings.ACCESS_TOKEN_EXPIRE_MINUTES,
        memberships=result.memberships,
    )


@router.get("/me", response_model=BusinessProfileResponse)
async def get_me(
    actor: CurrentActor = Depends(require_permissions("business:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get current authenticated business profile."""
    from app.services.business_service import BusinessService
    profile = await BusinessService(db).get_business_profile(actor.business.id)
    return BusinessProfileResponse(**profile)
