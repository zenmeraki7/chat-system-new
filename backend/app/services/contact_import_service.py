from __future__ import annotations

import csv
import io
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import ContactImportJob, ContactImportRow, ContactImportError
from app.repositories.contact_repo import ContactRepository
from app.services.contact_hygiene_service import contact_hygiene_service
from app.services.object_storage_service import object_storage_service


class ContactImportService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.repo = ContactRepository(db)

    async def execute_csv_import(
        self,
        business_id: UUID,
        uploaded_by_user_id: UUID | None,
        csv_text: str,
        source_file_name: str | None,
        existing_job: ContactImportJob | None = None,
    ):
        job = existing_job
        if job is None:
            job = ContactImportJob(
                business_id=business_id,
                uploaded_by_user_id=uploaded_by_user_id,
                status="processing",
                source_file_name=source_file_name,
            )
            self.db.add(job)
            await self.db.flush()
        else:
            job.status = "processing"

        reader = csv.DictReader(io.StringIO(csv_text))
        required = {"phone_e164"}
        missing = [r for r in required if r not in (reader.fieldnames or [])]
        if missing:
            job.status = "failed"
            await self.db.flush()
            return {"job_id": str(job.id), "status": job.status, "created": 0, "updated": 0, "errors": [f"Missing required columns: {', '.join(missing)}"]}

        created = 0
        updated = 0
        error_count = 0
        for idx, row in enumerate(reader, start=2):
            import_row = ContactImportRow(
                import_job_id=job.id,
                row_number=idx,
                payload_json=dict(row),
                status="pending",
            )
            self.db.add(import_row)
            await self.db.flush()
            phone = contact_hygiene_service.normalize_phone_e164(row.get("phone_e164"))
            if not phone:
                import_row.status = "error"
                self.db.add(
                    ContactImportError(
                        import_row_id=import_row.id,
                        error_code="invalid_phone_e164",
                        error_message="phone_e164 is missing or invalid",
                    )
                )
                error_count += 1
                continue
            existing = await self.repo.find_by_phone_or_wa(business_id, phone, (row.get("wa_id") or None))
            total_spend_raw = (row.get("total_spend") or "").strip()
            total_spend_value = None
            if total_spend_raw:
                try:
                    normalized_spend = total_spend_raw.replace(",", "")
                    total_spend_value = float(normalized_spend)
                except ValueError:
                    total_spend_value = None
            custom_attributes = {
                "city": (row.get("city") or "").strip() or None,
                "last_product": (row.get("last_product") or "").strip() or None,
                "last_purchase_at": (row.get("last_purchase_at") or "").strip() or None,
                "total_spend": total_spend_value,
                "total_spend_raw": total_spend_raw or None,
            }
            custom_attributes = {k: v for k, v in custom_attributes.items() if v is not None}
            await self.repo.upsert_contact(
                business_id=business_id,
                phone_e164=phone,
                wa_id=(row.get("wa_id") or None),
                name=(row.get("name") or None),
                email=((row.get("email") or "").strip().lower() or None),
                tags=[t.strip().lower() for t in (row.get("tags") or "").split(",") if t.strip()],
                custom_attributes=custom_attributes,
                source="csv_import",
            )
            import_row.status = "imported"
            if existing is None:
                created += 1
            else:
                updated += 1

        job.status = "completed_with_errors" if error_count > 0 else "completed"
        await self.db.commit()
        return {
            "job_id": str(job.id),
            "status": job.status,
            "created": created,
            "updated": updated,
            "error_rows": error_count,
        }

    async def create_upload_job(self, *, business_id: UUID, uploaded_by_user_id: UUID, source_file_name: str | None, file_bytes: bytes) -> ContactImportJob:
        storage_key = object_storage_service.put_bytes(
            namespace="contact-imports",
            filename_hint=source_file_name or "contacts.csv",
            content=file_bytes,
        )
        job = ContactImportJob(
            business_id=business_id,
            uploaded_by_user_id=uploaded_by_user_id,
            status="uploaded",
            source_file_name=source_file_name,
            storage_key=storage_key,
        )
        self.db.add(job)
        await self.db.flush()
        return job

    async def process_import_job(self, import_job_id: UUID) -> dict:
        job = (
            await self.db.execute(
                select(ContactImportJob).where(
                    ContactImportJob.id == import_job_id,
                    ContactImportJob.deleted_at.is_(None),
                )
            )
        ).scalar_one_or_none()
        if not job:
            return {"status": "not_found"}
        if not job.storage_key:
            job.status = "failed"
            await self.db.commit()
            return {"status": "failed", "reason": "missing_storage_key"}
        csv_text = object_storage_service.get_text(job.storage_key)
        job.status = "processing"
        await self.db.flush()
        result = await self.execute_csv_import(
            business_id=job.business_id,
            uploaded_by_user_id=job.uploaded_by_user_id,
            csv_text=csv_text,
            source_file_name=job.source_file_name,
            existing_job=job,
        )
        return result
