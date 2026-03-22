import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import (
    MOCK_ROLE_COOKIE,
    MOCK_STAFF_EMPLOYMENT_COOKIE,
    MOCK_STAFF_ID_COOKIE,
    MOCK_STAFF_NAME_COOKIE,
    Role,
)
from models import (
    AttendanceAlarmHistory,
    AttendanceAlarmState,
    AttendanceVerification,
    AttendanceVerificationHistory,
    Child,
    ChildStatus,
    Classroom,
    DailyContactEntry,
    ParentAccount,
    ParentContactType,
    Staff,
    StaffEmploymentType,
    StaffStatus,
)
import routers.attendance_checks as attendance_checks_module


class AttendanceChecksTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(attendance_checks_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[attendance_checks_module.get_session] = override_get_session
        self.client = TestClient(self.app)
        self.day = date(2026, 3, 22)

        with Session(self.engine) as session:
            classroom = Classroom(name="Sunflower", display_order=1)
            session.add(classroom)
            session.flush()

            child = Child(
                last_name="Tanaka",
                first_name="Taro",
                last_name_kana="tanaka",
                first_name_kana="taro",
                birth_date=date(2021, 4, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            regular_viewer = Staff(
                full_name="Regular Viewer",
                display_name="Regular Viewer",
                role=Role.VIEW_ONLY,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=classroom.id,
            )
            part_timer = Staff(
                full_name="Part Timer",
                display_name="Part Timer",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.part_time,
                primary_classroom_id=classroom.id,
            )
            parent = ParentAccount(
                display_name="Tanaka Parent",
                email="tanaka-parent@example.com",
            )
            session.add(child)
            session.add(regular_viewer)
            session.add(part_timer)
            session.add(parent)
            session.commit()

            self.child_id = child.id
            self.regular_viewer_id = regular_viewer.id
            self.part_timer_id = part_timer.id
            self.parent_id = parent.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _login_staff(self, *, staff_id: int, name: str, role: Role, employment_type: StaffEmploymentType):
        self.client.cookies.set(MOCK_STAFF_ID_COOKIE, str(staff_id))
        self.client.cookies.set(MOCK_STAFF_NAME_COOKIE, name)
        self.client.cookies.set(MOCK_ROLE_COOKIE, role.value)
        self.client.cookies.set(MOCK_STAFF_EMPLOYMENT_COOKIE, employment_type.value)

    def test_regular_non_part_time_staff_can_update_attendance_check(self):
        self._login_staff(
            staff_id=self.regular_viewer_id,
            name="regular_viewer",
            role=Role.VIEW_ONLY,
            employment_type=StaffEmploymentType.regular,
        )

        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": self.day.isoformat(),
                "status": "present",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            verification = session.exec(select(AttendanceVerification)).first()
            history = session.exec(select(AttendanceVerificationHistory)).all()

        self.assertIsNotNone(verification)
        self.assertEqual(verification.status.value, "present")
        self.assertEqual(verification.updated_by_name, "regular_viewer")
        self.assertEqual(len(history), 1)

    def test_htmx_update_returns_partial_and_keeps_operator_history(self):
        self._login_staff(
            staff_id=self.regular_viewer_id,
            name="regular_viewer",
            role=Role.VIEW_ONLY,
            employment_type=StaffEmploymentType.regular,
        )

        first_response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            headers={"HX-Request": "true"},
            data={
                "date": self.day.isoformat(),
                "status": "present",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
        )
        second_response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            headers={"HX-Request": "true"},
            data={
                "date": self.day.isoformat(),
                "status": "present",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
        )

        self.assertEqual(first_response.status_code, 200)
        self.assertEqual(second_response.status_code, 200)
        self.assertIn('id="attendance-checks-board"', second_response.text)
        self.assertIn("regular_viewer", second_response.text)
        self.assertIn("data-history-status=", second_response.text)

        with Session(self.engine) as session:
            verification = session.exec(select(AttendanceVerification)).first()
            histories = session.exec(
                select(AttendanceVerificationHistory).order_by(AttendanceVerificationHistory.id)
            ).all()

        self.assertIsNotNone(verification)
        self.assertEqual(verification.updated_by_name, "regular_viewer")
        self.assertEqual(len(histories), 2)
        self.assertTrue(all(history.updated_by_name == "regular_viewer" for history in histories))

    def test_part_time_staff_cannot_update_attendance_check(self):
        self._login_staff(
            staff_id=self.part_timer_id,
            name="part_timer",
            role=Role.CAN_EDIT,
            employment_type=StaffEmploymentType.part_time,
        )

        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": self.day.isoformat(),
                "status": "present",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
        )

        self.assertEqual(response.status_code, 403)

    def test_alarm_is_created_and_auto_cleared_when_condition_is_resolved(self):
        self._login_staff(
            staff_id=self.regular_viewer_id,
            name="regular_viewer",
            role=Role.VIEW_ONLY,
            employment_type=StaffEmploymentType.regular,
        )

        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": self.day.isoformat(),
                "status": "private_absent",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            alarm_state = session.exec(select(AttendanceAlarmState)).first()
            self.assertIsNotNone(alarm_state)
            self.assertTrue(alarm_state.is_active)
            self.assertEqual(alarm_state.reasons, ["no_contact_and_not_present"])

            session.add(
                DailyContactEntry(
                    child_id=self.child_id,
                    parent_account_id=self.parent_id,
                    target_date=self.day,
                    contact_type=ParentContactType.absent_private,
                    absence_note="family errand",
                )
            )
            session.commit()

        refresh_response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")
        self.assertEqual(refresh_response.status_code, 200)

        with Session(self.engine) as session:
            alarm_state = session.exec(select(AttendanceAlarmState)).first()
            alarm_history = session.exec(select(AttendanceAlarmHistory)).all()

        self.assertFalse(alarm_state.is_active)
        self.assertEqual(len(alarm_history), 2)


if __name__ == "__main__":
    unittest.main()
