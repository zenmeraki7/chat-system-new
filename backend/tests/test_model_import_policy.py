from __future__ import annotations

from pathlib import Path
import importlib


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"


def _iter_py_files() -> list[Path]:
    return [p for p in APP_ROOT.rglob("*.py") if "__pycache__" not in str(p)]


def test_no_wildcard_imports_from_app_models() -> None:
    violations: list[str] = []
    for file in _iter_py_files():
        text = file.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if "from app.models import *" in line:
                violations.append(f"{file}:{i}:{line.strip()}")
    assert not violations, "\n".join(violations)


def test_app_models_root_does_not_reexport_domain_enums() -> None:
    mod = importlib.import_module("app.models")
    assert not hasattr(mod, "ConversationStatus")
    assert not hasattr(mod, "MessageRole")
