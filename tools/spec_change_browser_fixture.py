"""Synthetic, in-memory app for test-spec-change-browser.cjs; never loads the live DB."""
from datetime import date
from uuid import UUID

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import Role, StaffUser, get_current_staff_user, set_staff_cookies
from database import get_session
from models import Child, Classroom, MeetingNote, User
from routers import attendance, attendance_checks, guardian, institutional_records, meeting_notes
from testing_helpers import configure_test_environment


configure_test_environment()
engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SQLModel.metadata.create_all(engine)
user_id = UUID("00000000-0000-0000-0000-000000000091")
user = StaffUser(role=Role.ADMIN, name="表示確認職員", user_id=user_id)
with Session(engine) as session:
    session.add(User(id=user_id, email="browser-fixture@example.test", display_name=user.name, staff_role="admin"))
    classroom = Classroom(name="検証クラス")
    session.add(classroom)
    session.flush()
    for index in range(50):
        session.add(Child(
            last_name="表示確認", first_name=f"園児{index:02d}",
            last_name_kana="ヒョウジカクニン", first_name_kana=f"エンジ{index:02d}",
            birth_date=date(2022, 4, 1), enrollment_date=date(2025, 4, 1), classroom_id=classroom.id,
        ))
    session.add(MeetingNote(title="ブラウザー回帰確認", created_by=user.name))
    session.commit()

app = FastAPI()
for router in (attendance.router, attendance_checks.router, guardian.router, meeting_notes.router, institutional_records.highlights_router):
    app.include_router(router)


def sessions():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = sessions
app.dependency_overrides[get_current_staff_user] = lambda: user


@app.get("/__fixture_login")
def login():
    response = RedirectResponse("/attendance-checks/?date=2026-09-09")
    set_staff_cookies(response, role=Role.ADMIN, name=user.name, user_id=str(user_id))
    return response
