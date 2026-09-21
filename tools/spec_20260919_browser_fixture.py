"""Local synthetic records for the approved September 19 parent/kiosk flow."""
from datetime import date

from sqlmodel import Session, select

from models import AttendanceRecord, AttendanceVerification, AttendanceVerificationStatus, Child, DailyContactEntry
from time_utils import local_today
from tools.spec_20260917_browser_fixture import app, fixture

with Session(fixture.engine) as session:
    original = session.get(Child, fixture.child_id)
    room_id = original.classroom_id
    children = []
    for name in ("あお", "ひな"):
        child = Child(last_name="見本", first_name=name, last_name_kana="ミホン", first_name_kana=name,
                      birth_date=date(2023, 4, 1), enrollment_date=date(2026, 4, 1), classroom_id=room_id)
        session.add(child)
        session.flush()
        children.append(child.id)
    partial_id, visual_id = children
    session.add(AttendanceRecord(child_id=partial_id, attendance_date=local_today(), planned_pickup_time="17:00"))
    session.add(AttendanceVerification(child_id=visual_id, target_date=local_today(), status=AttendanceVerificationStatus.present))
    session.commit()


@app.get("/__fixture19")
def ids19():
    return dict(parent_id=fixture.parent_account_id, child_id=fixture.child_id, room_id=room_id,
                partial_id=partial_id, visual_id=visual_id, today=str(local_today()))


@app.get("/__fixture19/state")
def state19():
    with Session(fixture.engine) as session:
        records = session.exec(select(AttendanceRecord).where(AttendanceRecord.attendance_date == local_today())).all()
        contacts = session.exec(select(DailyContactEntry).where(DailyContactEntry.target_date == local_today())).all()
        return dict(records={str(r.child_id): r.model_dump(mode="json") for r in records},
                    contacts={str(c.child_id): c.model_dump(mode="json") for c in contacts})
