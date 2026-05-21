from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.exceptions import ForbiddenException, NotFoundException
from app.models.business_domains import (
    OAuthCredential,
    ProviderSyncRun,
    WhatsAppBusinessAccount,
    WhatsAppMessageTemplate,
)
from app.services.audit_log_service import AuditLogService
from app.services.onboarding_event_ledger_service import OnboardingEventLedgerService
from app.services.token_crypto_service import token_crypto_service


@dataclass
class TemplateSyncResult:
    business_id: UUID
    run_id: UUID
    status: str
    templates_fetched: int
    templates_upserted: int
    templates_marked_deleted: int
    waba_ids: list[str]
    completed_at: datetime
    failure_reason: str | None = None


class TemplateGraphSyncError(Exception):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        error_subcode: str | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.error_code = error_code
        self.error_subcode = error_subcode
        self.response_body = response_body


class TemplateGraphSyncService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.base_url = "https://graph.facebook.com"

    async def sync_business_templates(
        self,
        *,
        business_id: UUID,
        requested_by_user_id: UUID | None,
        trigger: str,
        waba_id: str | None = None,
    ) -> TemplateSyncResult:
        run = ProviderSyncRun(
            business_id=business_id,
            provider="meta",
            sync_type="whatsapp_templates",
            status="running",
            started_at=datetime.now(timezone.utc),
        )
        self.db.add(run)
        await self.db.flush()
        try:
            token = await self._resolve_access_token(business_id=business_id)
            target_wabas = await self._resolve_target_wabas(business_id=business_id, waba_id=waba_id)
            now = datetime.now(timezone.utc)
            total_fetched = 0
            total_upserted = 0
            total_marked_deleted = 0
            touched_wabas: list[str] = []

            for current_waba_id in target_wabas:
                fetched = await self._fetch_all_templates_for_waba(token=token, waba_id=current_waba_id)
                total_fetched += len(fetched)
                touched_wabas.append(current_waba_id)
                upserted, marked_deleted = await self._upsert_and_prune_waba_templates(
                    business_id=business_id,
                    waba_id=current_waba_id,
                    templates=fetched,
                    synced_at=now,
                )
                total_upserted += upserted
                total_marked_deleted += marked_deleted

                waba_row = (
                    await self.db.execute(
                        select(WhatsAppBusinessAccount).where(
                            WhatsAppBusinessAccount.business_id == business_id,
                            WhatsAppBusinessAccount.waba_id == current_waba_id,
                            WhatsAppBusinessAccount.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if waba_row is not None:
                    waba_row.last_template_sync_at = now

            run.status = "completed"
            run.completed_at = datetime.now(timezone.utc)
            run.failure_reason = None
            await AuditLogService(self.db).write(
                action="whatsapp.templates.sync",
                resource_type="whatsapp_business_account",
                status="success",
                business_id=business_id,
                user_id=requested_by_user_id,
                actor_type="system" if requested_by_user_id is None else "user",
                actor_id=(str(requested_by_user_id) if requested_by_user_id else None),
                details={
                    "trigger": trigger,
                    "waba_ids": touched_wabas,
                    "templates_fetched": total_fetched,
                    "templates_upserted": total_upserted,
                    "templates_marked_deleted": total_marked_deleted,
                },
            )
            await OnboardingEventLedgerService(self.db).append(
                business_id=business_id,
                operation_id=f"template_sync_{run.id}",
                event_type="template_sync_success",
                event_status="success",
                merchant_user_id=requested_by_user_id,
                waba_id=(waba_id or (touched_wabas[0] if touched_wabas else None)),
                graph_api_endpoint=f"/{settings.META_GRAPH_API_VERSION}/{{waba_id}}/message_templates",
                graph_response_json={
                    "trigger": trigger,
                    "waba_ids": touched_wabas,
                    "templates_fetched": total_fetched,
                    "templates_upserted": total_upserted,
                    "templates_marked_deleted": total_marked_deleted,
                },
            )
            await self.db.commit()
            return TemplateSyncResult(
                business_id=business_id,
                run_id=run.id,
                status="completed",
                templates_fetched=total_fetched,
                templates_upserted=total_upserted,
                templates_marked_deleted=total_marked_deleted,
                waba_ids=touched_wabas,
                completed_at=run.completed_at or datetime.now(timezone.utc),
            )
        except Exception as exc:
            run.status = "failed"
            run.completed_at = datetime.now(timezone.utc)
            run.failure_reason = str(exc)
            graph_error_code = str(getattr(exc, "error_code", None) or "")
            graph_error_subcode = str(getattr(exc, "error_subcode", None) or "")
            await AuditLogService(self.db).write(
                action="whatsapp.templates.sync",
                resource_type="whatsapp_business_account",
                status="failed",
                business_id=business_id,
                user_id=requested_by_user_id,
                actor_type="system" if requested_by_user_id is None else "user",
                actor_id=(str(requested_by_user_id) if requested_by_user_id else None),
                details={
                    "trigger": trigger,
                    "waba_id": waba_id,
                    "reason": str(exc),
                    "graph_error_code": graph_error_code or None,
                    "graph_error_subcode": graph_error_subcode or None,
                },
            )
            await OnboardingEventLedgerService(self.db).append(
                business_id=business_id,
                operation_id=f"template_sync_{run.id}",
                event_type="template_sync_failed",
                event_status="failed",
                merchant_user_id=requested_by_user_id,
                waba_id=waba_id,
                graph_api_endpoint=f"/{settings.META_GRAPH_API_VERSION}/{{waba_id}}/message_templates",
                graph_error_code=graph_error_code or None,
                graph_error_subcode=graph_error_subcode or None,
                error_message=str(exc),
            )
            await self.db.commit()
            return TemplateSyncResult(
                business_id=business_id,
                run_id=run.id,
                status="failed",
                templates_fetched=0,
                templates_upserted=0,
                templates_marked_deleted=0,
                waba_ids=([waba_id] if waba_id else []),
                completed_at=run.completed_at or datetime.now(timezone.utc),
                failure_reason=str(exc),
            )

    async def _resolve_access_token(self, *, business_id: UUID) -> str:
        row = await self.db.execute(
            select(OAuthCredential)
            .where(
                OAuthCredential.business_id == business_id,
                OAuthCredential.provider == "whatsapp",
                OAuthCredential.environment == "live",
                OAuthCredential.revoked_at.is_(None),
                OAuthCredential.deleted_at.is_(None),
            )
            .order_by(OAuthCredential.created_at.desc())
            .limit(1)
        )
        credential = row.scalars().first()
        if credential is None:
            raise ForbiddenException("Missing active WhatsApp credential for template sync")
        granted_scopes = {str(scope).strip() for scope in (credential.scopes or []) if str(scope).strip()}
        if granted_scopes and "*" not in granted_scopes and "whatsapp_business_management" not in granted_scopes:
            raise ForbiddenException("Credential missing whatsapp_business_management scope")
        if credential.expires_at and credential.expires_at <= (datetime.now(timezone.utc) + timedelta(minutes=1)):
            raise ForbiddenException("WhatsApp credential is expired or near expiration")
        return token_crypto_service.decrypt(credential.access_token_ciphertext)

    async def _resolve_target_wabas(self, *, business_id: UUID, waba_id: str | None) -> list[str]:
        if waba_id:
            row = await self.db.execute(
                select(WhatsAppBusinessAccount.id).where(
                    WhatsAppBusinessAccount.business_id == business_id,
                    WhatsAppBusinessAccount.waba_id == waba_id,
                    WhatsAppBusinessAccount.deleted_at.is_(None),
                )
            )
            if row.scalar_one_or_none() is None:
                raise NotFoundException("WABA not found for this business")
            return [waba_id]
        rows = await self.db.execute(
            select(WhatsAppBusinessAccount.waba_id)
            .where(
                WhatsAppBusinessAccount.business_id == business_id,
                WhatsAppBusinessAccount.deleted_at.is_(None),
            )
            .order_by(WhatsAppBusinessAccount.created_at.desc())
        )
        wabas = [str(v) for v in rows.scalars().all() if str(v or "").strip()]
        if not wabas:
            raise NotFoundException("No WhatsApp Business Account linked for template sync")
        return wabas

    async def _fetch_all_templates_for_waba(self, *, token: str, waba_id: str) -> list[dict[str, Any]]:
        version = str(settings.META_GRAPH_API_VERSION or "v21.0").strip()
        fields = "id,name,status,category,language,components,rejected_reason,quality_score"
        next_url = f"{self.base_url}/{version}/{waba_id}/message_templates"
        params: dict[str, Any] | None = {"fields": fields, "limit": 100}
        headers = {"Authorization": f"Bearer {token}"}
        collected: list[dict[str, Any]] = []
        page_guard = 0
        async with httpx.AsyncClient(timeout=20.0) as client:
            while next_url:
                page_guard += 1
                if page_guard > 200:
                    raise TemplateGraphSyncError("Template pagination exceeded safety limit")
                response = await client.get(next_url, params=params, headers=headers)
                if response.status_code >= 400:
                    code = None
                    subcode = None
                    try:
                        err = (response.json() or {}).get("error") or {}
                        code = str(err.get("code")) if err.get("code") is not None else None
                        subcode = str(err.get("error_subcode")) if err.get("error_subcode") is not None else None
                    except Exception:
                        pass
                    raise TemplateGraphSyncError(
                        "Meta template fetch failed",
                        status_code=response.status_code,
                        error_code=code,
                        error_subcode=subcode,
                        response_body=response.text,
                    )
                payload = response.json() or {}
                data = payload.get("data") or []
                if isinstance(data, list):
                    collected.extend([x for x in data if isinstance(x, dict)])
                paging = payload.get("paging") or {}
                cursor = paging.get("next")
                next_url = str(cursor).strip() if cursor else ""
                params = None
        return collected

    async def _upsert_and_prune_waba_templates(
        self,
        *,
        business_id: UUID,
        waba_id: str,
        templates: list[dict[str, Any]],
        synced_at: datetime,
    ) -> tuple[int, int]:
        upserted = 0
        seen_keys: set[tuple[str, str]] = set()
        for raw in templates:
            name = str(raw.get("name") or "").strip()
            language_node = raw.get("language")
            if isinstance(language_node, dict):
                language = str(language_node.get("code") or "").strip()
            else:
                language = str(raw.get("language") or "").strip()
            if not name or not language:
                continue
            seen_keys.add((name, language))
            row = (
                await self.db.execute(
                    select(WhatsAppMessageTemplate).where(
                        WhatsAppMessageTemplate.business_id == business_id,
                        WhatsAppMessageTemplate.waba_id == waba_id,
                        WhatsAppMessageTemplate.name == name,
                        WhatsAppMessageTemplate.language == language,
                        WhatsAppMessageTemplate.deleted_at.is_(None),
                    )
                )
            ).scalars().first()
            if row is None:
                row = WhatsAppMessageTemplate(
                    business_id=business_id,
                    waba_id=waba_id,
                    name=name,
                    language=language,
                )
                self.db.add(row)
            row.meta_template_id = str(raw.get("id") or "").strip() or None
            row.category = str(raw.get("category") or "").strip().lower() or None
            row.status = str(raw.get("status") or "unknown").strip().lower()
            row.components_json = {
                "components": raw.get("components")
            } if isinstance(raw.get("components"), list) else {}
            row.rejection_reason = str(raw.get("rejected_reason") or "").strip() or None
            row.last_synced_at = synced_at
            if row.deleted_at is not None:
                row.deleted_at = None
            upserted += 1

        existing_rows = (
            await self.db.execute(
                select(WhatsAppMessageTemplate).where(
                    WhatsAppMessageTemplate.business_id == business_id,
                    WhatsAppMessageTemplate.waba_id == waba_id,
                    WhatsAppMessageTemplate.deleted_at.is_(None),
                )
            )
        ).scalars().all()
        marked_deleted = 0
        for row in existing_rows:
            key = (str(row.name or ""), str(row.language or ""))
            if key not in seen_keys:
                row.deleted_at = synced_at
                row.last_synced_at = synced_at
                marked_deleted += 1
        return upserted, marked_deleted
