from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping


@dataclass(frozen=True)
class DailyContactReplyField:
    key: str
    label: str
    input_type: str = "text"
    placeholder: str = ""
    options: tuple[str, ...] = ()


DEFAULT_DAILY_CONTACT_REPLY_FIELDS: tuple[DailyContactReplyField, ...] = (
    DailyContactReplyField("nap_time", "お昼寝時間", placeholder="12:30-14:20"),
    DailyContactReplyField("temperature", "体温", placeholder="36.8"),
    DailyContactReplyField("bowel_movement", "排便", input_type="select", options=("あり", "なし")),
    DailyContactReplyField("appetite", "食欲", input_type="select", options=("完食", "ほぼ完食", "半分", "少なめ")),
)


def reply_field_definitions() -> tuple[DailyContactReplyField, ...]:
    return DEFAULT_DAILY_CONTACT_REPLY_FIELDS


def _clean_value(raw: Any) -> str:
    return str(raw or "").strip()


def reply_values_from_mapping(form_data: Mapping[str, Any]) -> dict[str, str]:
    values: dict[str, str] = {}
    for field in DEFAULT_DAILY_CONTACT_REPLY_FIELDS:
        value = _clean_value(form_data.get(f"reply_{field.key}"))
        if field.options and value not in field.options:
            value = ""
        if value:
            values[field.key] = value
    return values


def reply_values_for_form(reply) -> dict[str, str]:
    stored_values = reply.field_values if reply and reply.field_values else {}
    return {
        field.key: _clean_value(stored_values.get(field.key))
        for field in DEFAULT_DAILY_CONTACT_REPLY_FIELDS
    }


def reply_items_for_display(reply) -> list[dict[str, str]]:
    if not reply:
        return []
    stored_values = reply.field_values or {}
    items: list[dict[str, str]] = []
    for field in DEFAULT_DAILY_CONTACT_REPLY_FIELDS:
        value = _clean_value(stored_values.get(field.key))
        if value:
            items.append({"key": field.key, "label": field.label, "value": value})
    return items
