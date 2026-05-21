from __future__ import annotations

import asyncio
import csv
import io
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy import and_, or_, select

from app.database import AsyncSessionLocal
from app.models.business_domains import Contact, ContactExportJob, OutboxEvent, QuerySnapshot, ConversationSavedView
from app.services.contact_segment_service import ContactSegmentService
from app.services.degradation_mode_service import should_defer_domain
from app.services.object_storage_service import object_storage_service

logger = logging.getLogger(__name__)


class ContactExportWorker:
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
            if should_defer_domain("exports"):
                await asyncio.sleep(max(2.0, self.poll_interval_seconds * 2))
                continue
            try:
                processed = await self._process_one()
                if not processed:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("contact_export_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _build_contacts_query_stmt(self, *, db, business_id, query_json: dict):
        stmt = select(Contact).where(
            Contact.business_id == business_id,
            Contact.deleted_at.is_(None),
        )
        search = query_json.get("search")
        tag = query_json.get("tag")
        opt_in_status = query_json.get("opt_in_status")
        suppressed = query_json.get("suppressed")
        segment_id = query_json.get("segment_id")
        if search:
            q = f"%{str(search).strip()}%"
            stmt = stmt.where(
                or_(
                    Contact.display_name.ilike(q),
                    Contact.email.ilike(q),
                    Contact.normalized_phone.ilike(q),
                    Contact.wa_id.ilike(q),
                )
            )
        if tag:
            stmt = stmt.where(Contact.tags.contains([str(tag).strip().lower()]))
        if opt_in_status:
            stmt = stmt.where(Contact.opt_in_status == str(opt_in_status).strip().lower())
        if suppressed is True:
            stmt = stmt.where(or_(Contact.blocked_at.is_not(None), Contact.unsubscribed_at.is_not(None)))
        elif suppressed is False:
            stmt = stmt.where(Contact.blocked_at.is_(None), Contact.unsubscribed_at.is_(None))
        if segment_id:
            try:
                seg_id = uuid.UUID(str(segment_id))
            except ValueError:
                seg_id = None
            if seg_id:
                seg = (
                    await db.execute(
                        select(ConversationSavedView).where(
                            ConversationSavedView.id == seg_id,
                            ConversationSavedView.business_id == business_id,
                            ConversationSavedView.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if seg and isinstance((seg.filters_json or {}).get("filters"), dict):
                    stmt = ContactSegmentService(db)._apply_filters(stmt, (seg.filters_json or {}).get("filters") or {})
        return stmt

    async def _process_one(self) -> bool:
        async with AsyncSessionLocal() as db:
            evt_row = await db.execute(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "contact_export.process_job",
                    OutboxEvent.status == "pending",
                    OutboxEvent.available_at <= datetime.now(timezone.utc),
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
            job_id_raw = payload.get("contact_export_job_id")
            if not job_id_raw:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True
            try:
                job_id = uuid.UUID(str(job_id_raw))
            except ValueError:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            job = (
                await db.execute(
                    select(ContactExportJob).where(
                        ContactExportJob.id == job_id,
                        ContactExportJob.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if job is None:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            try:
                job.status = "running"
                job.progress = 35
                await db.flush()

                ids_raw = job.selected_contact_ids_json or []
                selected_ids: list[uuid.UUID] = []
                for raw in ids_raw:
                    try:
                        selected_ids.append(uuid.UUID(str(raw)))
                    except ValueError:
                        continue

                stmt = select(Contact).where(
                    Contact.business_id == job.business_id,
                    Contact.deleted_at.is_(None),
                )

                if str(job.selection_mode or "").lower() == "all_matching_query" and job.query_snapshot_id is not None:
                    snapshot = (
                        await db.execute(
                            select(QuerySnapshot).where(
                                QuerySnapshot.id == job.query_snapshot_id,
                                QuerySnapshot.business_id == job.business_id,
                                QuerySnapshot.deleted_at.is_(None),
                            )
                        )
                    ).scalar_one_or_none()
                    if snapshot is not None:
                        stmt = await self._build_contacts_query_stmt(
                            db=db,
                            business_id=job.business_id,
                            query_json=(snapshot.query_json or {}),
                        )
                        excluded: list[uuid.UUID] = []
                        for raw in (job.excluded_contact_ids_json or []):
                            try:
                                excluded.append(uuid.UUID(str(raw)))
                            except ValueError:
                                continue
                        if excluded:
                            stmt = stmt.where(~Contact.id.in_(excluded))
                    elif selected_ids:
                        stmt = stmt.where(Contact.id.in_(selected_ids))
                elif selected_ids:
                    stmt = stmt.where(Contact.id.in_(selected_ids))

                rows = (await db.execute(stmt.order_by(Contact.updated_at.desc(), Contact.id.desc()))).scalars().all()
                columns = [str(c).strip() for c in (job.columns_json or []) if str(c).strip()]
                allowed_columns = {
                    "contact_id": lambda r: str(r.id),
                    "name": lambda r: r.display_name or "",
                    "email": lambda r: r.email or "",
                    "phone_e164": lambda r: r.normalized_phone or "",
                    "wa_id": lambda r: r.wa_id or "",
                    "opt_in_status": lambda r: r.opt_in_status or "",
                    "tags": lambda r: "|".join(r.tags or []),
                    "updated_at": lambda r: r.updated_at.isoformat() if r.updated_at else "",
                }
                if not columns:
                    columns = ["contact_id", "name", "email", "phone_e164", "wa_id", "opt_in_status", "tags", "updated_at"]
                columns = [c for c in columns if c in allowed_columns]
                if not columns:
                    columns = ["contact_id", "name", "email", "phone_e164", "wa_id", "opt_in_status", "tags", "updated_at"]

                buf = io.StringIO()
                writer = csv.writer(buf)
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([allowed_columns[c](row) for c in columns])

                key = object_storage_service.put_bytes(
                    namespace="contact_exports",
                    filename_hint=f"contacts_{job.business_id}.csv",
                    content=buf.getvalue().encode("utf-8"),
                )
                job.storage_key = key
                job.download_url = object_storage_service.build_url(key)
                job.total_rows = len(rows)
                job.progress = 100
                job.status = "completed"
                job.error_code = None
                job.error_message = None
                evt.status = "processed"
                evt.processed_at = datetime.now(timezone.utc)
            except Exception as exc:
                job.status = "failed"
                job.progress = 100
                job.error_code = "export_worker_error"
                job.error_message = str(exc)
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
            await db.commit()
            return True
