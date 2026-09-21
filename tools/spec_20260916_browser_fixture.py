"""Synthetic in-memory app for the September 16 browser regression checks."""
import os

from fastapi.responses import RedirectResponse
from sqlmodel import Session

from auth import Role, get_current_staff_user, set_staff_cookies
from models import MeetingNote
from routers import attendance_checks, guardian, meeting_notes, terminal_monitor
from test_parent_portal import ParentPortalTests

fixture = ParentPortalTests()
fixture.setUp()
app = fixture.app
for router in (attendance_checks.router, guardian.router, meeting_notes.router, terminal_monitor.router):
    app.include_router(router)
os.environ.update(HOIKUICT_KIOSK_ACCESS_MODE="token", HOIKUICT_KIOSK_TOKEN="synthetic-browser-token",
                  HOIKUICT_SECRET_KEY="synthetic-browser-secret-20260916-only")
with Session(fixture.engine) as session:
    note = MeetingNote(title="自動保存の検証")
    session.add(note)
    session.commit()
    note_id = note.id
actor = app.dependency_overrides[get_current_staff_user]()
actor.role = Role.ADMIN
app.dependency_overrides[get_current_staff_user] = lambda: actor


@app.get('/__fixture')
def ids():
    return {'parent_id': fixture.parent_account_id, 'child_id': fixture.child_id, 'note_id': note_id}


@app.get('/__fixture_login')
def staff_login():
    response = RedirectResponse('/meeting-notes/')
    set_staff_cookies(response, role=Role.ADMIN, name='ブラウザー検証職員', user_id='00000000-0000-0000-0000-000000000001')
    return response
