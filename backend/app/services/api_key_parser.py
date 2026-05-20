from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ParsedApiKey:
    raw: str
    prefix: str
    environment: str
    secret: str


class ApiKeyParser:
    @staticmethod
    def parse(raw_key: str) -> ParsedApiKey | None:
        if not raw_key or not isinstance(raw_key, str):
            return None
        normalized = raw_key.strip()
        if not normalized:
            return None
        if len(normalized) > 256:
            return None
        if not normalized.startswith("mtk_"):
            return None
        parts = normalized.split("_", 2)
        if len(parts) != 3:
            return None
        _, environment, secret = parts
        if environment not in {"live", "test", "sandbox"}:
            return None
        if len(secret) < 12:
            return None
        return ParsedApiKey(
            raw=normalized,
            prefix=normalized[:12],
            environment=environment,
            secret=secret,
        )

    @staticmethod
    def is_legacy_uuid(raw_key: str) -> bool:
        if not raw_key or not isinstance(raw_key, str):
            return False
        normalized = raw_key.strip()
        if not normalized or len(normalized) > 256:
            return False
        try:
            UUID(normalized)
            return True
        except ValueError:
            return False
