import unittest
from datetime import datetime, time, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

import child_records.models  # noqa: F401
from auth import Role
from models import (
    AttendanceRecord,
    AttendanceVerification,
    AttendanceVerificationStatus,
    Calendar,
    CalendarMember,
    CalendarMemberRole,
    Child,
    ChildProfileChangeRequest,
    ChildProfileChangeRequestStatus,
    ChildStatus,
    Classroom,
    Event,
    Message,
    Notice,
    NoticeStatus,
    NoticeWorkflowAction,
    ParentAccount,
    StaffClassroomAssignment,
    StaffClassroomAssignmentRole,
    Survey,
    SurveyAnswerUnit,
    SurveyAudienceType,
    SurveyStatus,
    SurveyTarget,
    SurveyTargetType,
    User,
)
from plan_docs.auth_adapter import DEFAULT_NURSERY_REF
from plan_docs.db_models import PlanDocumentRow, PlanReviewNotificationRow
import routers.staff_portal as portal_module
from staff_portal_service import active_assignments
from testing_helpers import authenticate_mock_staff, configure_test_environment
from time_utils import local_today, utc_now


class StaffPortalTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(portal_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[portal_module.get_session] = override_get_session
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_logged_out_home_only_shows_clock_and_login_prompt(self):
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="current-time"', response.text)
        self.assertIn("ログインしてください", response.text)
        self.assertIn('href="/staff/login?redirect=/"', response.text)
        self.assertNotIn("今日の予定", response.text)
        self.assertNotIn("担当クラスの出席", response.text)
        self.assertNotIn("園児一覧", response.text)
        self.assertIn("no-store", response.headers.get("cache-control", ""))

    def test_staff_portal_alias_requires_login(self):
        response = self.client.get("/staff/portal", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff/login?redirect=/staff/portal")

    def test_admin_home_shows_monthly_plan_review_request(self):
        with Session(self.engine) as session:
            admin = User(
                email="principal-notification@example.com",
                display_name="園長",
                staff_role="admin",
            )
            session.add(admin)
            session.flush()
            session.add(
                PlanDocumentRow(
                    document_type="monthly_plan",
                    status="in_review",
                    title="8月 ひよこ組 月案",
                    nursery_ref=DEFAULT_NURSERY_REF,
                    classroom_ref="ひよこ組",
                    actor_ref="staff:teacher",
                    owner_name="ひよこ組担任",
                )
            )
            session.commit()
            admin_id = admin.id
        authenticate_mock_staff(
            self.client,
            role=Role.ADMIN,
            user_id=admin_id,
            name="園長",
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("すべての承認待ち", response.text)
        self.assertIn("承認待ち", response.text)
        self.assertIn("8月 ひよこ組 月案", response.text)
        self.assertIn("ひよこ組担任さんから承認依頼", response.text)

    def test_admin_home_combines_all_approval_request_types(self):
        today = local_today()
        with Session(self.engine) as session:
            admin = User(
                email="approval-admin@example.com",
                display_name="園長",
                staff_role="admin",
            )
            child = Child(
                last_name="佐藤",
                first_name="花",
                last_name_kana="サトウ",
                first_name_kana="ハナ",
                birth_date=today - timedelta(days=365 * 3),
                enrollment_date=today - timedelta(days=30),
                status=ChildStatus.enrolled,
            )
            parent = ParentAccount(
                display_name="佐藤 保護者",
                email="approval-parent@example.com",
            )
            session.add_all([admin, child, parent])
            session.flush()
            notice = Notice(
                title="運動会のお知らせ",
                body="開催案内",
                status=NoticeStatus.pending_approval,
                created_by="主任",
            )
            session.add(notice)
            session.flush()
            session.add(
                NoticeWorkflowAction(
                    notice_id=notice.id,
                    action="submitted",
                    actor_name="主任",
                )
            )
            session.add(
                ChildProfileChangeRequest(
                    child_id=child.id,
                    parent_account_id=parent.id,
                    status=ChildProfileChangeRequestStatus.pending,
                    change_summary="住所変更",
                )
            )
            session.add(
                PlanDocumentRow(
                    document_type="monthly_plan",
                    status="in_review",
                    title="9月 ひよこ組 月案",
                    nursery_ref=DEFAULT_NURSERY_REF,
                    classroom_ref="ひよこ組",
                    actor_ref="staff:teacher",
                    owner_name="ひよこ組担任",
                )
            )
            session.commit()
            admin_id = admin.id
            notice_id = notice.id

        authenticate_mock_staff(
            self.client,
            role=Role.ADMIN,
            user_id=admin_id,
            name="園長",
        )
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn(">3件<", response.text)
        self.assertIn("9月 ひよこ組 月案", response.text)
        self.assertIn("月案", response.text)
        self.assertIn("運動会のお知らせ", response.text)
        self.assertIn(f'href="/notices/{notice_id}/preview"', response.text)
        self.assertIn("佐藤 花さんの変更申請", response.text)
        self.assertIn("佐藤 保護者さんから承認依頼", response.text)
        self.assertIn("お知らせ", response.text)
        self.assertIn("園児情報変更", response.text)

    def test_creator_home_shows_child_record_review_outcome(self):
        with Session(self.engine) as session:
            creator = User(
                email="creator-notification@example.com",
                display_name="うさぎ組担任",
                staff_role="can_edit",
            )
            session.add(creator)
            session.flush()
            session.add(
                PlanReviewNotificationRow(
                    document_id=11,
                    review_revision_id=21,
                    recipient_user_id=creator.id,
                    nursery_ref=DEFAULT_NURSERY_REF,
                    document_title="佐藤 空 児童票",
                    notification_kind="review_outcome",
                    decision_status="rejected",
                    decided_by_name="園長",
                    decision_comment="家庭連携欄を再確認してください。",
                    requested_by_ref="staff:principal",
                    requested_by_name="園長",
                )
            )
            session.commit()
            creator_id = creator.id
        authenticate_mock_staff(
            self.client,
            role=Role.CAN_EDIT,
            user_id=creator_id,
            name="うさぎ組担任",
        )

        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("佐藤 空 児童票", response.text)
        self.assertIn("却下（差戻し）しました", response.text)
        self.assertIn("家庭連携欄を再確認してください。", response.text)

    def test_logged_in_home_shows_schedule_and_assigned_class_attendance(self):
        today = local_today()
        now = utc_now()
        with Session(self.engine) as session:
            user = User(
                email="teacher@example.com",
                display_name="ひよこ組担任",
                staff_role="can_edit",
                timezone="Asia/Tokyo",
            )
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(user)
            session.add(classroom)
            session.flush()
            child_present = Child(
                last_name="佐藤",
                first_name="花",
                last_name_kana="サトウ",
                first_name_kana="ハナ",
                birth_date=today - timedelta(days=365 * 3),
                enrollment_date=today - timedelta(days=30),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            child_unknown = Child(
                last_name="鈴木",
                first_name="空",
                last_name_kana="スズキ",
                first_name_kana="ソラ",
                birth_date=today - timedelta(days=365 * 2),
                enrollment_date=today - timedelta(days=30),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            session.add(child_present)
            session.add(child_unknown)
            session.flush()
            session.add(
                StaffClassroomAssignment(
                    staff_user_id=user.id,
                    classroom_id=classroom.id,
                    assignment_role=StaffClassroomAssignmentRole.primary,
                    starts_on=today - timedelta(days=30),
                    is_primary=True,
                )
            )
            session.add(
                AttendanceRecord(
                    child_id=child_present.id,
                    attendance_date=today,
                    check_in_at=datetime.combine(today, time(8, 30)),
                )
            )
            session.add(
                AttendanceVerification(
                    child_id=child_present.id,
                    target_date=today,
                    status=AttendanceVerificationStatus.present,
                )
            )
            calendar = Calendar(
                owner_user_id=user.id,
                name="ひよこ組予定",
                color="#4F46E5",
                is_primary=True,
            )
            session.add(calendar)
            session.flush()
            session.add(
                CalendarMember(
                    calendar_id=calendar.id,
                    user_id=user.id,
                    role=CalendarMemberRole.owner,
                )
            )
            session.add(
                Event(
                    calendar_id=calendar.id,
                    created_by_user_id=user.id,
                    title="クラスミーティング",
                    start_at=now - timedelta(minutes=10),
                    end_at=now + timedelta(minutes=50),
                    timezone="Asia/Tokyo",
                )
            )
            session.commit()
            user_id = user.id

        authenticate_mock_staff(
            self.client,
            role=Role.CAN_EDIT,
            user_id=user_id,
            name="ひよこ組担任",
        )
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("ひよこ組担任さん", response.text)
        self.assertIn("ひよこ組", response.text)
        self.assertIn("クラスミーティング", response.text)
        self.assertNotIn("佐藤 花", response.text)
        self.assertNotIn("鈴木 空", response.text)
        self.assertIn("在園中", response.text)
        self.assertIn("要確認 1", response.text)
        self.assertIn('href="/staff/attention"', response.text)
        self.assertIn("no-store", response.headers.get("cache-control", ""))

    def test_assignment_query_only_returns_current_period(self):
        today = local_today()
        with Session(self.engine) as session:
            user = User(email="staff@example.com", display_name="職員")
            current_class = Classroom(name="現在組", display_order=1)
            old_class = Classroom(name="旧組", display_order=2)
            session.add_all([user, current_class, old_class])
            session.flush()
            session.add_all(
                [
                    StaffClassroomAssignment(
                        staff_user_id=user.id,
                        classroom_id=current_class.id,
                        starts_on=today,
                    ),
                    StaffClassroomAssignment(
                        staff_user_id=user.id,
                        classroom_id=old_class.id,
                        starts_on=today - timedelta(days=20),
                        ends_on=today - timedelta(days=1),
                    ),
                ]
            )
            session.commit()
            user_id = user.id

        with Session(self.engine) as session:
            assignments = active_assignments(session, user_id, today)

        self.assertEqual([item.classroom.name for item in assignments], ["現在組"])

    def test_unanswered_staff_survey_is_listed_on_personal_attention_page(self):
        with Session(self.engine) as session:
            user = User(
                email="survey-staff@example.com",
                display_name="回答職員",
                staff_role="can_edit",
            )
            survey = Survey(
                title="研修希望調査",
                status=SurveyStatus.published,
                audience_type=SurveyAudienceType.staff,
                answer_unit=SurveyAnswerUnit.staff_user,
                closes_at=datetime.now() + timedelta(days=1),
            )
            session.add(user)
            session.add(survey)
            session.flush()
            session.add(
                SurveyTarget(
                    survey_id=survey.id,
                    target_type=SurveyTargetType.all_staff,
                )
            )
            session.commit()
            user_id = user.id

        authenticate_mock_staff(
            self.client,
            role=Role.CAN_EDIT,
            user_id=user_id,
            name="回答職員",
        )
        home_response = self.client.get("/")
        response = self.client.get("/staff/attention")

        self.assertEqual(home_response.status_code, 200)
        self.assertNotIn("研修希望調査", home_response.text)
        self.assertIn('href="/staff/attention"', home_response.text)
        self.assertEqual(response.status_code, 200)
        self.assertIn("研修希望調査", response.text)
        self.assertIn("アンケート", response.text)

    def test_personal_attention_page_lists_all_items_while_home_shows_count_only(self):
        today = local_today()
        with Session(self.engine) as session:
            user = User(
                email="hiyoko@example.com",
                display_name="ひよこ組担任",
                staff_role="can_edit",
            )
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add_all([user, classroom])
            session.flush()
            session.add(
                StaffClassroomAssignment(
                    staff_user_id=user.id,
                    classroom_id=classroom.id,
                    starts_on=today,
                )
            )
            for index in range(7):
                session.add(
                    Child(
                        last_name=f"園児{index}",
                        first_name="花",
                        last_name_kana=f"エンジ{index}",
                        first_name_kana="ハナ",
                        birth_date=today - timedelta(days=365 * 2),
                        enrollment_date=today - timedelta(days=30),
                        status=ChildStatus.enrolled,
                        classroom_id=classroom.id,
                    )
                )
            session.commit()
            user_id = user.id

        authenticate_mock_staff(
            self.client,
            role=Role.CAN_EDIT,
            user_id=user_id,
            name="ひよこ組担任",
        )
        home_response = self.client.get("/")
        response = self.client.get("/staff/attention")

        self.assertEqual(home_response.status_code, 200)
        self.assertNotIn("園児0 花", home_response.text)
        self.assertIn('href="/staff/attention"', home_response.text)
        self.assertEqual(response.status_code, 200)
        self.assertIn("7件", response.text)
        self.assertIn("園児0 花", response.text)
        self.assertIn("園児6 花", response.text)

    def test_home_shows_latest_parent_messages_as_timeline(self):
        with Session(self.engine) as session:
            user = User(
                email="timeline@example.com",
                display_name="タイムライン職員",
                staff_role="can_edit",
            )
            classroom = Classroom(name="職員ルーム", display_order=1)
            session.add_all([user, classroom])
            session.flush()
            parent = Message(
                room_id=classroom.id,
                author_name="園長",
                body="本日の連絡事項です",
            )
            session.add(parent)
            session.flush()
            session.add(
                Message(
                    room_id=classroom.id,
                    parent_message_id=parent.id,
                    author_name="主任",
                    body="返信本文はトップに単独表示しません",
                )
            )
            session.commit()
            user_id = user.id
            parent_id = parent.id

        authenticate_mock_staff(
            self.client,
            role=Role.CAN_EDIT,
            user_id=user_id,
            name="タイムライン職員",
        )
        response = self.client.get("/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("連絡タイムライン", response.text)
        self.assertIn("本日の連絡事項です", response.text)
        self.assertNotIn("返信本文はトップに単独表示しません", response.text)
        self.assertIn(f'/staff-rooms/threads/{parent_id}', response.text)

    def test_personal_attention_page_requires_login(self):
        response = self.client.get("/staff/attention", follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            "/staff/login?redirect=/staff/attention",
        )


if __name__ == "__main__":
    unittest.main()
