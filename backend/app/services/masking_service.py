class MaskingService:
    @staticmethod
    def mask_email(email: str | None) -> str | None:
        if not email:
            return email
        parts = email.split("@")
        if len(parts) != 2:
            return "***"
        local, domain = parts
        if len(local) <= 2:
            return "**@" + domain
        return local[:2] + "***@" + domain

    @staticmethod
    def mask_phone(phone: str | None) -> str | None:
        if not phone:
            return phone
        digits = ''.join(c for c in phone if c.isdigit())
        if len(digits) <= 4:
            return "****"
        return "*" * (len(digits) - 4) + digits[-4:]

    @staticmethod
    def mask_api_key_prefix(prefix: str | None) -> str | None:
        if not prefix:
            return prefix
        return prefix

    @staticmethod
    def mask_secret(_: str | None) -> str:
        return "[REDACTED]"
