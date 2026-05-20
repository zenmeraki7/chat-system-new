from __future__ import annotations

import csv
import io
import re


class ContactHygieneService:
    @staticmethod
    def normalize_phone_e164(phone: str | None, default_country_code: str = "+1") -> str | None:
        if not phone:
            return None
        raw = re.sub(r"[^\d+]", "", phone.strip())
        if raw.startswith("+"):
            digits = "+" + re.sub(r"\D", "", raw)
        else:
            digits_only = re.sub(r"\D", "", raw)
            digits = f"{default_country_code}{digits_only}"
        if not re.match(r"^\+[1-9]\d{6,14}$", digits):
            return None
        return digits

    @staticmethod
    def validate_csv(csv_text: str) -> dict:
        reader = csv.DictReader(io.StringIO(csv_text))
        required = {"phone_e164"}
        missing = [r for r in required if r not in (reader.fieldnames or [])]
        if missing:
            return {"valid": False, "errors": [f"Missing required columns: {', '.join(missing)}"], "rows": 0}
        errors: list[str] = []
        rows = 0
        for idx, row in enumerate(reader, start=2):
            rows += 1
            normalized = ContactHygieneService.normalize_phone_e164(row.get("phone_e164"))
            if not normalized:
                errors.append(f"Row {idx}: invalid phone_e164")
        return {"valid": len(errors) == 0, "errors": errors[:100], "rows": rows}


contact_hygiene_service = ContactHygieneService()

