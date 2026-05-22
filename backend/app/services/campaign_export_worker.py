from __future__ import annotations

import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import Campaign, CampaignRecipient, JobOperation, OutboxEvent
from app.services.csv_safety import escape_csv_cell
from app.services.object_storage_service import object_storage_service

logger = logging.getLogger(__name__)

MAX_RETRY_ATTEMPTS = 5
BASE_RETRY_DELAY_SECONDS = 5
MAX_RETRY_DELAY_SECONDS = 300


class CampaignExportWorkerError(Exception):
    def __init__(self, code: str, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable


class CampaignExportWorker:
    def __init__(self, *, poll_interval_seconds: float = 1.0) -> None:
        self.poll_interval_seconds = poll_interval_seconds
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        if self._task is not None:
            return
        self._stop.clear()
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is None:
            return
        self._stop.set()
        await self._task
        self._task = None

    async def _run(self) -> None:
        while not self._stop.is_set():
            try:
                processed = await self._process_one()
                if not processed:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("campaign_export_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _process_one(self) -> bool:
        now = datetime.now(timezone.utc)
        async with AsyncSessionLocal() as db:
            evt_row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "campaign_export.process_job",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= now,
                    OutboxEvent.deleted_at.is_(None),
                )
                .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            evt = evt_row.scalar_one_or_none()
            if evt is None:
                return False
            evt.attempts = int(evt.attempts or 0) + 1

            payload = evt.payload_json or {}
            job_id_raw = payload.get("job_operation_id")
            campaign_id_raw = payload.get("campaign_id")
            if not job_id_raw or not campaign_id_raw:
                self._mark_event_dead_letter(
                    evt,
                    error_code="CAMPAIGN_EXPORT_INVALID_PAYLOAD",
                    error_message="Missing job_operation_id or campaign_id",
                    now=now,
                )
                await db.commit()
                return True

            try:
                job_id = UUID(str(job_id_raw))
                campaign_id = UUID(str(campaign_id_raw))
            except ValueError:
                self._mark_event_dead_letter(
                    evt,
                    error_code="CAMPAIGN_EXPORT_INVALID_PAYLOAD",
                    error_message="Invalid UUID in job payload",
                    now=now,
                )
                await db.commit()
                return True

            job = (
                await db.execute(
                    select(JobOperation).where(
                        JobOperation.id == job_id,
                        JobOperation.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            campaign = (
                await db.execute(
                    select(Campaign).where(
                        Campaign.id == campaign_id,
                        Campaign.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if job is None or campaign is None:
                self._mark_event_dead_letter(
                    evt,
                    error_code="CAMPAIGN_EXPORT_ENTITY_NOT_FOUND",
                    error_message="Job operation or campaign not found",
                    now=now,
                )
                await db.commit()
                return True

            try:
                job.status = "running"
                job.payload_json = {
                    **(job.payload_json or {}),
                    "status": "running",
                    "progress": 35,
                    "attempts": int(evt.attempts or 0),
                    "maxAttempts": MAX_RETRY_ATTEMPTS,
                    "errorCode": None,
                    "errorMessage": None,
                }
                await db.flush()

                buf = io.StringIO()
                writer = csv.writer(buf)
                header = [
                    "campaign_id",
                    "recipient_id",
                    "phone_e164",
                    "status",
                    "eligibility_status",
                    "eligibility_reason",
                    "provider_message_id",
                    "attempt_count",
                    "sent_at",
                    "delivered_at",
                    "read_at",
                    "failed_at",
                    "last_error_code",
                    "last_error_message",
                ]
                writer.writerow([escape_csv_cell(c) for c in header])
                row_count = 0
                stream = await db.stream(
                    select(CampaignRecipient).where(
                        CampaignRecipient.business_id == campaign.business_id,
                        CampaignRecipient.campaign_id == campaign.id,
                        CampaignRecipient.deleted_at.is_(None),
                    ).order_by(CampaignRecipient.created_at.asc(), CampaignRecipient.id.asc()).execution_options(yield_per=500)
                )
                async for r in stream.scalars():
                    writer.writerow(
                        [escape_csv_cell(v) for v in [
                            str(campaign.id),
                            str(r.id),
                            r.phone_e164,
                            r.status,
                            r.eligibility_status,
                            r.eligibility_reason or "",
                            r.provider_message_id or "",
                            int(r.attempt_count or 0),
                            r.sent_at.isoformat() if r.sent_at else "",
                            r.delivered_at.isoformat() if r.delivered_at else "",
                            r.read_at.isoformat() if r.read_at else "",
                            r.failed_at.isoformat() if r.failed_at else "",
                            r.last_error_code or "",
                            r.last_error_message or "",
                        ]]
                    )
                    row_count += 1
                content = buf.getvalue().encode("utf-8")
                key = object_storage_service.put_bytes(
                    namespace="campaign_exports",
                    filename_hint=f"campaign_{campaign.id}.csv",
                    content=content,
                )
                job.status = "completed"
                job.payload_json = {
                    **(job.payload_json or {}),
                    "campaign_id": str(campaign.id),
                    "status": "completed",
                    "progress": 100,
                    "download_url": object_storage_service.build_url(key),
                    "storage_key": key,
                    "rows": row_count,
                    "attempts": int(evt.attempts or 0),
                    "maxAttempts": MAX_RETRY_ATTEMPTS,
                    "errorCode": None,
                    "errorMessage": None,
                }
                evt.status = "processed"
                evt.processed_at = datetime.now(timezone.utc)
            except Exception as exc:
                error_code, error_message, retryable = self._classify_error(exc)
                attempts = int(evt.attempts or 0)
                terminal_failure = (not retryable) or attempts >= MAX_RETRY_ATTEMPTS
                job.status = "failed" if terminal_failure else "pending"
                job.payload_json = {
                    **(job.payload_json or {}),
                    "campaign_id": str(campaign.id),
                    "status": "failed" if terminal_failure else "pending",
                    "progress": 100 if terminal_failure else 35,
                    "attempts": attempts,
                    "maxAttempts": MAX_RETRY_ATTEMPTS,
                    "errorCode": error_code,
                    "errorMessage": error_message,
                    "retryable": retryable,
                    "deadLettered": terminal_failure,
                }
                evt.status = "failed" if terminal_failure else "pending"
                evt.processed_at = datetime.now(timezone.utc) if terminal_failure else None
                if not terminal_failure:
                    evt.available_at = datetime.now(timezone.utc) + self._retry_delay(attempts)
            await db.commit()
            return True

    def _classify_error(self, exc: Exception) -> tuple[str, str, bool]:
        if isinstance(exc, CampaignExportWorkerError):
            return exc.code, exc.message, exc.retryable
        return "CAMPAIGN_EXPORT_WORKER_ERROR", (str(exc) or "Unhandled campaign export error"), True

    def _retry_delay(self, attempts: int) -> timedelta:
        exponent = max(0, attempts - 1)
        seconds = min(MAX_RETRY_DELAY_SECONDS, BASE_RETRY_DELAY_SECONDS * (2 ** exponent))
        return timedelta(seconds=seconds)

    def _mark_event_dead_letter(self, evt: OutboxEvent, *, error_code: str, error_message: str, now: datetime) -> None:
        evt.status = "failed"
        evt.processed_at = now
        evt.payload_json = {
            **(evt.payload_json or {}),
            "errorCode": error_code,
            "errorMessage": error_message,
            "deadLettered": True,
            "attempts": int(evt.attempts or 0),
            "maxAttempts": MAX_RETRY_ATTEMPTS,
        }
