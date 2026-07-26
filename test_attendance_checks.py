import unittest
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
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
    ParentChildLink,
    ParentContactType,
    ParentNotification,
    ParentNotificationDelivery,
)
import routers.attendance_checks as attendance_checks_module
from parent_notification_service import queue_push_delivery


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

        self.current_user = StaffUser(role=Role.CAN_EDIT, name="確認担当")

        def override_get_current_staff_user():
            return self.current_user

        self.app.dependency_overrides[attendance_checks_module.get_session] = override_get_session
        self.app.dependency_overrides[attendance_checks_module.get_current_staff_user] = override_get_current_staff_user

        self.client = TestClient(self.app)
        self.day = date(2026, 3, 22)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひまわり組", display_order=1)
            session.add(classroom)
            session.flush()

            child = Child(
                last_name="田中",
                first_name="太郎",
                last_name_kana="タナカ",
                first_name_kana="タロウ",
                birth_date=date(2021, 4, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            parent = ParentAccount(
                display_name="田中 保護者",
                email="tanaka-parent@example.com",
            )
            session.add(child)
            session.add(parent)
            session.flush()
            session.add(
                ParentChildLink(
                    parent_account_id=parent.id,
                    child_id=child.id,
                    relationship_label="母",
                    is_primary_contact=True,
                )
            )
            session.commit()

            self.child_id = child.id
            self.parent_id = parent.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_editor_can_update_attendance_check(self):
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
        self.assertEqual(verification.updated_by_name, "確認担当")
        self.assertEqual(len(history), 1)

    def test_htmx_update_returns_partial_and_keeps_operator_history(self):
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
        self.assertIn("確認担当", second_response.text)
        self.assertIn("data-history-status=", second_response.text)

        with Session(self.engine) as session:
            verification = session.exec(select(AttendanceVerification)).first()
            histories = session.exec(
                select(AttendanceVerificationHistory).order_by(AttendanceVerificationHistory.id)
            ).all()

        self.assertIsNotNone(verification)
        self.assertEqual(verification.updated_by_name, "確認担当")
        self.assertEqual(len(histories), 2)
        self.assertTrue(all(history.updated_by_name == "確認担当" for history in histories))

    def test_list_shows_compact_summary_row_and_detail_toggle(self):
        with Session(self.engine) as session:
            session.add(
                DailyContactEntry(
                    child_id=self.child_id,
                    parent_account_id=self.parent_id,
                    target_date=self.day,
                    contact_type=ParentContactType.absent_sick,
                    absence_temperature="38.2",
                    absence_symptoms="発熱",
                    absence_note="受診予定",
                )
            )
            session.commit()

        response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("詳細表示", response.text)
        self.assertIn(f'aria-controls="attendance-check-detail-{self.child_id}"', response.text)
        self.assertIn('data-status-key="present"', response.text)
        self.assertIn('data-status-key="private_absent"', response.text)
        self.assertIn('data-status-key="sick_absent"', response.text)
        self.assertIn('data-status-key="unknown"', response.text)
        self.assertRegex(
            response.text,
            r'data-status-key="unknown"[\s\S]*?aria-pressed="false"',
        )
        self.assertIn("病欠", response.text)

    def test_only_explicit_unknown_is_highlighted(self):
        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": self.day.isoformat(),
                "status": "unknown",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        list_response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")

        self.assertRegex(
            list_response.text,
            r'data-status-key="unknown"[\s\S]*?aria-pressed="true"',
        )

    def test_unknown_can_notify_linked_parent_for_future_push_delivery(self):
        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": self.day.isoformat(),
                "status": "unknown",
                "notify_parent": "true",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("notice=parent_notified", response.headers["location"])
        with Session(self.engine) as session:
            notification = session.exec(select(ParentNotification)).one()
            delivery = session.exec(select(ParentNotificationDelivery)).one()

        self.assertEqual(notification.parent_account_id, self.parent_id)
        self.assertEqual(notification.child_id, self.child_id)
        self.assertEqual(
            notification.body,
            "本日の連絡をいただいておりません。出席か欠席かお知らせください。",
        )
        self.assertEqual(delivery.notification_id, notification.id)
        self.assertEqual(delivery.channel.value, "in_app")
        self.assertEqual(delivery.status.value, "delivered")

        with Session(self.engine) as session:
            notification = session.get(ParentNotification, notification.id)
            push_delivery = queue_push_delivery(session, notification)
            session.commit()
            session.refresh(push_delivery)
            self.assertEqual(push_delivery.channel.value, "push")
            self.assertEqual(push_delivery.status.value, "pending")

    def test_unknown_without_parent_contact_does_not_create_notification(self):
        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": self.day.isoformat(),
                "status": "unknown",
                "notify_parent": "false",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(ParentNotification)).all(), [])

    def test_view_only_unconfirmed_status_uses_white_background(self):
        self.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧担当")

        response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertRegex(
            response.text,
            r'data-readonly-status="unknown"[\s\S]*?border border-slate-200 bg-white',
        )

    def test_view_only_staff_cannot_update_attendance_check(self):
        self.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧担当")

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

    def test_view_only_staff_can_see_present_and_absent_results(self):
        for status, expected_label in (("present", "出席"), ("sick_absent", "病欠")):
            self.current_user = StaffUser(role=Role.CAN_EDIT, name="確認担当")
            update_response = self.client.post(
                f"/attendance-checks/{self.child_id}/verification",
                data={
                    "date": self.day.isoformat(),
                    "status": status,
                    "layout": "flat",
                    "filter": "all",
                    "classroom_id": "",
                },
                follow_redirects=False,
            )
            self.assertEqual(update_response.status_code, 303)

            self.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧担当")
            response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")

            self.assertEqual(response.status_code, 200)
            self.assertIn("確認結果", response.text)
            self.assertIn(f'data-readonly-status="{status}"', response.text)
            self.assertIn(expected_label, response.text)
            self.assertIn("確認者: 確認担当", response.text)
            self.assertNotIn('data-status-key="present"', response.text)

    def test_verification_audit_time_is_displayed_in_jst(self):
        with Session(self.engine) as session:
            session.add(
                AttendanceVerification(
                    child_id=self.child_id,
                    target_date=self.day,
                    status="present",
                    updated_by_name="主任",
                    created_at=datetime(2026, 7, 25, 23, 22),
                    updated_at=datetime(2026, 7, 25, 23, 22),
                )
            )
            session.commit()

        self.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧担当")
        response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")

        self.assertEqual(response.status_code, 200)
        self.assertIn("確認時刻 (JST):", response.text)
        self.assertIn("08:22", response.text)
        self.assertNotIn("確認時刻 (JST): 23:22", response.text)

    def test_alarm_is_not_recalculated_by_list_get(self):
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
                    absence_note="私用のため欠席",
                )
            )
            session.commit()

        refresh_response = self.client.get(f"/attendance-checks/?date={self.day.isoformat()}")
        self.assertEqual(refresh_response.status_code, 200)

        with Session(self.engine) as session:
            alarm_state = session.exec(select(AttendanceAlarmState)).first()
            alarm_history = session.exec(select(AttendanceAlarmHistory)).all()

        self.assertTrue(alarm_state.is_active)
        self.assertEqual(len(alarm_history), 1)

    def test_invalid_date_is_rejected_without_creating_verification(self):
        response = self.client.post(
            f"/attendance-checks/{self.child_id}/verification",
            data={
                "date": "not-a-date",
                "status": "present",
                "layout": "flat",
                "filter": "all",
                "classroom_id": "",
            },
        )

        self.assertEqual(response.status_code, 400)
        with Session(self.engine) as session:
            verification = session.exec(select(AttendanceVerification)).first()
        self.assertIsNone(verification)


if __name__ == "__main__":
    unittest.main()
