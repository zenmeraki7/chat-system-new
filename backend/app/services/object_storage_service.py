from __future__ import annotations

from pathlib import Path
import uuid
import hmac
import hashlib
import base64
from datetime import datetime, timezone, timedelta
from app.config import settings


class ObjectStorageService:
    def __init__(self, base_dir: str = "storage") -> None:
        self.base_dir = Path(__file__).resolve().parent.parent.parent / base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def put_bytes(self, *, namespace: str, filename_hint: str, content: bytes) -> str:
        ns_dir = self.base_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        safe_name = (filename_hint or "upload.csv").replace("\\", "_").replace("/", "_")
        key = f"{uuid.uuid4().hex}_{safe_name}"
        path = ns_dir / key
        path.write_bytes(content)
        return f"{namespace}/{key}"

    def put_file(self, *, namespace: str, filename_hint: str, source_path: str) -> str:
        ns_dir = self.base_dir / namespace
        ns_dir.mkdir(parents=True, exist_ok=True)
        safe_name = (filename_hint or "upload.csv").replace("\\", "_").replace("/", "_")
        key = f"{uuid.uuid4().hex}_{safe_name}"
        path = ns_dir / key
        path.write_bytes(Path(source_path).read_bytes())
        return f"{namespace}/{key}"

    def get_text(self, key: str, encoding: str = "utf-8") -> str:
        path = self.base_dir / key
        return path.read_text(encoding=encoding)

    def build_url(self, key: str) -> str:
        return f"/storage/{key}"

    def build_signed_download_url(self, key: str, *, expires_in_seconds: int = 600) -> tuple[str, datetime]:
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=max(30, int(expires_in_seconds)))
        payload = f"{key}:{int(expires_at.timestamp())}"
        signature = hmac.new(
            settings.SECRET_KEY.encode("utf-8"),
            payload.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        token_blob = f"{payload}:{signature}".encode("utf-8")
        token = base64.urlsafe_b64encode(token_blob).decode("utf-8").rstrip("=")
        return f"/api/v1/contacts/exports/download/{token}", expires_at

    def resolve_signed_download_token(self, token: str) -> str:
        padded = token + "=" * (-len(token) % 4)
        try:
            raw = base64.urlsafe_b64decode(padded.encode("utf-8")).decode("utf-8")
            key, ts_raw, sig = raw.rsplit(":", 2)
            expected = hmac.new(
                settings.SECRET_KEY.encode("utf-8"),
                f"{key}:{ts_raw}".encode("utf-8"),
                hashlib.sha256,
            ).hexdigest()
            if not hmac.compare_digest(expected, sig):
                raise ValueError("signature_mismatch")
            expires_at = datetime.fromtimestamp(int(ts_raw), tz=timezone.utc)
            if expires_at <= datetime.now(timezone.utc):
                raise ValueError("token_expired")
            return key
        except Exception as exc:
            raise ValueError("invalid_download_token") from exc


object_storage_service = ObjectStorageService()
