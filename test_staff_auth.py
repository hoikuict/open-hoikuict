import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import (
    MOCK_CALENDAR_USER_COOKIE,
    MOCK_CHILD_RECORDS_PERMISSION_COOKIE,
    MOCK_ROLE_COOKIE,
    MOCK_STAFF_NAME_COOKIE,
)
import database
from models import (
    USER_SOURCE_LOCAL_SAMPLE,
    USER_SOURCE_MANUAL,
    USER_SOURCE_WEB_DEMO,
    Classroom,
    StaffClassroomAssignment,
    StaffClassroomAssignmentRole,
    StaffPermissionChangeLog,
    User,
)
import routers.staff_auth as staff_auth_module
from testing_helpers import configure_test_environment


class StaffAuthRouterTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(staff_auth_module.router)
        self.app.include_router(staff_auth_module.mock_login_router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[staff_auth_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            self.principal = User(
                email="principal@example.com",
                display_name="園長",
                staff_role="admin",
                staff_sort_order=10,
                is_calendar_admin=True,
            )
            self.part_timer = User(
                email="part@example.com",
                display_name="早番パート",
                staff_role="view_only",
                staff_sort_order=150,
                is_calendar_admin=False,
            )
            self.external_user = User(
                email="external@example.com",
                display_name="外部確認用",
                staff_role="view_only",
                staff_sort_order=220,
                is_calendar_admin=False,
            )
            session.add(self.principal)
            session.add(self.part_timer)
            session.add(self.external_user)
            session.commit()
            self.principal_id = self.principal.id
            self.part_timer_id = self.part_timer.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _login_admin(self):
        response = self.client.post(
            "/staff/login",
            data={"user_id": str(self.principal_id), "redirect_to": "/staff/users"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_login_page_renders_staff_cards(self):
        response = self.client.get("/staff/login?redirect=/staff-rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/staff/login"', response.text)
        self.assertIn('name="redirect_to" value="/staff-rooms/"', response.text)
        self.assertEqual(response.text.count('name="user_id"'), 2)
        self.assertIn("職員ログイン", response.text)
        self.assertIn("未ログイン", response.text)
        self.assertIn("職員を選択する", response.text)
        self.assertLess(response.text.index("職員を選択する"), response.text.index("基本業務"))
        self.assertIn("園長", response.text)
        self.assertIn("早番パート", response.text)
        self.assertNotIn("外部確認用", response.text)
        self.assertIn("管理者", response.text)
        self.assertIn("閲覧のみ", response.text)
        self.assertIn("園児台帳管理", response.text)

    def test_login_sets_staff_and_calendar_cookies_and_redirects(self):
        response = self.client.post(
            "/staff/login",
            data={"user_id": str(self.principal_id), "redirect_to": "/staff-rooms/"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff-rooms/")
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn(f"{MOCK_ROLE_COOKIE}=admin", set_cookie)
        self.assertIn(f"{MOCK_STAFF_NAME_COOKIE}=", set_cookie)
        self.assertIn(f"{MOCK_CALENDAR_USER_COOKIE}=", set_cookie)
        self.assertIn(f"{MOCK_CHILD_RECORDS_PERMISSION_COOKIE}=1", set_cookie)

    def test_non_admin_login_from_staff_management_redirects_to_portal_home(self):
        with Session(self.engine) as session:
            teacher = User(
                email="teacher@example.com",
                display_name="ひよこ組担任",
                staff_role="can_edit",
                staff_sort_order=60,
            )
            session.add(teacher)
            session.commit()
            teacher_id = teacher.id

        response = self.client.post(
            "/staff/login",
            data={
                "user_id": str(teacher_id),
                "redirect_to": f"/staff/users/{teacher_id}/classrooms",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/")

    def test_logout_clears_staff_and_calendar_cookies(self):
        self.client.post(
            "/staff/login",
            data={"user_id": str(self.principal_id), "redirect_to": "/staff-rooms/"},
            follow_redirects=False,
        )

        response = self.client.post(
            "/staff/logout",
            data={"redirect_to": "/staff/login"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff/login")
        set_cookie = response.headers.get("set-cookie", "")
        self.assertIn(f"{MOCK_ROLE_COOKIE}=", set_cookie)
        self.assertIn(f"{MOCK_STAFF_NAME_COOKIE}=", set_cookie)
        self.assertIn(f"{MOCK_CALENDAR_USER_COOKIE}=", set_cookie)
        self.assertIn(f"{MOCK_CHILD_RECORDS_PERMISSION_COOKIE}=", set_cookie)

        login_page = self.client.get("/staff/login")
        self.assertEqual(login_page.status_code, 200)
        self.assertIn("未ログイン", login_page.text)
        self.assertNotIn("ログイン中</p>\n          <p class=\"mt-2 text-base font-semibold\">園長", login_page.text)

    def test_default_login_and_logout_return_to_portal_home(self):
        login_response = self.client.post(
            "/staff/login",
            data={"user_id": str(self.principal_id), "redirect_to": "/"},
            follow_redirects=False,
        )
        self.assertEqual(login_response.status_code, 303)
        self.assertEqual(login_response.headers["location"], "/")

        logout_response = self.client.post(
            "/staff/logout",
            data={"redirect_to": "/"},
            follow_redirects=False,
        )
        self.assertEqual(logout_response.status_code, 303)
        self.assertEqual(logout_response.headers["location"], "/")

    def test_seed_calendar_data_restores_full_staff_users(self):
        original_engine = database.engine
        database.engine = self.engine
        try:
            database.seed_calendar_data()
        finally:
            database.engine = original_engine

        with Session(self.engine) as session:
            staff_users = session.exec(
                select(User)
                .where(User.is_active.is_(True), User.staff_sort_order < 200)
                .order_by(User.staff_sort_order, User.display_name)
            ).all()

        self.assertEqual(len(staff_users), 19)
        names = [user.display_name for user in staff_users]
        self.assertIn("看護師", names)
        self.assertIn("ぞう組担任B", names)
        self.assertIn("早番パート", names)
        self.assertIn("遅番パート", names)
        office = next(user for user in staff_users if user.display_name == "事務")
        self.assertTrue(office.can_manage_child_records)
        self.assertTrue(all(user.provisioning_source == USER_SOURCE_LOCAL_SAMPLE for user in staff_users))

    def test_seed_calendar_data_skips_local_staff_when_web_demo_users_exist(self):
        with Session(self.engine) as session:
            session.add_all(
                [
                    User(
                        email="principal@demo.open-hoikuict.example",
                        display_name="園長",
                        staff_role="admin",
                        staff_sort_order=10,
                        provisioning_source=USER_SOURCE_WEB_DEMO,
                        is_calendar_admin=True,
                    ),
                    User(
                        email="chief@demo.open-hoikuict.example",
                        display_name="主任",
                        staff_role="admin",
                        staff_sort_order=20,
                        provisioning_source=USER_SOURCE_WEB_DEMO,
                        is_calendar_admin=True,
                    ),
                    User(
                        email="chief@example.com",
                        display_name="主任",
                        staff_role="admin",
                        staff_sort_order=20,
                        provisioning_source=USER_SOURCE_LOCAL_SAMPLE,
                        is_calendar_admin=True,
                    ),
                ]
            )
            session.commit()

        original_engine = database.engine
        database.engine = self.engine
        try:
            database.seed_calendar_data()
        finally:
            database.engine = original_engine

        with Session(self.engine) as session:
            local_principal = session.exec(
                select(User).where(User.email == "principal@example.com")
            ).first()
            local_chief = session.exec(
                select(User).where(User.email == "chief@example.com")
            ).first()
            demo_principal = session.exec(
                select(User).where(User.email == "principal@demo.open-hoikuict.example")
            ).first()

        self.assertEqual(local_principal.provisioning_source, USER_SOURCE_MANUAL)
        self.assertIsNotNone(local_chief)
        self.assertFalse(local_chief.is_active)
        self.assertIsNotNone(demo_principal)
        self.assertEqual(demo_principal.provisioning_source, USER_SOURCE_WEB_DEMO)

    def test_new_staff_business_permissions_default_to_disabled(self):
        self._login_admin()

        response = self.client.post(
            "/staff/users",
            data={
                "display_name": "台帳担当",
                "email": "records@example.com",
                "staff_role": "can_edit",
                "can_manage_child_records": "1",
                "staff_sort_order": "45",
                "is_active": "1",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            user = session.exec(select(User).where(User.email == "records@example.com")).first()
        self.assertIsNotNone(user)
        self.assertEqual(
            response.headers["location"],
            f"/staff/users/{user.id}/authentication",
        )
        self.assertEqual(user.staff_role, "can_edit")
        self.assertFalse(user.can_manage_child_records)
        self.assertEqual(user.provisioning_source, USER_SOURCE_MANUAL)

    def test_admin_can_filter_staff_users_by_source(self):
        with Session(self.engine) as session:
            session.add(
                User(
                    email="principal@demo.open-hoikuict.example",
                    display_name="デモ園長",
                    staff_role="admin",
                    staff_sort_order=10,
                    provisioning_source=USER_SOURCE_WEB_DEMO,
                    is_calendar_admin=True,
                )
            )
            session.commit()

        self._login_admin()

        response = self.client.get("/staff/users")
        self.assertEqual(response.status_code, 200)
        self.assertIn("手動追加", response.text)
        self.assertIn("WEB公開デモ", response.text)
        self.assertIn("デモ園長", response.text)
        self.assertNotIn("早番パート", response.text)

        all_response = self.client.get("/staff/users?source=all")
        self.assertEqual(all_response.status_code, 200)
        self.assertIn("デモ園長", all_response.text)
        self.assertIn("早番パート", all_response.text)

        filtered_response = self.client.get("/staff/users?source=web_demo")
        self.assertEqual(filtered_response.status_code, 200)
        self.assertIn("デモ園長", filtered_response.text)
        self.assertNotIn("早番パート", filtered_response.text)

    def test_admin_can_manage_billing_account_permission_from_central_page(self):
        with Session(self.engine) as session:
            office = User(
                email="office-permission@example.com",
                display_name="事務担当",
                staff_role="can_edit",
                staff_sort_order=40,
            )
            session.add(office)
            session.commit()
            office_id = office.id

        self._login_admin()
        page = self.client.get("/staff/permissions")

        self.assertEqual(page.status_code, 200)
        self.assertIn("職員権限設定", page.text)
        self.assertIn("請求・口座情報管理", page.text)
        self.assertIn("事務担当", page.text)

        response = self.client.post(
            f"/staff/permissions/{office_id}",
            data={
                "staff_role": "can_edit",
                "can_manage_child_records": "1",
                "can_manage_billing_accounts": "1",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertIn("message=", response.headers["location"])
        with Session(self.engine) as session:
            office = session.get(User, office_id)
            logs = session.exec(
                select(StaffPermissionChangeLog).where(
                    StaffPermissionChangeLog.target_user_id == office_id
                )
            ).all()
        self.assertTrue(office.can_manage_child_records)
        self.assertTrue(office.can_manage_billing_accounts)
        self.assertEqual(
            {log.permission_key for log in logs},
            {"can_manage_child_records", "can_manage_billing_accounts"},
        )
        self.assertTrue(all(log.changed_by_user_id == self.principal_id for log in logs))

    def test_view_only_role_clears_business_permissions(self):
        with Session(self.engine) as session:
            staff = User(
                email="limited@example.com",
                display_name="権限変更対象",
                staff_role="can_edit",
                can_manage_child_records=True,
                can_manage_billing_accounts=True,
            )
            session.add(staff)
            session.commit()
            staff_id = staff.id

        self._login_admin()
        response = self.client.post(
            f"/staff/permissions/{staff_id}",
            data={
                "staff_role": "view_only",
                "can_manage_child_records": "1",
                "can_manage_billing_accounts": "1",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            staff = session.get(User, staff_id)
        self.assertEqual(staff.staff_role, "view_only")
        self.assertFalse(staff.can_manage_child_records)
        self.assertFalse(staff.can_manage_billing_accounts)

    def test_non_admin_cannot_open_or_update_permissions(self):
        response = self.client.post(
            "/staff/login",
            data={"user_id": str(self.part_timer_id), "redirect_to": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        page = self.client.get("/staff/permissions")
        update = self.client.post(
            f"/staff/permissions/{self.principal_id}",
            data={"staff_role": "admin"},
        )

        self.assertEqual(page.status_code, 403)
        self.assertEqual(update.status_code, 403)

    def test_non_admin_cannot_manage_staff_authentication(self):
        response = self.client.post(
            "/staff/login",
            data={"user_id": str(self.part_timer_id), "redirect_to": "/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        page = self.client.get(
            f"/staff/users/{self.principal_id}/authentication"
        )
        reset = self.client.post(
            f"/staff/users/{self.principal_id}/authentication/reset",
            data={"reason": "不正な操作"},
        )
        self.assertEqual(page.status_code, 403)
        self.assertEqual(reset.status_code, 403)

    def test_admin_can_add_staff_classroom_assignment(self):
        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.commit()
            classroom_id = classroom.id

        self._login_admin()
        response = self.client.post(
            f"/staff/users/{self.principal_id}/classrooms",
            data={
                "classroom_id": str(classroom_id),
                "assignment_role": "primary",
                "starts_on": "2026-04-01",
                "ends_on": "",
                "is_primary": "1",
                "display_order": "10",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(
            response.headers["location"],
            f"/staff/users/{self.principal_id}/classrooms",
        )
        with Session(self.engine) as session:
            assignment = session.exec(
                select(StaffClassroomAssignment).where(
                    StaffClassroomAssignment.staff_user_id == self.principal_id
                )
            ).one()
        self.assertEqual(assignment.classroom_id, classroom_id)
        self.assertEqual(assignment.assignment_role, StaffClassroomAssignmentRole.primary)
        self.assertTrue(assignment.is_primary)

        page = self.client.get(f"/staff/users/{self.principal_id}/classrooms")
        self.assertEqual(page.status_code, 200)
        self.assertIn("ひよこ組", page.text)
        self.assertIn("主担当", page.text)

    def test_assignment_period_overlap_is_rejected(self):
        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.flush()
            session.add(
                StaffClassroomAssignment(
                    staff_user_id=self.principal_id,
                    classroom_id=classroom.id,
                    starts_on=staff_auth_module.local_today(),
                )
            )
            session.commit()
            classroom_id = classroom.id

        self._login_admin()
        response = self.client.post(
            f"/staff/users/{self.principal_id}/classrooms",
            data={
                "classroom_id": str(classroom_id),
                "assignment_role": "support",
                "starts_on": staff_auth_module.local_today().isoformat(),
                "ends_on": "",
                "display_order": "20",
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("担当期間が重複しています", response.text)
        self.assertIn("別の職員を選んで追加してください", response.text)

    def test_same_class_can_be_assigned_to_multiple_staff(self):
        with Session(self.engine) as session:
            classroom = Classroom(name="りす組（1歳児）", display_order=2)
            second_staff = User(
                email="second-teacher@example.com",
                display_name="りす組担任B",
                staff_role="can_edit",
                staff_sort_order=71,
            )
            session.add_all([classroom, second_staff])
            session.commit()
            classroom_id = classroom.id
            second_staff_id = second_staff.id

        self._login_admin()
        for staff_user_id in (self.principal_id, second_staff_id):
            response = self.client.post(
                f"/staff/users/{staff_user_id}/classrooms",
                data={
                    "classroom_id": str(classroom_id),
                    "assignment_role": "primary",
                    "starts_on": "2026-04-01",
                    "ends_on": "",
                    "display_order": "10",
                },
                follow_redirects=False,
            )
            self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            assignments = session.exec(
                select(StaffClassroomAssignment).where(
                    StaffClassroomAssignment.classroom_id == classroom_id
                )
            ).all()

        self.assertEqual(len(assignments), 2)
        self.assertEqual(
            {item.staff_user_id for item in assignments},
            {self.principal_id, second_staff_id},
        )

    def test_seed_assigns_multiple_homeroom_staff_with_age_labelled_class_name(self):
        with Session(self.engine) as session:
            classroom = Classroom(name="りす組（1歳児）", display_order=2)
            teachers = [
                User(
                    email=f"risu-{suffix}@demo.example.com",
                    display_name=f"りす組担任{suffix}",
                    staff_role="can_edit",
                    staff_sort_order=70 + index,
                    provisioning_source=USER_SOURCE_WEB_DEMO,
                )
                for index, suffix in enumerate(("A", "B"))
            ]
            session.add(classroom)
            session.add_all(teachers)
            session.commit()
            classroom_id = classroom.id
            teacher_ids = {item.id for item in teachers}

        original_engine = database.engine
        database.engine = self.engine
        try:
            database.seed_staff_classroom_assignments()
        finally:
            database.engine = original_engine

        with Session(self.engine) as session:
            assignments = session.exec(
                select(StaffClassroomAssignment).where(
                    StaffClassroomAssignment.classroom_id == classroom_id
                )
            ).all()

        self.assertEqual(len(assignments), 2)
        self.assertEqual({item.staff_user_id for item in assignments}, teacher_ids)

    def test_admin_cannot_remove_own_last_admin_permission(self):
        self._login_admin()

        response = self.client.post(
            f"/staff/permissions/{self.principal_id}",
            data={"staff_role": "can_edit"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("自分自身の管理者権限はこの画面では外せません。", response.text)


if __name__ == "__main__":
    unittest.main()
