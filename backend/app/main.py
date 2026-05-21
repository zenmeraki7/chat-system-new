from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import os

from app.config import settings
from app.database import engine, Base
from app.api.v1 import (
    admin_support,
    analytics,
    auth,
    automations,
    business,
    campaigns,
    commerce,
    contacts,
    conversations,
    public,
    realtime,
    templates,
    websocket,
    whatsapp,
)
from app.services.campaign_batch_dispatch_worker import CampaignBatchDispatchWorker
from app.services.campaign_dispatch_worker import CampaignDispatchWorker
from app.services.campaign_finalize_worker import CampaignFinalizeWorker
from app.services.campaign_finalize_sweeper_worker import CampaignFinalizeSweeperWorker
from app.services.campaign_quality_guard_worker import CampaignQualityGuardWorker
from app.services.campaign_scheduler_worker import CampaignSchedulerWorker
from app.services.billing_finalizer_worker import BillingFinalizerWorker
from app.services.contact_import_worker import ContactImportWorker
from app.services.contact_export_worker import ContactExportWorker
from app.services.message_send_worker import MessageSendWorker
from app.services.webhook_status_worker import WebhookStatusWorker
from app.services.webhook_outbox_consumer import WebhookOutboxConsumer
from app.services.waba_subscription_reconcile_worker import WabaSubscriptionReconcileWorker
from app.services.whatsapp_phone_registration_worker import WhatsAppPhoneRegistrationWorker
from app.services.whatsapp_phone_registration_reconcile_worker import WhatsAppPhoneRegistrationReconcileWorker
from app.services.whatsapp_credential_health_worker import WhatsAppCredentialHealthWorker
from app.services.outbound_send_worker import OutboundSendWorker
from app.services.object_storage_service import object_storage_service
from app.services.template_sync_reconcile_worker import TemplateSyncReconcileWorker
from app.services.whatsapp_onboarding_health_reconcile_worker import WhatsAppOnboardingHealthReconcileWorker
from app.services.bulk_job_worker import BulkJobWorker


def _validate_startup_configuration() -> None:
    env = (settings.APP_ENV or "").strip().lower()
    is_local_env = env in {"local", "dev", "development", "test"}
    if is_local_env:
        return
    required = {
        "META_APP_ID": str(settings.META_APP_ID or settings.FB_APP_ID or "").strip(),
        "META_APP_SECRET": str(settings.META_APP_SECRET or settings.FB_APP_SECRET or "").strip(),
        "META_EMBEDDED_SIGNUP_CONFIG_ID": str(settings.META_EMBEDDED_SIGNUP_CONFIG_ID or "").strip(),
    }
    missing = [k for k, v in required.items() if not v]
    if missing:
        raise RuntimeError(f"Missing required Meta configuration in non-local environment: {', '.join(missing)}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_configuration()
    # Create tables on startup (Alembic handles migrations in production)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    webhook_consumer = WebhookOutboxConsumer()
    outbound_worker = OutboundSendWorker()
    contact_import_worker = ContactImportWorker()
    contact_export_worker = ContactExportWorker()
    campaign_scheduler_worker = CampaignSchedulerWorker()
    campaign_dispatch_worker = CampaignDispatchWorker()
    campaign_batch_dispatch_worker = CampaignBatchDispatchWorker()
    campaign_finalize_worker = CampaignFinalizeWorker()
    campaign_finalize_sweeper_worker = CampaignFinalizeSweeperWorker()
    campaign_quality_guard_worker = CampaignQualityGuardWorker()
    billing_finalizer_worker = BillingFinalizerWorker()
    message_send_worker = MessageSendWorker()
    webhook_status_worker = WebhookStatusWorker()
    waba_subscription_reconcile_worker = WabaSubscriptionReconcileWorker()
    whatsapp_phone_registration_worker = WhatsAppPhoneRegistrationWorker()
    whatsapp_phone_registration_reconcile_worker = WhatsAppPhoneRegistrationReconcileWorker()
    whatsapp_credential_health_worker = WhatsAppCredentialHealthWorker()
    template_sync_reconcile_worker = TemplateSyncReconcileWorker()
    whatsapp_onboarding_health_reconcile_worker = WhatsAppOnboardingHealthReconcileWorker()
    bulk_job_worker = BulkJobWorker()
    await webhook_consumer.start()
    await outbound_worker.start()
    await contact_import_worker.start()
    await contact_export_worker.start()
    await campaign_scheduler_worker.start()
    await campaign_dispatch_worker.start()
    await campaign_batch_dispatch_worker.start()
    await campaign_finalize_worker.start()
    await campaign_finalize_sweeper_worker.start()
    await campaign_quality_guard_worker.start()
    await billing_finalizer_worker.start()
    await message_send_worker.start()
    await webhook_status_worker.start()
    await waba_subscription_reconcile_worker.start()
    await whatsapp_phone_registration_worker.start()
    await whatsapp_phone_registration_reconcile_worker.start()
    await whatsapp_credential_health_worker.start()
    await template_sync_reconcile_worker.start()
    await whatsapp_onboarding_health_reconcile_worker.start()
    await bulk_job_worker.start()
    yield
    await bulk_job_worker.stop()
    await whatsapp_onboarding_health_reconcile_worker.stop()
    await template_sync_reconcile_worker.stop()
    await whatsapp_credential_health_worker.stop()
    await whatsapp_phone_registration_reconcile_worker.stop()
    await whatsapp_phone_registration_worker.stop()
    await waba_subscription_reconcile_worker.stop()
    await webhook_status_worker.stop()
    await message_send_worker.stop()
    await billing_finalizer_worker.stop()
    await campaign_quality_guard_worker.stop()
    await campaign_finalize_sweeper_worker.stop()
    await campaign_finalize_worker.stop()
    await campaign_batch_dispatch_worker.stop()
    await campaign_dispatch_worker.stop()
    await campaign_scheduler_worker.stop()
    await contact_import_worker.stop()
    await contact_export_worker.stop()
    await outbound_worker.stop()
    await webhook_consumer.stop()
    await engine.dispose()


app = FastAPI(
    title="ChatSystem API",
    description="Multi-tenant business chat system with OpenAI auto-replies",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files (serves widget.js)
static_dir = os.path.join(os.path.dirname(__file__), "..", "static")
if os.path.exists(static_dir):
    app.mount("/static", StaticFiles(directory=static_dir), name="static")
if object_storage_service.base_dir.exists():
    app.mount("/storage", StaticFiles(directory=str(object_storage_service.base_dir)), name="storage")

# Register routers
app.include_router(auth.router, prefix=settings.API_V1_STR)
app.include_router(business.router, prefix=settings.API_V1_STR)
app.include_router(conversations.router, prefix=settings.API_V1_STR)
app.include_router(contacts.router, prefix=settings.API_V1_STR)
app.include_router(campaigns.router, prefix=settings.API_V1_STR)
app.include_router(templates.router, prefix=settings.API_V1_STR)
app.include_router(automations.router, prefix=settings.API_V1_STR)
app.include_router(commerce.router, prefix=settings.API_V1_STR)
app.include_router(analytics.router, prefix=settings.API_V1_STR)
app.include_router(admin_support.router, prefix=settings.API_V1_STR)
app.include_router(realtime.router, prefix=settings.API_V1_STR)
app.include_router(public.router, prefix=settings.API_V1_STR)
app.include_router(whatsapp.router, prefix=settings.API_V1_STR)
app.include_router(whatsapp.webhook_alias_router)
app.include_router(websocket.router)


@app.get("/", tags=["Health"])
async def health_check():
    return {"status": "ok", "app": settings.APP_NAME, "version": "1.0.0"}


@app.get("/widget.js", tags=["Widget"])
async def serve_widget():
    """Serve the widget JavaScript file."""
    from fastapi.responses import FileResponse
    widget_path = os.path.join(os.path.dirname(__file__), "..", "static", "widget.js")
    return FileResponse(widget_path, media_type="application/javascript")
