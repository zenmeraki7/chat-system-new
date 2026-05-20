from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"

ALLOWED_FILES = {
    str((APP_ROOT / "services" / "conversation_service.py").resolve()),
    str((APP_ROOT / "repositories" / "conversation_repo.py").resolve()),
}


def test_conversation_status_mutation_only_via_service_or_repo() -> None:
    violations: list[str] = []
    for file in APP_ROOT.rglob("*.py"):
        path = str(file.resolve())
        text = file.read_text(encoding="utf-8")
        if "conversation.status =" not in text:
            continue
        if path in ALLOWED_FILES:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if "conversation.status =" in line:
                violations.append(f"{file}:{i}:{line.strip()}")
    assert not violations, "\n".join(violations)
