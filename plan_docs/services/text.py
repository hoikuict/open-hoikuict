from __future__ import annotations


def clean_text(value: object) -> str:
    return " ".join(str(value or "").replace("\r", "\n").split())


def confirmation_items(items: list[tuple[str, str]]) -> list[str]:
    return [label for label, value in items if not clean_text(value)]
