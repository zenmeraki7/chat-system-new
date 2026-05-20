import uuid
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, File, UploadFile
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.database import get_db
from app.models.business_domains import Contact, ContactSource, ContactMergeEvent, SuppressionListEntry, OutboxEvent
from app.models.business_domains import ConversationSavedView, ContactImportJob, ContactImportRow, ContactImportError
from app.models.business_domains import CampaignRecipient, CampaignRecipientEvent
from app.models.message import Message, MessageDirection
from app.repositories.contact_repo import ContactRepository
from app.schemas.contact import (
    ContactBlockRequest,
    ContactCSVValidationRequest,
    ContactCsvImportExecuteRequest,
    ContactDuplicateSuggestionResponse,
    ContactMergeRequest,
    ContactOptInRequest,
    ContactResponse,
    ContactSegmentResponse,
    ContactSegmentUpsertRequest,
    ContactUpdateRequest,
    ContactUpsertRequest,
)
from app.services.contact_dedup_service import ContactDedupService
from app.services.contact_hygiene_service import contact_hygiene_service
from app.services.contact_import_service import ContactImportService
from app.services.contact_import_service import ContactImportService
from app.services.contact_segment_service import ContactSegmentService

router = APIRouter(prefix="/contacts", tags=["Contacts"])


def _to_response(row) -> ContactResponse:
    eligible = row.opt_in_status == "opted_in" and row.blocked_at is None and row.unsubscribed_at is None and row.status == "active"
    return ContactResponse(
        id=row.id,
        phone_e164=row.normalized_phone,
        wa_id=row.wa_id,
        name=row.display_name,
        email=row.email,
        tags=row.tags or [],
        custom_attributes=row.custom_attributes or {},
        opt_in_status=row.opt_in_status,
        opt_in_source=row.opt_in_source,
        opt_in_timestamp=row.opt_in_timestamp,
        unsubscribed_at=row.unsubscribed_at,
        blocked_at=row.blocked_at,
        last_seen_at=row.last_seen_at,
        last_message_at=row.last_message_at,
        marketing_eligible=eligible,
    )


def _iso(ts):
    return ts.isoformat() if ts else None


async def _build_contact_record(db: AsyncSession, business_id, row: Contact) -> dict:
    cid = row.id
    latest_inbound_msg = (
        await db.execute(
            select(Message.created_at)
            .where(
                Message.business_id == business_id,
                Message.contact_id == cid,
                Message.deleted_at.is_(None),
                Message.direction == MessageDirection.INBOUND,
            )
            .order_by(Message.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    latest_campaign_receive = (
        await db.execute(
            select(CampaignRecipient.sent_at, CampaignRecipient.updated_at)
            .where(
                CampaignRecipient.business_id == business_id,
                CampaignRecipient.contact_id == cid,
                CampaignRecipient.deleted_at.is_(None),
            )
            .order_by(CampaignRecipient.sent_at.desc().nullslast(), CampaignRecipient.updated_at.desc(), CampaignRecipient.id.desc())
            .limit(1)
        )
    ).first()
    last_campaign_at = None
    if latest_campaign_receive is not None:
        sent_at, updated_at = latest_campaign_receive
        last_campaign_at = sent_at or updated_at

    suppression_rows = (
        await db.execute(
            select(SuppressionListEntry).where(
                SuppressionListEntry.business_id == business_id,
                SuppressionListEntry.deleted_at.is_(None),
                or_(
                    SuppressionListEntry.identity_hash == (row.phone_hash or ""),
                    SuppressionListEntry.identity_hash == (row.normalized_phone or ""),
                ),
            )
        )
    ).scalars().all()
    suppression_status = "active" if suppression_rows or row.blocked_at or row.unsubscribed_at else "clear"

    attrs = row.custom_attributes or {}
    return {
        "id": str(row.id),
        "phone_e164": row.normalized_phone,
        "wa_id": row.wa_id,
        "name": row.display_name,
        "email": row.email,
        "tags": row.tags or [],
        "custom_attributes": attrs,
        "opt_in_status": row.opt_in_status,
        "opt_in_source": row.opt_in_source,
        "opted_out_at": _iso(row.unsubscribed_at),
        "suppression_status": suppression_status,
        "last_message_at": _iso(row.last_message_at),
        "last_inbound_at": _iso(latest_inbound_msg),
        "last_campaign_at": _iso(last_campaign_at),
        "last_reply_at": _iso(latest_inbound_msg),
        "last_order_at": _iso(attrs.get("last_order_at")) if isinstance(attrs.get("last_order_at"), datetime) else attrs.get("last_order_at"),
        "last_click_at": _iso(attrs.get("last_click_at")) if isinstance(attrs.get("last_click_at"), datetime) else attrs.get("last_click_at"),
    }


@router.post("/import/validate", response_model=dict)
async def validate_contact_csv(
    payload: ContactCSVValidationRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
):
    del actor
    return contact_hygiene_service.validate_csv(payload.csv_text)


@router.post("/import/upload", response_model=dict)
async def upload_contact_csv(
    file: UploadFile = File(...),
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    content = await file.read()
    if not content:
        return {"status": "failed", "reason": "empty_file"}
    svc = ContactImportService(db)
    job = await svc.create_upload_job(
        business_id=actor.business.id,
        uploaded_by_user_id=actor.user.id,
        source_file_name=file.filename,
        file_bytes=content,
    )
    db.add(
        OutboxEvent(
            business_id=actor.business.id,
            event_type="contact_import.process_csv",
            payload_json={"import_job_id": str(job.id)},
            status="pending",
        )
    )
    await db.commit()
    return {"status": "accepted", "import_job_id": str(job.id)}


@router.post("", response_model=ContactResponse)
async def upsert_contact(
    payload: ContactUpsertRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    repo = ContactRepository(db)
    normalized = contact_hygiene_service.normalize_phone_e164(payload.phone_e164)
    row = await repo.upsert_contact(
        business_id=actor.business.id,
        phone_e164=normalized,
        wa_id=payload.wa_id,
        name=payload.name,
        email=(payload.email.strip().lower() if payload.email else None),
        tags=payload.tags,
        custom_attributes=payload.custom_attributes,
        source=payload.source,
    )
    await db.commit()
    return _to_response(row)


@router.get("", response_model=list[ContactResponse])
async def list_contacts(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await ContactRepository(db).list_for_business(actor.business.id, limit=200)
    return [_to_response(r) for r in rows]


@router.get("/crm/records", response_model=list[dict])
async def list_contact_crm_records(
    search: str | None = None,
    tag: str | None = None,
    opt_in_status: str | None = None,
    suppressed: bool | None = None,
    segment_id: str | None = None,
    limit: int = 200,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Contact).where(
        Contact.business_id == actor.business.id,
        Contact.deleted_at.is_(None),
    )
    if search:
        q = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                Contact.display_name.ilike(q),
                Contact.email.ilike(q),
                Contact.normalized_phone.ilike(q),
                Contact.wa_id.ilike(q),
            )
        )
    if tag and tag.strip():
        stmt = stmt.where(Contact.tags.contains([tag.strip().lower()]))
    if opt_in_status:
        stmt = stmt.where(Contact.opt_in_status == opt_in_status.strip().lower())
    if suppressed is True:
        stmt = stmt.where(or_(Contact.blocked_at.is_not(None), Contact.unsubscribed_at.is_not(None)))
    elif suppressed is False:
        stmt = stmt.where(Contact.blocked_at.is_(None), Contact.unsubscribed_at.is_(None))
    if segment_id:
        seg = (
            await db.execute(
                select(ConversationSavedView).where(
                    ConversationSavedView.id == uuid.UUID(segment_id),
                    ConversationSavedView.business_id == actor.business.id,
                    ConversationSavedView.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if seg and isinstance((seg.filters_json or {}).get("filters"), dict):
            stmt = ContactSegmentService(db)._apply_filters(stmt, (seg.filters_json or {}).get("filters") or {})
    rows = (await db.execute(stmt.order_by(Contact.updated_at.desc(), Contact.id.desc()).limit(max(1, min(limit, 1000))))).scalars().all()
    out: list[dict] = []
    for row in rows:
        out.append(await _build_contact_record(db, actor.business.id, row))
    return out


@router.get("/tags", response_model=list[dict])
async def list_contact_tags(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await ContactRepository(db).list_for_business(actor.business.id, limit=5000)
    counts: dict[str, int] = {}
    for row in rows:
        for t in (row.tags or []):
            k = str(t).strip().lower()
            if not k:
                continue
            counts[k] = int(counts.get(k, 0)) + 1
    return [{"tag": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


@router.get("/custom-fields", response_model=list[dict])
async def list_contact_custom_fields(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await ContactRepository(db).list_for_business(actor.business.id, limit=5000)
    counts: dict[str, int] = {}
    for row in rows:
        attrs = row.custom_attributes or {}
        if not isinstance(attrs, dict):
            continue
        for k, v in attrs.items():
            if v is None:
                continue
            key = str(k).strip()
            if not key:
                continue
            counts[key] = int(counts.get(key, 0)) + 1
    return [{"field": k, "count": v} for k, v in sorted(counts.items(), key=lambda x: (-x[1], x[0]))]


@router.get("/{contact_id}/record", response_model=dict)
async def get_contact_record(
    contact_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).get_by_id_for_business(actor.business.id, uuid.UUID(contact_id))
    if not row:
        return {"status": "not_found"}
    return await _build_contact_record(db, actor.business.id, row)


@router.patch("/{contact_id}", response_model=ContactResponse)
async def update_contact(
    contact_id: str,
    payload: ContactUpdateRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).get_by_id_for_business(actor.business.id, uuid.UUID(contact_id))
    if not row:
        from app.core.exceptions import NotFoundException
        raise NotFoundException("Contact not found")
    if payload.name is not None:
        row.display_name = str(payload.name).strip() or None
    if payload.email is not None:
        row.email = (str(payload.email).strip().lower() or None)
    if payload.tags is not None:
        row.tags = sorted({str(t).strip().lower() for t in payload.tags if str(t).strip()})
    if payload.custom_attributes is not None:
        row.custom_attributes = dict(payload.custom_attributes)
    row.last_seen_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(row)
    return _to_response(row)


@router.post("/merge", response_model=dict)
async def merge_contacts(
    payload: ContactMergeRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).merge_contacts(
        business_id=actor.business.id,
        source_contact_id=payload.source_contact_id,
        target_contact_id=payload.target_contact_id,
        merged_by_user_id=actor.user.id,
    )
    await db.commit()
    return {"status": "ok", "target_contact_id": str(row.id) if row else None}


@router.post("/{contact_id}/opt-in", response_model=ContactResponse)
async def set_opt_in(
    contact_id: str,
    payload: ContactOptInRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).set_opt_in(
        business_id=actor.business.id,
        contact_id=uuid.UUID(contact_id),
        status=payload.opt_in_status,
        source=payload.opt_in_source,
    )
    await db.commit()
    return _to_response(row)


@router.post("/{contact_id}/block", response_model=ContactResponse)
async def set_block(
    contact_id: str,
    payload: ContactBlockRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).set_blocked(
        business_id=actor.business.id,
        contact_id=uuid.UUID(contact_id),
        blocked=payload.blocked,
    )
    if row and payload.blocked and row.normalized_phone:
        db.add(
            SuppressionListEntry(
                business_id=actor.business.id,
                channel_type="whatsapp",
                identity_hash=row.phone_hash or row.normalized_phone,
                reason="blocked",
                source="contacts_api",
            )
        )
    await db.commit()
    return _to_response(row)


@router.get("/{contact_id}/timeline", response_model=dict)
async def contact_timeline(
    contact_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    import uuid
    cid = uuid.UUID(contact_id)
    sources = await db.execute(
        select(ContactSource).where(ContactSource.business_id == actor.business.id, ContactSource.contact_id == cid)
    )
    merges = await db.execute(
        select(ContactMergeEvent).where(
            ContactMergeEvent.business_id == actor.business.id,
            (ContactMergeEvent.source_contact_id == cid) | (ContactMergeEvent.target_contact_id == cid),
        )
    )
    message_rows = (
        await db.execute(
            select(Message.created_at, Message.direction, Message.message_kind, Message.content_text)
            .where(
                Message.business_id == actor.business.id,
                Message.contact_id == cid,
                Message.deleted_at.is_(None),
            )
            .order_by(Message.created_at.desc())
            .limit(30)
        )
    ).all()
    campaign_rows = (
        await db.execute(
            select(
                CampaignRecipient.id,
                CampaignRecipient.status,
                CampaignRecipient.sent_at,
                CampaignRecipient.delivered_at,
                CampaignRecipient.read_at,
                CampaignRecipient.replied_at,
                CampaignRecipient.failed_at,
                CampaignRecipient.last_error_code,
            )
            .where(
                CampaignRecipient.business_id == actor.business.id,
                CampaignRecipient.contact_id == cid,
                CampaignRecipient.deleted_at.is_(None),
            )
            .order_by(CampaignRecipient.updated_at.desc())
            .limit(30)
        )
    ).all()
    return {
        "sources": [{"source": s.source, "last_seen_at": s.last_seen_at.isoformat() if s.last_seen_at else None} for s in sources.scalars().all()],
        "merge_events": [
            {
                "source_contact_id": str(m.source_contact_id),
                "target_contact_id": str(m.target_contact_id),
                "created_at": m.created_at.isoformat(),
            }
            for m in merges.scalars().all()
        ],
        "message_events": [
            {
                "created_at": _iso(ca),
                "direction": str(direction.value if hasattr(direction, "value") else direction),
                "message_kind": kind,
                "content_preview": (content or "")[:160],
            }
            for ca, direction, kind, content in message_rows
        ],
        "campaign_events": [
            {
                "campaign_recipient_id": str(rid),
                "status": status,
                "sent_at": _iso(sent_at),
                "delivered_at": _iso(delivered_at),
                "read_at": _iso(read_at),
                "replied_at": _iso(replied_at),
                "failed_at": _iso(failed_at),
                "last_error_code": err,
            }
            for rid, status, sent_at, delivered_at, read_at, replied_at, failed_at, err in campaign_rows
        ],
    }


@router.get("/{contact_id}/import-history", response_model=dict)
async def contact_import_history(
    contact_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).get_by_id_for_business(actor.business.id, uuid.UUID(contact_id))
    if not row:
        return {"status": "not_found"}
    jobs = (
        await db.execute(
            select(ContactImportJob).where(
                ContactImportJob.business_id == actor.business.id,
                ContactImportJob.deleted_at.is_(None),
            ).order_by(ContactImportJob.created_at.desc()).limit(50)
        )
    ).scalars().all()
    job_ids = [j.id for j in jobs]
    if not job_ids:
        return {"contact_id": str(row.id), "imports": []}
    import_rows = (
        await db.execute(
            select(ContactImportRow).where(
                ContactImportRow.import_job_id.in_(job_ids),
                ContactImportRow.deleted_at.is_(None),
            )
        )
    ).scalars().all()
    by_job = {j.id: j for j in jobs}
    matches: list[dict] = []
    for r in import_rows:
        payload = r.payload_json or {}
        phone = str(payload.get("phone_e164") or "").strip()
        wa_id = str(payload.get("wa_id") or "").strip()
        if (row.normalized_phone and phone == row.normalized_phone) or (row.wa_id and wa_id and wa_id == row.wa_id):
            j = by_job.get(r.import_job_id)
            if not j:
                continue
            matches.append(
                {
                    "job_id": str(j.id),
                    "source_file_name": j.source_file_name,
                    "job_status": j.status,
                    "row_number": r.row_number,
                    "row_status": r.status,
                    "imported_at": _iso(r.updated_at),
                }
            )
    matches.sort(key=lambda x: x["imported_at"] or "", reverse=True)
    return {"contact_id": str(row.id), "imports": matches}


@router.get("/{contact_id}/suppression-history", response_model=dict)
async def contact_suppression_history(
    contact_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).get_by_id_for_business(actor.business.id, uuid.UUID(contact_id))
    if not row:
        return {"status": "not_found"}

    outbox_events = (
        await db.execute(
            select(OutboxEvent).where(
                OutboxEvent.business_id == actor.business.id,
                OutboxEvent.event_type == "contact.suppression.history",
                OutboxEvent.deleted_at.is_(None),
            ).order_by(OutboxEvent.created_at.desc()).limit(500)
        )
    ).scalars().all()
    events: list[dict] = []
    for e in outbox_events:
        p = e.payload_json or {}
        if str(p.get("contact_id") or "") != str(row.id):
            continue
        events.append(
            {
                "reason": p.get("reason"),
                "source": p.get("source"),
                "event_type": e.event_type,
                "created_at": _iso(e.created_at),
                "payload_json": p,
            }
        )

    rec_events = (
        await db.execute(
            select(CampaignRecipientEvent).where(
                CampaignRecipientEvent.business_id == actor.business.id,
                CampaignRecipientEvent.event_type == "campaign_recipient.suppression_applied",
                CampaignRecipientEvent.deleted_at.is_(None),
            ).order_by(CampaignRecipientEvent.created_at.desc()).limit(1000)
        )
    ).scalars().all()
    for re in rec_events:
        rec = (
            await db.execute(
                select(CampaignRecipient).where(
                    CampaignRecipient.id == re.campaign_recipient_id,
                    CampaignRecipient.contact_id == row.id,
                    CampaignRecipient.business_id == actor.business.id,
                    CampaignRecipient.deleted_at.is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
        if rec is None:
            continue
        payload = re.payload_json or {}
        for reason in payload.get("suppression_reasons") or []:
            events.append(
                {
                    "reason": reason,
                    "source": "campaign_recipient_freeze",
                    "event_type": re.event_type,
                    "campaign_id": str(re.campaign_id),
                    "created_at": _iso(re.created_at),
                    "payload_json": payload,
                }
            )

    events.sort(key=lambda x: x.get("created_at") or "", reverse=True)
    return {"contact_id": str(row.id), "history": events}


@router.post("/segments", response_model=ContactSegmentResponse)
async def upsert_contact_segment(
    payload: ContactSegmentUpsertRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    name = payload.name.strip()
    key = f"contact_segment:{name.lower()}"
    row_q = await db.execute(
        select(ConversationSavedView).where(
            ConversationSavedView.business_id == actor.business.id,
            ConversationSavedView.name == key,
            ConversationSavedView.deleted_at.is_(None),
        )
    )
    row = row_q.scalar_one_or_none()
    filters = payload.filters.model_dump()
    if row is None:
        row = ConversationSavedView(
            business_id=actor.business.id,
            owner_user_id=actor.user.id,
            name=key,
            filters_json={"kind": "contact_segment", "display_name": name, "filters": filters},
            visibility=payload.visibility,
        )
        db.add(row)
    else:
        row.filters_json = {"kind": "contact_segment", "display_name": name, "filters": filters}
        row.visibility = payload.visibility
    await db.flush()
    count = await ContactSegmentService(db).count_contacts(actor.business.id, filters)
    await db.commit()
    return ContactSegmentResponse(
        segment_id=str(row.id),
        name=name,
        visibility=row.visibility,
        filters=filters,
        count=count,
    )


@router.get("/segments", response_model=list[ContactSegmentResponse])
async def list_contact_segments(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = await db.execute(
        select(ConversationSavedView).where(
            ConversationSavedView.business_id == actor.business.id,
            ConversationSavedView.name.like("contact_segment:%"),
            ConversationSavedView.deleted_at.is_(None),
        )
    )
    svc = ContactSegmentService(db)
    out: list[ContactSegmentResponse] = []
    for row in rows.scalars().all():
        meta = row.filters_json or {}
        filters = (meta.get("filters") or {})
        count = await svc.count_contacts(actor.business.id, filters)
        out.append(
            ContactSegmentResponse(
                segment_id=str(row.id),
                name=meta.get("display_name") or row.name.replace("contact_segment:", "", 1),
                visibility=row.visibility,
                filters=filters,
                count=count,
            )
        )
    return out


@router.post("/import/execute", response_model=dict)
async def execute_contact_csv_import(
    payload: ContactCsvImportExecuteRequest,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    return await ContactImportService(db).execute_csv_import(
        business_id=actor.business.id,
        uploaded_by_user_id=actor.user.id,
        csv_text=payload.csv_text,
        source_file_name=payload.source_file_name,
    )


@router.get("/import/jobs/{job_id}", response_model=dict)
async def get_contact_import_job(
    job_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    jid = uuid.UUID(job_id)
    job = (
        await db.execute(
            select(ContactImportJob).where(
                ContactImportJob.id == jid,
                ContactImportJob.business_id == actor.business.id,
                ContactImportJob.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not job:
        return {"status": "not_found"}
    rows = (
        await db.execute(
            select(ContactImportRow).where(ContactImportRow.import_job_id == jid, ContactImportRow.deleted_at.is_(None))
        )
    ).scalars().all()
    row_ids = [r.id for r in rows]
    errors = []
    if row_ids:
        errors = (
            await db.execute(
                select(ContactImportError).where(ContactImportError.import_row_id.in_(row_ids), ContactImportError.deleted_at.is_(None))
            )
        ).scalars().all()
    return {
        "job_id": str(job.id),
        "status": job.status,
        "source_file_name": job.source_file_name,
        "rows_total": len(rows),
        "rows_imported": len([r for r in rows if r.status == "imported"]),
        "rows_error": len([r for r in rows if r.status == "error"]),
        "errors": [{"import_row_id": str(e.import_row_id), "error_code": e.error_code, "error_message": e.error_message} for e in errors],
    }


@router.get("/duplicates/suggestions", response_model=list[ContactDuplicateSuggestionResponse])
async def get_duplicate_suggestions(
    limit: int = 50,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    suggestions = await ContactDedupService(db).suggest_duplicates(actor.business.id, limit=max(1, min(limit, 200)))
    return [ContactDuplicateSuggestionResponse(**row) for row in suggestions]
