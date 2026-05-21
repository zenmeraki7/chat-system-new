import uuid
import json
import hashlib
import base64
import hmac
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, Depends, File, UploadFile, HTTPException, Request
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentActor, require_permissions
from app.database import get_db
from app.models.business_domains import Contact, ContactSource, ContactMergeEvent, SuppressionListEntry, OutboxEvent, QuerySnapshot, ContactExportJob, AuditLog, JobOperation, BusinessDashboardStat
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
from app.services.contact_segment_service import ContactSegmentService
from app.config import settings
from app.services.table_registry import validate_table_query, get_table_config
from app.services.query_cost_service import classify_table_query, classify_bulk_action
from app.services.data_freshness_service import freshness_live_db, freshness_snapshot

router = APIRouter(prefix="/contacts", tags=["Contacts"])
CONTACT_TABLE_ALLOWED_SORTS = {"updated_at", "created_at"}
CONTACT_TABLE_MAX_LIMIT = 1000
QUERY_SNAPSHOT_TTL_SECONDS = 1800
SENSITIVE_COLUMN_PERMISSIONS = {
    "phone_e164": "contacts:columns:phone",
    "email": "contacts:columns:email",
    "custom_attributes": "contacts:columns:attributes",
    "actual_cost": "campaigns:columns:cost",
    "revenue": "analytics:columns:revenue",
    "campaign_errors": "campaigns:columns:errors",
}


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


def _normalize_contact_query_payload(*, search: str | None, tag: str | None, opt_in_status: str | None, suppressed: bool | None, segment_id: str | None, sort_by: str, sort_dir: str) -> dict:
    return {
        "search": (search or "").strip() or None,
        "tag": (tag or "").strip().lower() or None,
        "opt_in_status": (opt_in_status or "").strip().lower() or None,
        "suppressed": suppressed if suppressed is not None else None,
        "segment_id": str(segment_id).strip() if segment_id else None,
        "sort_by": "updated_at" if sort_by == "updated_at" else "created_at",
        "sort_dir": "asc" if str(sort_dir).lower() == "asc" else "desc",
    }


def _contact_query_hash(*, business_id, query_payload: dict) -> str:
    canonical = json.dumps({"business_id": str(business_id), "query": query_payload}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _validate_contact_table_query_contract(*, sort_by: str, sort_dir: str, limit: int) -> tuple[str, str, int]:
    normalized_sort_by = str(sort_by or "").strip().lower()
    if normalized_sort_by in {"name", "phone_e164", "last_message_at"}:
        normalized_sort_by = "updated_at"
    return validate_table_query(
        table="contacts",
        sort_by=normalized_sort_by,
        sort_dir=sort_dir,
        limit=min(int(limit), CONTACT_TABLE_MAX_LIMIT),
        filters={},
    )


def _encode_signed_contact_cursor(*, business_id, sort_by: str, sort_dir: str, cursor_key: datetime, cursor_id: uuid.UUID) -> str:
    payload = {
        "business_id": str(business_id),
        "sort_by": sort_by,
        "sort_dir": sort_dir,
        "cursor_key": cursor_key.astimezone(timezone.utc).isoformat(),
        "cursor_id": str(cursor_id),
    }
    payload_raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    signature = hmac.new(settings.SECRET_KEY.encode("utf-8"), payload_raw, hashlib.sha256).hexdigest().encode("utf-8")
    return (
        base64.urlsafe_b64encode(payload_raw).decode("utf-8")
        + "."
        + base64.urlsafe_b64encode(signature).decode("utf-8")
    )


def _decode_signed_contact_cursor(*, token: str, business_id, sort_by: str, sort_dir: str) -> tuple[datetime, uuid.UUID] | None:
    try:
        payload_enc, sig_enc = token.split(".", 1)
        payload_raw = base64.urlsafe_b64decode(payload_enc.encode("utf-8"))
        given_sig = base64.urlsafe_b64decode(sig_enc.encode("utf-8"))
        expected_sig = hmac.new(settings.SECRET_KEY.encode("utf-8"), payload_raw, hashlib.sha256).hexdigest().encode("utf-8")
        if not hmac.compare_digest(given_sig, expected_sig):
            return None
        payload = json.loads(payload_raw.decode("utf-8"))
        if str(payload.get("business_id")) != str(business_id):
            return None
        if str(payload.get("sort_by")) != sort_by or str(payload.get("sort_dir")) != sort_dir:
            return None
        key = datetime.fromisoformat(str(payload.get("cursor_key")))
        if key.tzinfo is None:
            key = key.replace(tzinfo=timezone.utc)
        cid = uuid.UUID(str(payload.get("cursor_id")))
        return key.astimezone(timezone.utc), cid
    except Exception:
        return None


def _selection_ids_from_payload(payload: dict) -> list[str]:
    sel = payload.get("selection") or {}
    if not isinstance(sel, dict):
        return []
    mode = str(sel.get("mode") or "").strip().lower()
    if mode != "explicit":
        return []
    ids = sel.get("ids") or []
    if not isinstance(ids, list):
        return []
    out: list[str] = []
    for raw in ids:
        value = str(raw or "").strip()
        if value:
            out.append(value)
    return out


async def _fetch_query_snapshot_for_selection(*, payload: dict, actor: CurrentActor, db: AsyncSession) -> QuerySnapshot | None:
    selection = payload.get("selection") or {}
    if not isinstance(selection, dict):
        return None
    snapshot_id_raw = (
        payload.get("query_snapshot_id")
        or payload.get("querySnapshotId")
        or selection.get("query_snapshot_id")
        or selection.get("querySnapshotId")
    )
    if not snapshot_id_raw:
        return None
    try:
        snapshot_id = uuid.UUID(str(snapshot_id_raw))
    except ValueError:
        return None
    snapshot = (
        await db.execute(
            select(QuerySnapshot).where(
                QuerySnapshot.id == snapshot_id,
                QuerySnapshot.business_id == actor.business.id,
                QuerySnapshot.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if snapshot is None:
        return None
    if snapshot.expires_at is not None and snapshot.expires_at <= datetime.now(timezone.utc):
        return None
    if str(snapshot.status or "").lower() != "active":
        return None
    return snapshot


async def _build_contacts_query_stmt(
    *,
    db: AsyncSession,
    business_id,
    search: str | None,
    tag: str | None,
    opt_in_status: str | None,
    suppressed: bool | None,
    segment_id: str | None,
):
    stmt = select(Contact).where(
        Contact.business_id == business_id,
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
                    ConversationSavedView.business_id == business_id,
                    ConversationSavedView.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if seg and isinstance((seg.filters_json or {}).get("filters"), dict):
            stmt = ContactSegmentService(db)._apply_filters(stmt, (seg.filters_json or {}).get("filters") or {})
    return stmt


async def _resolve_selection_contact_ids(*, payload: dict, actor: CurrentActor, db: AsyncSession) -> list[uuid.UUID]:
    bulk_snapshot_id_raw = payload.get("bulk_action_snapshot_id") or payload.get("bulkActionSnapshotId")
    if bulk_snapshot_id_raw:
        try:
            bsid = uuid.UUID(str(bulk_snapshot_id_raw))
        except ValueError:
            return []
        snap = (
            await db.execute(
                select(QuerySnapshot).where(
                    QuerySnapshot.id == bsid,
                    QuerySnapshot.business_id == actor.business.id,
                    QuerySnapshot.resource == "bulk_action",
                    QuerySnapshot.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if snap is None:
            return []
        frozen = snap.query_json or {}
        out: list[uuid.UUID] = []
        for raw in (frozen.get("selected_contact_ids") or []):
            try:
                out.append(uuid.UUID(str(raw)))
            except ValueError:
                continue
        return out

    selection = payload.get("selection") or {}
    if not isinstance(selection, dict):
        return []
    mode = str(selection.get("mode") or "").strip().lower()
    if mode == "explicit":
        values = selection.get("ids") or []
        if not isinstance(values, list):
            return []
        out: list[uuid.UUID] = []
        for raw in values:
            value = str(raw or "").strip()
            if not value:
                continue
            try:
                out.append(uuid.UUID(value))
            except ValueError:
                continue
        return out
    if mode == "all_matching_query":
        snapshot = await _fetch_query_snapshot_for_selection(payload=payload, actor=actor, db=db)
        if snapshot is None:
            return []
        normalized = snapshot.query_json or {}
        expected_hash = str(snapshot.query_hash or "").strip()
        provided_hash = str(payload.get("queryHash") or selection.get("queryHash") or "").strip()
        if provided_hash and provided_hash != expected_hash:
            return []
        stmt = await _build_contacts_query_stmt(
            db=db,
            business_id=actor.business.id,
            search=normalized.get("search"),
            tag=normalized.get("tag"),
            opt_in_status=normalized.get("opt_in_status"),
            suppressed=normalized.get("suppressed"),
            segment_id=normalized.get("segment_id"),
        )
        excluded_raw = selection.get("excludedIds") or []
        excluded: list[uuid.UUID] = []
        if isinstance(excluded_raw, list):
            for raw in excluded_raw:
                value = str(raw or "").strip()
                if not value:
                    continue
                try:
                    excluded.append(uuid.UUID(value))
                except ValueError:
                    continue
        if excluded:
            stmt = stmt.where(~Contact.id.in_(excluded))
        rows = (await db.execute(stmt.with_only_columns(Contact.id).order_by(Contact.updated_at.desc(), Contact.id.desc()))).all()
        return [row[0] for row in rows]
    return []


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


def _can_view_column(actor: CurrentActor, column: str) -> bool:
    if "*" in actor.permissions:
        return True
    required = SENSITIVE_COLUMN_PERMISSIONS.get(column)
    if required is None:
        return True
    return required in actor.permissions


def _project_contact_record_for_actor(actor: CurrentActor, record: dict) -> dict:
    out = dict(record)
    if not _can_view_column(actor, "phone_e164"):
        out["phone_e164"] = None
    if not _can_view_column(actor, "email"):
        out["email"] = None
    if not _can_view_column(actor, "custom_attributes"):
        out["custom_attributes"] = {}
    return out


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


@router.get("/crm/records", response_model=dict)
async def list_contact_crm_records(
    search: str | None = None,
    tag: str | None = None,
    opt_in_status: str | None = None,
    suppressed: bool | None = None,
    segment_id: str | None = None,
    cursor: str | None = None,
    sort_by: str = "updated_at",
    sort_dir: str = "desc",
    limit: int = 200,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    sort_by, sort_dir, normalized_limit = validate_table_query(
        table="contacts",
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        filters={"tag": tag, "opt_in_status": opt_in_status, "suppressed": suppressed, "segment_id": segment_id, "search": search},
    )
    normalized_query = _normalize_contact_query_payload(
        search=search,
        tag=tag,
        opt_in_status=opt_in_status,
        suppressed=suppressed,
        segment_id=segment_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    applied_query_hash = _contact_query_hash(business_id=actor.business.id, query_payload=normalized_query)
    query_risk = classify_table_query(
        table="contacts",
        sort_by=sort_by,
        limit=normalized_limit,
        filters={"search": search, "tag": tag, "opt_in_status": opt_in_status, "suppressed": suppressed},
    )

    stmt = await _build_contacts_query_stmt(
        db=db,
        business_id=actor.business.id,
        search=normalized_query.get("search"),
        tag=normalized_query.get("tag"),
        opt_in_status=normalized_query.get("opt_in_status"),
        suppressed=normalized_query.get("suppressed"),
        segment_id=normalized_query.get("segment_id"),
    )
    sort_key = Contact.updated_at if sort_by == "updated_at" else Contact.created_at
    sort_desc = str(sort_dir).lower() != "asc"
    if cursor:
        parsed = _decode_signed_contact_cursor(
            token=cursor,
            business_id=actor.business.id,
            sort_by=sort_by,
            sort_dir=sort_dir,
        )
        if parsed is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        cursor_key, cursor_id = parsed
        if sort_desc:
            stmt = stmt.where(or_(sort_key < cursor_key, and_(sort_key == cursor_key, Contact.id < cursor_id)))
        else:
            stmt = stmt.where(or_(sort_key > cursor_key, and_(sort_key == cursor_key, Contact.id > cursor_id)))

    total_stmt = select(func.count()).select_from(stmt.subquery())
    total = int((await db.execute(total_stmt)).scalar_one() or 0)
    order_primary = sort_key.desc() if sort_desc else sort_key.asc()
    order_secondary = Contact.id.desc() if sort_desc else Contact.id.asc()
    rows = (await db.execute(stmt.order_by(order_primary, order_secondary).limit(normalized_limit + 1))).scalars().all()
    page_rows = rows[: normalized_limit]
    next_cursor = None
    if len(rows) > normalized_limit and page_rows:
        last_row = page_rows[-1]
        cursor_key = last_row.updated_at if sort_by == "updated_at" else last_row.created_at
        if cursor_key is not None:
            next_cursor = _encode_signed_contact_cursor(
                business_id=actor.business.id,
                sort_by=sort_by,
                sort_dir=sort_dir,
                cursor_key=cursor_key,
                cursor_id=last_row.id,
            )
    out: list[dict] = []
    for row in page_rows:
        out.append(_project_contact_record_for_actor(actor, await _build_contact_record(db, actor.business.id, row)))
    return {
        "items": out,
        "next_cursor": next_cursor,
        "total": total,
        "applied_query_hash": applied_query_hash,
        "query_risk_class": query_risk.risk_class,
        "query_risk_reasons": query_risk.reasons,
        "freshness": freshness_live_db(),
    }


@router.post("/query-snapshots", response_model=dict)
async def create_contact_query_snapshot(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    query = payload.get("query") or {}
    if not isinstance(query, dict):
        raise HTTPException(status_code=400, detail="query object is required")
    try:
        snapshot_limit = int(query.get("limit") or 100)
    except Exception:
        snapshot_limit = 100
    sort_by, sort_dir, _ = _validate_contact_table_query_contract(
        sort_by=query.get("sort_by") or "updated_at",
        sort_dir=query.get("sort_dir") or "desc",
        limit=snapshot_limit,
    )
    normalized_query = _normalize_contact_query_payload(
        search=query.get("search"),
        tag=query.get("tag"),
        opt_in_status=query.get("opt_in_status"),
        suppressed=query.get("suppressed"),
        segment_id=query.get("segment_id"),
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    query_hash = _contact_query_hash(business_id=actor.business.id, query_payload=normalized_query)
    existing = (
        await db.execute(
            select(QuerySnapshot).where(
                QuerySnapshot.business_id == actor.business.id,
                QuerySnapshot.resource == "contacts",
                QuerySnapshot.query_hash == query_hash,
                QuerySnapshot.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=QUERY_SNAPSHOT_TTL_SECONDS)
    if existing is None:
        existing = QuerySnapshot(
            business_id=actor.business.id,
            resource="contacts",
            query_hash=query_hash,
            query_json=normalized_query,
            status="active",
            expires_at=expires_at,
            created_by_user_id=actor.user.id,
        )
        db.add(existing)
    else:
        existing.query_json = normalized_query
        existing.status = "active"
        existing.expires_at = expires_at
    await db.commit()
    await db.refresh(existing)
    return {
        "query_snapshot_id": str(existing.id),
        "query_hash": existing.query_hash,
        "resource": existing.resource,
        "expires_at": existing.expires_at.isoformat() if existing.expires_at else None,
        "freshness": freshness_snapshot(generated_at=existing.updated_at, max_lag_seconds=QUERY_SNAPSHOT_TTL_SECONDS),
    }


@router.post("/saved-views", response_model=dict)
async def upsert_contact_saved_view(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    name = str(payload.get("name") or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")
    query = payload.get("query") or {}
    if not isinstance(query, dict):
        raise HTTPException(status_code=400, detail="query object is required")
    sort_by, sort_dir, lim = validate_table_query(
        table="contacts",
        sort_by=query.get("sort_by") or "updated_at",
        sort_dir=query.get("sort_dir") or "desc",
        limit=int(query.get("limit") or 100),
        filters={
            "tag": query.get("tag"),
            "opt_in_status": query.get("opt_in_status"),
            "suppressed": query.get("suppressed"),
            "segment_id": query.get("segment_id"),
            "search": query.get("search"),
        },
    )
    normalized = _normalize_contact_query_payload(
        search=query.get("search"),
        tag=query.get("tag"),
        opt_in_status=query.get("opt_in_status"),
        suppressed=query.get("suppressed"),
        segment_id=query.get("segment_id"),
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    normalized["limit"] = lim
    key = f"table_view:contacts:{name.lower()}"
    row = (
        await db.execute(
            select(ConversationSavedView).where(
                ConversationSavedView.business_id == actor.business.id,
                ConversationSavedView.name == key,
                ConversationSavedView.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ConversationSavedView(
            business_id=actor.business.id,
            owner_user_id=actor.user.id,
            name=key,
            visibility="private",
            filters_json={"kind": "table_view", "table": "contacts", "name": name, "query": normalized},
        )
        db.add(row)
    else:
        row.filters_json = {"kind": "table_view", "table": "contacts", "name": name, "query": normalized}
    await db.commit()
    await db.refresh(row)
    return {"saved_view_id": str(row.id), "name": name, "table": "contacts"}


@router.get("/saved-views", response_model=list[dict])
async def list_contact_saved_views(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(ConversationSavedView).where(
                ConversationSavedView.business_id == actor.business.id,
                ConversationSavedView.name.like("table_view:contacts:%"),
                ConversationSavedView.deleted_at.is_(None),
            ).order_by(ConversationSavedView.updated_at.desc(), ConversationSavedView.id.desc())
        )
    ).scalars().all()
    return [
        {
            "saved_view_id": str(row.id),
            "name": (row.filters_json or {}).get("name") or row.name,
            "query": (row.filters_json or {}).get("query") or {},
            "visibility": row.visibility,
        }
        for row in rows
    ]


@router.post("/query-preview", response_model=dict)
async def preview_contact_query_impact(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    query = payload.get("query") or {}
    if not isinstance(query, dict):
        raise HTTPException(status_code=400, detail="query object is required")
    sort_by, sort_dir, _ = validate_table_query(
        table="contacts",
        sort_by=query.get("sort_by") or "updated_at",
        sort_dir=query.get("sort_dir") or "desc",
        limit=int(query.get("limit") or 100),
        filters={
            "tag": query.get("tag"),
            "opt_in_status": query.get("opt_in_status"),
            "suppressed": query.get("suppressed"),
            "segment_id": query.get("segment_id"),
            "search": query.get("search"),
        },
    )
    normalized = _normalize_contact_query_payload(
        search=query.get("search"),
        tag=query.get("tag"),
        opt_in_status=query.get("opt_in_status"),
        suppressed=query.get("suppressed"),
        segment_id=query.get("segment_id"),
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    stmt = await _build_contacts_query_stmt(
        db=db,
        business_id=actor.business.id,
        search=normalized.get("search"),
        tag=normalized.get("tag"),
        opt_in_status=normalized.get("opt_in_status"),
        suppressed=normalized.get("suppressed"),
        segment_id=normalized.get("segment_id"),
    )
    approx = int((await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one() or 0)
    query_risk = classify_table_query(
        table="contacts",
        sort_by=sort_by,
        limit=int(query.get("limit") or 100),
        filters={
            "search": query.get("search"),
            "tag": query.get("tag"),
            "opt_in_status": query.get("opt_in_status"),
            "suppressed": query.get("suppressed"),
        },
    )
    return {
        "table": "contacts",
        "approx_affected": approx,
        "message": f"This will affect approximately {approx:,} contacts.",
        "query_risk_class": query_risk.risk_class,
        "query_risk_reasons": query_risk.reasons,
    }


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


@router.get("/approx-counts", response_model=dict)
async def get_contact_approx_counts(
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    latest = (
        await db.execute(
            select(BusinessDashboardStat).where(
                BusinessDashboardStat.business_id == actor.business.id,
                BusinessDashboardStat.deleted_at.is_(None),
            ).order_by(BusinessDashboardStat.date_bucket.desc(), BusinessDashboardStat.id.desc()).limit(1)
        )
    ).scalar_one_or_none()
    metrics = dict((latest.metrics_json or {})) if latest is not None else {}
    contacts_total = metrics.get("contacts_total_approx")
    opted_in = metrics.get("contacts_opted_in_approx")
    failed_recipients = metrics.get("failed_recipients_approx")
    return {
        "contacts_total_approx": contacts_total if contacts_total is not None else "unknown",
        "contacts_opted_in_approx": opted_in if opted_in is not None else "unknown",
        "failed_recipients_approx": failed_recipients if failed_recipients is not None else "unknown",
        "as_of": latest.date_bucket.isoformat() if latest is not None else None,
        "source": "business_dashboard_stats",
    }


@router.post("/export-jobs", response_model=dict)
async def create_contact_export_job(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    selection = payload.get("selection") or {}
    if not isinstance(selection, dict):
        selection = {"mode": "explicit", "ids": []}
    selection_mode = str(selection.get("mode") or "explicit").strip().lower()
    if selection_mode not in {"explicit", "all_matching_query"}:
        raise HTTPException(status_code=400, detail="Unsupported selection.mode")
    resolved_selection_ids = await _resolve_selection_contact_ids(payload=payload, actor=actor, db=db)
    explicit_legacy_ids = _selection_ids_from_payload(payload)
    if not resolved_selection_ids and explicit_legacy_ids:
        resolved_selection_ids = [uuid.UUID(x) for x in explicit_legacy_ids]
    excluded_ids = [str(x).strip() for x in (selection.get("excludedIds") or []) if str(x).strip()]
    query_snapshot = await _fetch_query_snapshot_for_selection(payload=payload, actor=actor, db=db)
    export_columns = payload.get("columns") or [
        "contact_id",
        "name",
        "email",
        "phone_e164",
        "wa_id",
        "opt_in_status",
        "tags",
        "updated_at",
    ]
    if not isinstance(export_columns, list) or not export_columns:
        export_columns = ["contact_id", "name", "email", "phone_e164", "wa_id", "opt_in_status", "tags", "updated_at"]
    table_cfg = get_table_config("contacts")
    allowed_export_set = set(table_cfg.exportable_columns)
    filtered_columns: list[str] = []
    for c in export_columns:
        col = str(c).strip()
        if not col:
            continue
        if col not in allowed_export_set:
            continue
        if col in {"phone_e164"} and not _can_view_column(actor, "phone_e164"):
            continue
        if col in {"email"} and not _can_view_column(actor, "email"):
            continue
        if col in {"custom_attributes"} and not _can_view_column(actor, "custom_attributes"):
            continue
        filtered_columns.append(col)
    if not filtered_columns:
        filtered_columns = ["contact_id", "name", "opt_in_status", "updated_at"]
    approx_affected = len(resolved_selection_ids)
    action_risk = classify_bulk_action(
        action="export_contacts",
        approx_affected=approx_affected,
        includes_sensitive_columns=any(c in {"phone_e164", "email"} for c in filtered_columns),
        has_opt_in_filter=bool((payload.get("query") or {}).get("opt_in_status")),
    )
    if action_risk.risk_class == "BLOCKED":
        raise HTTPException(status_code=400, detail={"code": "query_risk_blocked", "reasons": action_risk.reasons})

    job = ContactExportJob(
        business_id=actor.business.id,
        requested_by_user_id=actor.user.id,
        query_snapshot_id=(query_snapshot.id if query_snapshot else None),
        selection_mode=selection_mode,
        selected_contact_ids_json=[str(x) for x in resolved_selection_ids],
        excluded_contact_ids_json=excluded_ids,
        columns_json=filtered_columns,
        status="pending",
        progress=5,
    )
    db.add(job)
    await db.flush()
    db.add(
        OutboxEvent(
            business_id=actor.business.id,
            event_type="contact_export.process_job",
            operation_id=f"contact_export:{job.id}",
            payload_json={"contact_export_job_id": str(job.id)},
            status="pending",
        )
    )
    await db.commit()
    await db.refresh(job)
    return {
        "job_id": str(job.id),
        "status": str(job.status),
        "progress": int(job.progress or 0),
        "query_risk_class": action_risk.risk_class,
        "query_risk_reasons": action_risk.reasons,
        "approx_affected": approx_affected,
    }


@router.post("/bulk-jobs", response_model=dict)
async def create_contact_bulk_job(
    payload: dict,
    request: Request,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    action = str(payload.get("action") or "").strip().lower()
    dry_run = bool(payload.get("dry_run") is True or payload.get("dryRun") is True)
    bulk_action_snapshot_id = str(payload.get("bulk_action_snapshot_id") or payload.get("bulkActionSnapshotId") or "").strip()
    allowed = {"bulk_tag_contacts", "bulk_suppress_contacts", "create_segment_from_query", "export_contacts", "retry_failed_recipients"}
    if action not in allowed:
        raise HTTPException(status_code=400, detail="Unsupported bulk job action")
    if not bulk_action_snapshot_id:
        raise HTTPException(status_code=400, detail="bulk_action_snapshot_id is required")
    try:
        bulk_snapshot_uuid = uuid.UUID(bulk_action_snapshot_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="bulk_action_snapshot_id is invalid")
    bulk_snapshot = (
        await db.execute(
            select(QuerySnapshot).where(
                QuerySnapshot.id == bulk_snapshot_uuid,
                QuerySnapshot.business_id == actor.business.id,
                QuerySnapshot.resource == "bulk_action",
                QuerySnapshot.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if bulk_snapshot is None:
        raise HTTPException(status_code=404, detail="bulk_action_snapshot not found")
    if bulk_snapshot.expires_at is not None and bulk_snapshot.expires_at <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="bulk_action_snapshot stale; regenerate snapshot")
    approx_affected = len(await _resolve_selection_contact_ids(payload=payload, actor=actor, db=db))
    frozen_meta = dict(bulk_snapshot.query_json or {})
    action_risk = classify_bulk_action(
        action=action,
        approx_affected=approx_affected,
        includes_sensitive_columns=bool(frozen_meta.get("includes_sensitive_columns") is True),
        has_opt_in_filter=bool(frozen_meta.get("has_opt_in_filter") is True),
    )
    if action_risk.risk_class == "BLOCKED":
        raise HTTPException(status_code=400, detail={"code": "query_risk_blocked", "reasons": action_risk.reasons})
    operation_id = f"bulk_job:{action}:{actor.business.id}:{datetime.now(timezone.utc).isoformat()}"
    job = JobOperation(
        business_id=actor.business.id,
        operation_id=operation_id,
        actor_user_id=actor.user.id,
        idempotency_key=operation_id,
        payload_json={
            "action": action,
            "selection": frozen_meta.get("selection") or {},
            "bulk_action_snapshot_id": str(bulk_snapshot.id),
            "query_snapshot_id": frozen_meta.get("query_snapshot_id"),
            "query_hash": frozen_meta.get("query_hash"),
            "query": frozen_meta.get("query"),
            "tag": payload.get("tag"),
            "campaign_id": payload.get("campaign_id") or payload.get("campaignId"),
            "dry_run": dry_run,
            "status": "pending",
            "progress": 0,
            "result": None,
        },
        status="pending",
    )
    db.add(job)
    await db.flush()
    db.add(
        OutboxEvent(
            business_id=actor.business.id,
            event_type="bulk_job.process",
            operation_id=operation_id,
            payload_json={"job_operation_id": str(job.id)},
            status="pending",
        )
    )
    db.add(
        AuditLog(
            business_id=actor.business.id,
            user_id=actor.user.id,
            actor_type="user",
            actor_id=str(actor.user.id),
            operation_id=operation_id,
            action="bulk_job.created",
            resource_type="bulk_job",
            resource_id=str(job.id),
            status="success",
            ip_address=(request.client.host if request.client else None),
            user_agent=request.headers.get("user-agent"),
            details={
                "action": action,
                "selection": frozen_meta.get("selection") or {},
                "bulk_action_snapshot_id": str(bulk_snapshot.id),
                "query_snapshot_id": frozen_meta.get("query_snapshot_id"),
            },
        )
    )
    await db.commit()
    return {
        "job_id": str(job.id),
        "status": "pending",
        "progress": 0,
        "query_risk_class": action_risk.risk_class,
        "query_risk_reasons": action_risk.reasons,
        "approx_affected": approx_affected,
    }


@router.get("/bulk-jobs/{job_id}", response_model=dict)
async def get_contact_bulk_job(
    job_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(JobOperation).where(
                JobOperation.id == uuid.UUID(job_id),
                JobOperation.business_id == actor.business.id,
                JobOperation.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return {"job_id": job_id, "status": "not_found"}
    p = dict(row.payload_json or {})
    return {"job_id": str(row.id), "status": row.status, "progress": int(p.get("progress") or 0), "result": p.get("result"), "action": p.get("action")}


@router.post("/bulk-action-snapshots", response_model=dict)
async def create_bulk_action_snapshot(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    action = str(payload.get("action") or "").strip().lower()
    if not action:
        raise HTTPException(status_code=400, detail="action is required")
    selection = payload.get("selection") or {}
    if not isinstance(selection, dict):
        selection = {"mode": "explicit", "ids": []}
    query = payload.get("query") or {}
    if not isinstance(query, dict):
        query = {}
    query_snapshot_id = payload.get("query_snapshot_id") or payload.get("querySnapshotId") or selection.get("query_snapshot_id") or selection.get("querySnapshotId")
    resolver_payload = {
        "selection": selection,
        "query": query,
        "query_snapshot_id": query_snapshot_id,
        "queryHash": payload.get("queryHash") or selection.get("queryHash"),
    }
    resolved_ids = await _resolve_selection_contact_ids(payload=resolver_payload, actor=actor, db=db)
    selected_ids = [str(x) for x in resolved_ids]
    approx_affected = len(selected_ids)
    includes_sensitive_columns = bool(any(str(c).strip() in {"phone_e164", "email", "custom_attributes"} for c in (payload.get("columns") or [])))
    has_opt_in_filter = bool(query.get("opt_in_status"))
    risk = classify_bulk_action(
        action=action,
        approx_affected=approx_affected,
        includes_sensitive_columns=includes_sensitive_columns,
        has_opt_in_filter=has_opt_in_filter,
    )
    if risk.risk_class == "BLOCKED":
        raise HTTPException(status_code=400, detail={"code": "query_risk_blocked", "reasons": risk.reasons})
    snapshot_payload = {
        "action": action,
        "selection": selection,
        "query": query,
        "query_hash": payload.get("queryHash") or selection.get("queryHash"),
        "query_snapshot_id": str(query_snapshot_id) if query_snapshot_id else None,
        "selected_contact_ids": selected_ids,
        "excluded_ids": selection.get("excludedIds") or [],
        "includes_sensitive_columns": includes_sensitive_columns,
        "has_opt_in_filter": has_opt_in_filter,
        "risk_class": risk.risk_class,
        "risk_reasons": risk.reasons,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    canonical = json.dumps({"business_id": str(actor.business.id), "resource": "bulk_action", "payload": snapshot_payload}, sort_keys=True, separators=(",", ":"))
    query_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=QUERY_SNAPSHOT_TTL_SECONDS)
    row = QuerySnapshot(
        business_id=actor.business.id,
        resource="bulk_action",
        query_hash=query_hash,
        query_json=snapshot_payload,
        status="active",
        expires_at=expires_at,
        created_by_user_id=actor.user.id,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return {
        "bulk_action_snapshot_id": str(row.id),
        "action": action,
        "query_hash": row.query_hash,
        "approx_affected": approx_affected,
        "risk_class": risk.risk_class,
        "risk_reasons": risk.reasons,
        "expires_at": row.expires_at.isoformat() if row.expires_at else None,
    }


@router.get("/export-jobs/{job_id}", response_model=dict)
async def get_contact_export_job(
    job_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    job = (
        await db.execute(
            select(ContactExportJob).where(
                ContactExportJob.id == uuid.UUID(job_id),
                ContactExportJob.business_id == actor.business.id,
                ContactExportJob.deleted_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if not job:
        return {"job_id": job_id, "status": "not_found"}
    return {
        "job_id": str(job.id),
        "status": str(job.status or "pending"),
        "progress": int(job.progress or 0),
        "download_url": job.download_url,
        "storage_key": job.storage_key,
        "rows": int(job.total_rows or 0),
        "error_code": job.error_code,
        "error_message": job.error_message,
    }


@router.post("/bulk-suppress", response_model=dict)
async def bulk_suppress_contacts(
    payload: dict,
    actor: CurrentActor = Depends(require_permissions("contacts:write")),
    db: AsyncSession = Depends(get_db),
):
    dry_run = bool(payload.get("dry_run") is True or payload.get("dryRun") is True)
    contact_ids = await _resolve_selection_contact_ids(payload=payload, actor=actor, db=db)
    if not contact_ids:
        return {"status": "no_selection", "suppressed_count": 0}
    unique_ids = list(dict.fromkeys(contact_ids))
    if dry_run:
        return {"status": "dry_run", "suppressed_count": len(unique_ids), "dry_run": True}
    repo = ContactRepository(db)
    suppressed_count = 0
    for cid in unique_ids:
        row = await repo.set_blocked(
            business_id=actor.business.id,
            contact_id=cid,
            blocked=True,
        )
        if row is None:
            continue
        suppressed_count += 1
        if row.normalized_phone:
            db.add(
                SuppressionListEntry(
                    business_id=actor.business.id,
                    channel_type="whatsapp",
                    identity_hash=row.phone_hash or row.normalized_phone,
                    reason="bulk_blocked",
                    source="contacts_bulk_api",
                )
            )
    await db.commit()
    return {"status": "ok", "suppressed_count": suppressed_count}


@router.get("/{contact_id}/record", response_model=dict)
async def get_contact_record(
    contact_id: str,
    actor: CurrentActor = Depends(require_permissions("contacts:read")),
    db: AsyncSession = Depends(get_db),
):
    row = await ContactRepository(db).get_by_id_for_business(actor.business.id, uuid.UUID(contact_id))
    if not row:
        return {"status": "not_found"}
    return _project_contact_record_for_actor(actor, await _build_contact_record(db, actor.business.id, row))


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
