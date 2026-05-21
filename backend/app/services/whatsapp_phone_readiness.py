from __future__ import annotations

from dataclasses import dataclass


_ALLOWED_CODE_VERIFICATION_STATUS = {"verified"}
_ALLOWED_PHONE_STATUS = {"connected", "verified", "active"}
_ALLOWED_PLATFORM_TYPE = {"cloud_api"}


@dataclass
class PhoneReadinessResult:
    ready: bool
    reason: str
    code_verification_status: str
    phone_status: str
    platform_type: str


class WhatsAppPhoneReadinessPolicy:
    def evaluate(self, profile: dict) -> PhoneReadinessResult:
        code_verification_status = str(profile.get("code_verification_status") or "").strip().lower()
        phone_status = str(profile.get("status") or "").strip().lower()
        platform_type = str(profile.get("platform_type") or "").strip().lower()

        if code_verification_status not in _ALLOWED_CODE_VERIFICATION_STATUS:
            return PhoneReadinessResult(
                ready=False,
                reason="code_verification_status_not_ready",
                code_verification_status=code_verification_status,
                phone_status=phone_status,
                platform_type=platform_type,
            )
        if phone_status and phone_status not in _ALLOWED_PHONE_STATUS:
            return PhoneReadinessResult(
                ready=False,
                reason="phone_status_not_ready",
                code_verification_status=code_verification_status,
                phone_status=phone_status,
                platform_type=platform_type,
            )
        if platform_type and platform_type not in _ALLOWED_PLATFORM_TYPE:
            return PhoneReadinessResult(
                ready=False,
                reason="platform_type_not_supported",
                code_verification_status=code_verification_status,
                phone_status=phone_status,
                platform_type=platform_type,
            )
        return PhoneReadinessResult(
            ready=True,
            reason="ready",
            code_verification_status=code_verification_status,
            phone_status=phone_status,
            platform_type=platform_type,
        )


whatsapp_phone_readiness_policy = WhatsAppPhoneReadinessPolicy()

