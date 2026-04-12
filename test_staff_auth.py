import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import MOCK_CALENDAR_USER_COOKIE, MOCK_ROLE_COOKIE, MOCK_STAFF_NAME_COOKIE
from models import User
import routers.staff_auth as staff_auth_module


class StaffAuthRouterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(staff_auth_module.router)

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
                display_name="パート職員",
                staff_role="view_only",
                staff_sort_order=60,
                is_calendar_admin=False,
            )
            session.add(self.principal)
            session.add(self.part_timer)
            session.commit()
            self.principal_id = self.principal.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_login_page_renders_staff_cards(self):
        response = self.client.get("/staff/login?redirect=/staff-rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/staff/login"', response.text)
        self.assertIn('name="redirect_to" value="/staff-rooms/"', response.text)
        self.assertIn("職員ログイン", response.text)
        self.assertIn("園長", response.text)
        self.assertIn("パート職員", response.text)
        self.assertIn("管理者", response.text)
        self.assertIn("閲覧のみ", response.text)

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

    def test_logout_clears_staff_and_calendar_cookies(self):
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


if __name__ == "__main__":
    unittest.main()
