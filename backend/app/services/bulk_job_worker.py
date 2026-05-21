from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
import logging

from sqlalchemy import select

from app.database import AsyncSessionLocal
from app.models.business_domains import (
    OutboxEvent,
    JobOperation,
    Contact,
    SuppressionListEntry,
    QuerySnapshot,
    ConversationSavedView,
    CampaignRecipient,
    AuditLog,
)
from app.services.contact_segment_service import ContactSegmentService
from app.services.degradation_mode_service import should_defer_domain

logger = logging.getLogger(__name__)


class BulkJobWorker:
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
            if should_defer_domain("bulk"):
                await asyncio.sleep(max(2.0, self.poll_interval_seconds * 2))
                continue
            try:
                processed = await self._process_one()
                if not processed:
                    await asyncio.sleep(self.poll_interval_seconds)
            except Exception:
                logger.exception("bulk_job_worker_loop_failed")
                await asyncio.sleep(self.poll_interval_seconds)

    async def _resolve_ids(self, *, db, job: JobOperation) -> list[uuid.UUID]:
        payload = dict(job.payload_json or {})
        bulk_snapshot_id_raw = payload.get("bulk_action_snapshot_id")
        if bulk_snapshot_id_raw:
            try:
                bsid = uuid.UUID(str(bulk_snapshot_id_raw))
            except Exception:
                return []
            bsnap = (
                await db.execute(
                    select(QuerySnapshot).where(
                        QuerySnapshot.id == bsid,
                        QuerySnapshot.business_id == job.business_id,
                        QuerySnapshot.resource == "bulk_action",
                        QuerySnapshot.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if bsnap is None:
                return []
            out: list[uuid.UUID] = []
            for raw in ((bsnap.query_json or {}).get("selected_contact_ids") or []):
                try:
                    out.append(uuid.UUID(str(raw)))
                except Exception:
                    continue
            return out
        selection = payload.get("selection") or {}
        mode = str((selection or {}).get("mode") or "explicit").strip().lower()
        if mode == "explicit":
            ids = []
            for raw in (selection.get("ids") or []):
                try:
                    ids.append(uuid.UUID(str(raw)))
                except Exception:
                    continue
            return ids
        if mode == "all_matching_query":
            bulk_snapshot_id_raw = payload.get("bulk_action_snapshot_id")
            if bulk_snapshot_id_raw:
                try:
                    bsid = uuid.UUID(str(bulk_snapshot_id_raw))
                except Exception:
                    return []
                bsnap = (
                    await db.execute(
                        select(QuerySnapshot).where(
                            QuerySnapshot.id == bsid,
                            QuerySnapshot.business_id == job.business_id,
                            QuerySnapshot.resource == "bulk_action",
                            QuerySnapshot.deleted_at.is_(None),
                        )
                    )
                ).scalar_one_or_none()
                if bsnap is None:
                    return []
                out: list[uuid.UUID] = []
                for raw in ((bsnap.query_json or {}).get("selected_contact_ids") or []):
                    try:
                        out.append(uuid.UUID(str(raw)))
                    except Exception:
                        continue
                return out
            snapshot_id_raw = payload.get("query_snapshot_id")
            if not snapshot_id_raw:
                return []
            try:
                snapshot_id = uuid.UUID(str(snapshot_id_raw))
            except Exception:
                return []
            snap = (
                await db.execute(
                    select(QuerySnapshot).where(
                        QuerySnapshot.id == snapshot_id,
                        QuerySnapshot.business_id == job.business_id,
                        QuerySnapshot.deleted_at.is_(None),
                    )
                )
            ).scalar_one_or_none()
            if snap is None:
                return []
            q = snap.query_json or {}
            stmt = select(Contact.id).where(Contact.business_id == job.business_id, Contact.deleted_at.is_(None))
            search = str(q.get("search") or "").strip()
            if search:
                like = f"%{search}%"
                stmt = stmt.where((Contact.display_name.ilike(like)) | (Contact.email.ilike(like)) | (Contact.normalized_phone.ilike(like)) | (Contact.wa_id.ilike(like)))
            if q.get("opt_in_status"):
                stmt = stmt.where(Contact.opt_in_status == str(q.get("opt_in_status")).strip().lower())
            if q.get("tag"):
                stmt = stmt.where(Contact.tags.contains([str(q.get("tag")).strip().lower()]))
            if q.get("suppressed") is True:
                stmt = stmt.where((Contact.blocked_at.is_not(None)) | (Contact.unsubscribed_at.is_not(None)))
            elif q.get("suppressed") is False:
                stmt = stmt.where(Contact.blocked_at.is_(None), Contact.unsubscribed_at.is_(None))
            segment_id = q.get("segment_id")
            if segment_id:
                try:
                    seg_uuid = uuid.UUID(str(segment_id))
                except Exception:
                    seg_uuid = None
                if seg_uuid:
                    seg = (
                        await db.execute(
                            select(ConversationSavedView).where(
                                ConversationSavedView.id == seg_uuid,
                                ConversationSavedView.business_id == job.business_id,
                                ConversationSavedView.deleted_at.is_(None),
                            )
                        )
                    ).scalar_one_or_none()
                    if seg and isinstance((seg.filters_json or {}).get("filters"), dict):
                        stmt = ContactSegmentService(db)._apply_filters(stmt, (seg.filters_json or {}).get("filters") or {})
            excluded: list[uuid.UUID] = []
            for raw in (selection.get("excludedIds") or []):
                try:
                    excluded.append(uuid.UUID(str(raw)))
                except Exception:
                    continue
            if excluded:
                stmt = stmt.where(~Contact.id.in_(excluded))
            rows = (await db.execute(stmt.order_by(Contact.updated_at.desc(), Contact.id.desc()))).all()
            return [r[0] for r in rows]
        return []

    async def _process_one(self) -> bool:
        async with AsyncSessionLocal() as db:
            evt = (
                await db.execute(
                    select(OutboxEvent)
                    .where(
                        OutboxEvent.event_type == "bulk_job.process",
                        OutboxEvent.status == "pending",
                        OutboxEvent.available_at <= datetime.now(timezone.utc),
                        OutboxEvent.deleted_at.is_(None),
                    )
                    .order_by(OutboxEvent.created_at.asc(), OutboxEvent.id.asc())
                    .with_for_update(skip_locked=True)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if evt is None:
                return False
            evt.attempts = int(evt.attempts or 0) + 1
            job_id_raw = (evt.payload_json or {}).get("job_operation_id")
            try:
                job_id = uuid.UUID(str(job_id_raw))
            except Exception:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
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
            if job is None:
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                await db.commit()
                return True

            payload = dict(job.payload_json or {})
            action = str(payload.get("action") or "").strip().lower()
            dry_run = bool(payload.get("dry_run") is True)
            payload["progress"] = 20
            job.status = "running"
            try:
                if action == "bulk_suppress_contacts":
                    ids = await self._resolve_ids(db=db, job=job)
                    if dry_run:
                        payload["result"] = {"affected": len(ids), "dry_run": True}
                        payload["progress"] = 100
                        job.payload_json = payload
                        job.status = "completed"
                        evt.status = "processed"
                        evt.processed_at = datetime.now(timezone.utc)
                        await db.commit()
                        return True
                    count = 0
                    for cid in ids:
                        row = (
                            await db.execute(
                                select(Contact).where(Contact.id == cid, Contact.business_id == job.business_id, Contact.deleted_at.is_(None))
                            )
                        ).scalar_one_or_none()
                        if row is None:
                            continue
                        row.blocked_at = datetime.now(timezone.utc)
                        count += 1
                        if row.normalized_phone:
                            db.add(
                                SuppressionListEntry(
                                    business_id=job.business_id,
                                    channel_type="whatsapp",
                                    identity_hash=row.phone_hash or row.normalized_phone,
                                    reason="bulk_blocked",
                                    source="bulk_job_worker",
                                )
                            )
                    payload["result"] = {"affected": count}
                elif action == "bulk_tag_contacts":
                    tag = str(payload.get("tag") or "").strip().lower()
                    ids = await self._resolve_ids(db=db, job=job)
                    if dry_run:
                        payload["result"] = {"affected": len(ids), "tag": tag, "dry_run": True}
                        payload["progress"] = 100
                        job.payload_json = payload
                        job.status = "completed"
                        evt.status = "processed"
                        evt.processed_at = datetime.now(timezone.utc)
                        await db.commit()
                        return True
                    count = 0
                    for cid in ids:
                        row = (
                            await db.execute(
                                select(Contact).where(Contact.id == cid, Contact.business_id == job.business_id, Contact.deleted_at.is_(None))
                            )
                        ).scalar_one_or_none()
                        if row is None:
                            continue
                        tags = set(row.tags or [])
                        if tag:
                            tags.add(tag)
                        row.tags = sorted(tags)
                        count += 1
                    payload["result"] = {"affected": count, "tag": tag}
                elif action == "create_segment_from_query":
                    snapshot_id_raw = payload.get("query_snapshot_id")
                    snap = None
                    if snapshot_id_raw:
                        try:
                            snap = (
                                await db.execute(
                                    select(QuerySnapshot).where(
                                        QuerySnapshot.id == uuid.UUID(str(snapshot_id_raw)),
                                        QuerySnapshot.business_id == job.business_id,
                                        QuerySnapshot.deleted_at.is_(None),
                                    )
                                )
                            ).scalar_one_or_none()
                        except Exception:
                            snap = None
                    if snap is None:
                        raise ValueError("query_snapshot_required")
                    seg = ConversationSavedView(
                        business_id=job.business_id,
                        owner_user_id=job.actor_user_id,
                        name=f"contact_segment:auto_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
                        filters_json={"kind": "contact_segment", "display_name": "Bulk job segment", "filters": dict(snap.query_json or {})},
                        visibility="private",
                    )
                    db.add(seg)
                    await db.flush()
                    payload["result"] = {"segment_id": str(seg.id)}
                elif action == "retry_failed_recipients":
                    campaign_id_raw = payload.get("campaign_id")
                    if not campaign_id_raw:
                        raise ValueError("campaign_id_required")
                    campaign_id = uuid.UUID(str(campaign_id_raw))
                    rows = (
                        await db.execute(
                            select(CampaignRecipient).where(
                                CampaignRecipient.business_id == job.business_id,
                                CampaignRecipient.campaign_id == campaign_id,
                                CampaignRecipient.status == "failed",
                                CampaignRecipient.deleted_at.is_(None),
                            )
                        )
                    ).scalars().all()
                    for r in rows:
                        r.status = "queued"
                        r.failed_at = None
                        r.last_error_code = None
                        r.last_error_message = None
                    payload["result"] = {"affected": len(rows), "campaign_id": str(campaign_id)}
                elif action == "export_contacts":
                    payload["result"] = {"note": "use /contacts/export-jobs for export pipeline"}
                else:
                    raise ValueError("unsupported_action")

                payload["progress"] = 100
                job.payload_json = payload
                job.status = "completed"
                evt.status = "processed"
                evt.processed_at = datetime.now(timezone.utc)
                db.add(
                    AuditLog(
                        business_id=job.business_id,
                        user_id=job.actor_user_id,
                        actor_type="user",
                        actor_id=(str(job.actor_user_id) if job.actor_user_id else None),
                        operation_id=job.operation_id,
                        action="bulk_job.completed",
                        resource_type="bulk_job",
                        resource_id=str(job.id),
                        status="success",
                        details={
                            "action": action,
                            "result": payload.get("result"),
                            "selection": payload.get("selection"),
                            "query_snapshot_id": payload.get("query_snapshot_id"),
                        },
                    )
                )
            except Exception as exc:
                payload["progress"] = 100
                payload["result"] = {"error": str(exc)}
                job.payload_json = payload
                job.status = "failed"
                evt.status = "failed"
                evt.processed_at = datetime.now(timezone.utc)
                db.add(
                    AuditLog(
                        business_id=job.business_id,
                        user_id=job.actor_user_id,
                        actor_type="user",
                        actor_id=(str(job.actor_user_id) if job.actor_user_id else None),
                        operation_id=job.operation_id,
                        action="bulk_job.failed",
                        resource_type="bulk_job",
                        resource_id=str(job.id),
                        status="failed",
                        details={"action": action, "error": str(exc), "selection": payload.get("selection")},
                    )
                )
            await db.commit()
            return True
