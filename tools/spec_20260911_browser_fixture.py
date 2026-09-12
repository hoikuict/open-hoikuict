"""Synthetic browser checks; all records are in memory and mail is captured."""

from datetime import datetime

from fastapi import Depends
from starlette.exceptions import HTTPException
from sqlmodel import Session

from tools.spec_change_browser_fixture import app, engine
from auth import staff_auth_http_exception_handler
from csrf import CsrfTokenMiddleware, verify_csrf
from models import AttendanceRecord, Family, Child, Message, GuardianTerminalStatus
from routers import (
    document_reviews,
    families,
    parent_accounts,
    staff_rooms,
    terminal_monitor,
)
from time_utils import local_today, utc_now

app.add_middleware(CsrfTokenMiddleware)
app.add_exception_handler(HTTPException, staff_auth_http_exception_handler)
# The base fixture's attendance/guardian routes were already registered.
# Apply CSRF to them as well, so cancellations use the production form path.
from fastapi.routing import APIRoute
from fastapi.dependencies.utils import get_parameterless_sub_dependant

for route in app.routes:
    if isinstance(route, APIRoute):
        route.dependant.dependencies.insert(
            0,
            get_parameterless_sub_dependant(
                depends=Depends(verify_csrf), path=route.path_format
            ),
        )
for router in (
    document_reviews.router,
    families.router,
    parent_accounts.router,
    staff_rooms.router,
    terminal_monitor.router,
):
    app.include_router(router, dependencies=[Depends(verify_csrf)])

with Session(engine) as session:
    family = Family(family_name="表示確認家")
    session.add(family)
    session.flush()
    for child_id in (1, 2):
        child = session.get(Child, child_id)
        child.family_id = family.id
        session.add(child)
    session.add(
        AttendanceRecord(
            child_id=1,
            attendance_date=local_today(),
            check_in_at=datetime.combine(local_today(), datetime.min.time()).replace(
                hour=9
            ),
        )
    )
    session.add(
        Message(
            room_id=1,
            author_name="表示確認職員",
            body="詳細は https://example.test/form を確認してください。",
        )
    )
    session.add(
        GuardianTerminalStatus(
            device_id="browser-test", label="玄関タブレット", last_seen_at=utc_now()
        )
    )
    session.commit()
