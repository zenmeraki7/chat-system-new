from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.business_domains import Contact


class ContactDedupService:
    def __init__(self, db: AsyncSession):
        self.db = db

    @staticmethod
    def _richness(c: Contact) -> int:
        return sum(
            1
            for v in [
                c.normalized_phone,
                c.wa_id,
                c.email,
                c.display_name,
                c.last_message_at,
                c.last_seen_at,
            ]
            if v is not None
        )

    @staticmethod
    def _score_pair(a: Contact, b: Contact) -> tuple[int, list[str], bool]:
        score = 0
        reasons: list[str] = []
        if a.normalized_phone and b.normalized_phone and a.normalized_phone == b.normalized_phone:
            score += 60
            reasons.append("phone_match")
        if a.wa_id and b.wa_id and a.wa_id == b.wa_id:
            score += 55
            reasons.append("wa_id_match")
        if a.email and b.email and a.email.lower() == b.email.lower():
            score += 40
            reasons.append("email_match")
        safe_to_merge = "phone_match" in reasons or "wa_id_match" in reasons
        if ("phone_match" in reasons and "wa_id_match" not in reasons and a.wa_id and b.wa_id and a.wa_id != b.wa_id):
            safe_to_merge = False
            reasons.append("wa_id_conflict")
        return score, reasons, safe_to_merge

    async def suggest_duplicates(self, business_id: UUID, limit: int = 50) -> list[dict]:
        rows = await self.db.execute(
            select(Contact)
            .where(Contact.business_id == business_id, Contact.deleted_at.is_(None), Contact.status != "merged")
            .order_by(Contact.updated_at.desc())
            .limit(500)
        )
        contacts = rows.scalars().all()
        suggestions: list[dict] = []
        for i in range(len(contacts)):
            for j in range(i + 1, len(contacts)):
                a = contacts[i]
                b = contacts[j]
                score, reasons, safe_to_merge = self._score_pair(a, b)
                if score < 60:
                    continue
                source = a
                target = b
                if self._richness(a) > self._richness(b):
                    source = b
                    target = a
                suggestions.append(
                    {
                        "source_contact_id": source.id,
                        "target_contact_id": target.id,
                        "score": score,
                        "reasons": reasons,
                        "safe_to_merge": safe_to_merge,
                    }
                )
        suggestions.sort(key=lambda x: (x["score"], x["safe_to_merge"]), reverse=True)
        return suggestions[:limit]
