"""Synthetic in-memory fixture for the September 15 browser checks."""
from sqlmodel import Session

from tools.spec_change_browser_fixture import app as app, engine, user_id
from calendar_import import router as import_router
from models import Calendar, CalendarMember, CalendarMemberRole
from routers.calendar import router as calendar_router

app.include_router(calendar_router)
app.include_router(import_router)
with Session(engine) as session:
    calendar = Calendar(name="取込検証カレンダー", owner_user_id=user_id)
    session.add(calendar)
    session.flush()
    session.add(CalendarMember(calendar_id=calendar.id, user_id=user_id, role=CalendarMemberRole.owner))
    session.commit()
