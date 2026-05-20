from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from app.database import get_db
from app.schemas.business import (
    BusinessProfileResponse,
    BusinessProfileUpdate,
    BusinessAISettingsResponse,
    BusinessAISettingsUpdate,
    WidgetSettingsResponse,
    WidgetSettingsUpdate,
    WidgetScriptResponse,
    ApiKeyIssuedResponse,
)
from app.services.business_service import BusinessService
from app.api.deps import CurrentActor, require_permissions
from app.services.audit_log_service import AuditLogService
from app.services.api_key_rotation_service import ApiKeyRotationService

router = APIRouter(prefix="/business", tags=["Business"])


@router.get("/me", response_model=BusinessProfileResponse)
async def get_business(
    actor: CurrentActor = Depends(require_permissions("business:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get current business settings."""
    profile = await BusinessService(db).get_business_profile(actor.business.id)
    return BusinessProfileResponse(**profile)


@router.patch("/me/profile", response_model=BusinessProfileResponse)
async def update_business_profile(
    payload: BusinessProfileUpdate,
    actor: CurrentActor = Depends(require_permissions("business:write")),
    db: AsyncSession = Depends(get_db),
):
    """Update business profile settings."""
    svc = BusinessService(db)
    async with db.begin():
        await svc.update_settings(
            business_id=actor.business.id,
            name=payload.name,
        )
        await AuditLogService(db).write(
            action="business.settings.update",
            resource_type="business",
            business_id=actor.business.id,
            user_id=actor.user.id,
            actor_type="user",
            actor_id=str(actor.user.id),
            resource_id=str(actor.business.id),
            details={"fields": [k for k, v in payload.model_dump().items() if v is not None]},
        )
    profile = await svc.get_business_profile(actor.business.id)
    return BusinessProfileResponse(**profile)


@router.get("/me/widget", response_model=WidgetSettingsResponse)
async def get_widget_settings(
    actor: CurrentActor = Depends(require_permissions("business:read")),
    db: AsyncSession = Depends(get_db),
):
    return WidgetSettingsResponse(**(await BusinessService(db).get_widget_settings(actor.business.id)))


@router.patch("/me/widget", response_model=WidgetSettingsResponse)
async def update_widget_settings(
    payload: WidgetSettingsUpdate,
    actor: CurrentActor = Depends(require_permissions("business:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = BusinessService(db)
    async with db.begin():
        await svc.update_settings(
            business_id=actor.business.id,
            widget_color=payload.widget_color,
            widget_title=payload.widget_title,
        )
    return WidgetSettingsResponse(**(await svc.get_widget_settings(actor.business.id)))


@router.get("/me/ai", response_model=BusinessAISettingsResponse)
async def get_ai_settings(
    actor: CurrentActor = Depends(require_permissions("business:read")),
    db: AsyncSession = Depends(get_db),
):
    return BusinessAISettingsResponse(**(await BusinessService(db).get_ai_settings(actor.business.id)))


@router.patch("/me/ai", response_model=BusinessAISettingsResponse)
async def update_ai_settings(
    payload: BusinessAISettingsUpdate,
    actor: CurrentActor = Depends(require_permissions("business:write")),
    db: AsyncSession = Depends(get_db),
):
    svc = BusinessService(db)
    async with db.begin():
        await svc.update_settings(
            business_id=actor.business.id,
            system_prompt=payload.system_prompt,
        )
    return BusinessAISettingsResponse(**(await svc.get_ai_settings(actor.business.id)))


@router.get("/widget-script", response_model=WidgetScriptResponse)
async def get_widget_script(
    actor: CurrentActor = Depends(require_permissions("business:read")),
    db: AsyncSession = Depends(get_db),
):
    """Get the embeddable widget script snippet."""
    svc = BusinessService(db)
    return await svc.get_widget_script(actor.business.id)


@router.post("/regenerate-key", response_model=ApiKeyIssuedResponse)
async def regenerate_api_key(
    actor: CurrentActor = Depends(require_permissions("api_keys:rotate")),
    db: AsyncSession = Depends(get_db),
):
    """Generate a new widget API key and return it once (non-recoverable afterward)."""
    async with db.begin():
        result = await ApiKeyRotationService(db).rotate_key(
            actor_user_id=actor.user.id,
            business_id=actor.business.id,
            scopes=["chat:write", "chat:read"],
            environment="live",
            name="Regenerated key",
            revoke_previous_in_environment=False,
        )
    return ApiKeyIssuedResponse(
        key_prefix=result.key_prefix,
        raw_key=result.raw_api_key,
    )
