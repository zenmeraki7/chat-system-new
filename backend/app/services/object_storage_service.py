from __future__ import annotations

from pathlib import Path
import uuid


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

    def get_text(self, key: str, encoding: str = "utf-8") -> str:
        path = self.base_dir / key
        return path.read_text(encoding=encoding)

    def build_url(self, key: str) -> str:
        return f"/storage/{key}"


object_storage_service = ObjectStorageService()
