"""Synthetic, memory-only app for visual QA. Run on loopback; never deploy this module."""
import os
from datetime import date, datetime, timedelta
from pathlib import Path

os.environ.update(HOIKUICT_ENV="test", HOIKUICT_ENABLE_MOCK_AUTH="1", HOIKUICT_KIOSK_ACCESS_MODE="open", HOIKUICT_ALLOW_OPEN_KIOSK="1",
                  HOIKUICT_PARENT_MAIL_TRANSPORT="capture", HOIKUICT_CSRF_ENFORCE="1", HOIKUICT_COOKIE_SECURE="0",
                  HOIKUICT_SECRET_KEY="synthetic-spec24-browser-only")

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from auth import Role, StaffUser, get_current_staff_user
from csrf import CsrfTokenMiddleware, verify_csrf
from database import get_session
from models import (AttendanceAlarmState, AttendanceRecord, AttendanceVerification, Child, Classroom,
                    DailyContactEntry, DailyContactReply, ParentAccount, ParentChildLink, User)
from routers import attendance, attendance_checks, daily_contacts, guardian, settings
from time_utils import local_today

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
SQLModel.metadata.create_all(engine)
today = local_today()
with Session(engine) as session:
    user = User(email="spec24@example.test", display_name="画面検証 職員", staff_role="admin")
    parent = ParentAccount(display_name="見本 保護者", email="spec24-parent@example.test")
    session.add_all([user, parent])
    session.flush()
    actor = StaffUser(role=Role.ADMIN, name=user.display_name, user_id=user.id)
    number = 0
    for index, size in enumerate([7, 15, 20, 20, 17, 21]):
        classroom = Classroom(name=["つぼみ", "たんぽぽ", "すみれ", "ひまわり", "ゆり", "さくら"][index] + "組", display_order=index)
        session.add(classroom)
        session.flush()
        for n in range(size):
            number += 1
            child = Child(last_name="見本", first_name=f"園児{number:03d}", last_name_kana="ミホン", first_name_kana=f"{number:03d}",
                          birth_date=date(2022, 4, 1), enrollment_date=date(2026, 4, 1), classroom_id=classroom.id)
            session.add(child)
            session.flush()
            state = number % 10
            if state < 8:
                session.add(AttendanceVerification(child_id=child.id, target_date=today,
                                                    status="present" if state < 7 else "sick_absent", updated_by_name=actor.name))
            if state < 7:
                session.add(AttendanceRecord(child_id=child.id, attendance_date=today,
                    check_in_at=datetime.combine(today, datetime.min.time()).replace(hour=8, minute=number % 60),
                    check_out_at=datetime.combine(today, datetime.min.time()).replace(hour=16) if state == 6 else None))
            if number in (1, 18, 42):
                session.add(AttendanceAlarmState(child_id=child.id, target_date=today, is_active=True, reasons=["no_contact_and_not_present"]))
            if number == 1:
                session.add(ParentChildLink(child_id=child.id, parent_account_id=parent.id))
                session.add(DailyContactEntry(child_id=child.id, parent_account_id=parent.id, target_date=today,
                    contact_type="present", temperature="36.5", breakfast_status="完食", sleep_notes="よく眠れた",
                    bowel_movement_status="あり", condition_note="元気です", contact_note="よろしくお願いします。"))
                for offset, status in ((1, "draft"), (2, "published")):
                    session.add(DailyContactReply(child_id=child.id, target_date=today - timedelta(days=offset), status=status,
                        field_values={"temperature": "36.5", "bowel_movement": "あり"}, message="園庭で遊びました。", staff_name=actor.name))
    session.commit()

app = FastAPI(dependencies=[Depends(verify_csrf)])
app.add_middleware(CsrfTokenMiddleware)
app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parents[1] / "static"), name="static")
for module in (attendance, attendance_checks, daily_contacts, guardian, settings):
    app.include_router(module.router)


def session_dependency():
    with Session(engine) as session:
        yield session


app.dependency_overrides[get_session] = session_dependency
app.dependency_overrides[get_current_staff_user] = lambda: actor
