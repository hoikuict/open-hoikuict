from datetime import timedelta

from sqlmodel import select

from models import GuardianTerminalStatus
from time_utils import ensure_utc, utc_now


def terminal_statuses(session):
    now = utc_now()
    hour = (now + timedelta(hours=9)).hour
    return [
        {
            "terminal": terminal,
            "stale": terminal.monitoring_enabled
            and terminal.start_hour <= hour < terminal.end_hour
            and now - ensure_utc(terminal.last_seen_at) > timedelta(minutes=2),
        }
        for terminal in session.exec(
            select(GuardianTerminalStatus).order_by(GuardianTerminalStatus.created_at)
        ).all()
    ]
