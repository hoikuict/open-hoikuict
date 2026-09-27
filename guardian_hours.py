"""Closing time for the nursery kiosk (Japan local time)."""
import re
from datetime import datetime

from sqlmodel import Session

from models import GuardianHoursSetting
from time_utils import local_naive_now


def parse_closing_time(raw: str) -> str:
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", raw or "") or raw == "00:00":
        raise ValueError("閉園時刻は00:01〜23:59で入力してください。")
    return raw


def closing_time(session: Session) -> str:
    setting = session.get(GuardianHoursSetting, 1)
    return setting.closing_time if setting else "19:00"


def kiosk_is_closed(session: Session, now: datetime | None = None) -> bool:
    return (now or local_naive_now()).strftime("%H:%M") >= closing_time(session)
