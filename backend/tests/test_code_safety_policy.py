from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "app"

TENANT_MODELS = ("Message", "Conversation", "Campaign", "Contact", "OutboundMessage")


def _iter_py_files() -> list[Path]:
    return [p for p in APP_ROOT.rglob("*.py") if "__pycache__" not in str(p)]


def test_ban_naked_session_get_for_tenant_models() -> None:
    pattern = re.compile(r"\.get\(\s*(%s)\s*," % "|".join(TENANT_MODELS))
    violations: list[str] = []
    for file in _iter_py_files():
        text = file.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{file}:{i}:{line.strip()}")
    assert not violations, "\n".join(violations)


def test_no_select_star_in_app_sql() -> None:
    violations: list[str] = []
    for file in _iter_py_files():
        text = file.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if "select *" in line.lower():
                violations.append(f"{file}:{i}:{line.strip()}")
    assert not violations, "\n".join(violations)


def test_no_fstring_sql_text_interpolation() -> None:
    pattern = re.compile(r"text\(\s*f[\"']")
    violations: list[str] = []
    for file in _iter_py_files():
        text = file.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), start=1):
            if pattern.search(line):
                violations.append(f"{file}:{i}:{line.strip()}")
    assert not violations, "\n".join(violations)
