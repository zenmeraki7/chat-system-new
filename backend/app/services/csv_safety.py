from __future__ import annotations


def escape_csv_cell(value: object) -> str:
    raw = "" if value is None else str(value)
    left_trimmed = raw.lstrip()
    if left_trimmed.startswith(("=", "+", "-", "@")) or raw.startswith(("\t", "\r")):
        return f"'{raw}"
    return raw
