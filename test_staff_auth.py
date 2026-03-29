import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from auth import MOCK_ROLE_COOKIE, MOCK_STAFF_ID_COOKIE, Role
from models import Staff, StaffEmploymentType, StaffStatus
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
            session.add(
                Staff(
                    full_name="Admin User",
                    display_name="Admin",
                    role=Role.ADMIN,
                    status=StaffStatus.active,
                    employment_type=StaffEmploymentType.regular,
                )
            )
            session.add(
                Staff(
                    full_name="Editor User",
                    display_name="Editor",
                    role=Role.CAN_EDIT,
                    status=StaffStatus.active,
                    employment_type=StaffEmploymentType.regular,
                )
            )
            session.add(
                Staff(
                    full_name="Viewer User",
                    display_name="Viewer",
                    role=Role.VIEW_ONLY,
                    status=StaffStatus.active,
                    employment_type=StaffEmploymentType.part_time,
                )
            )
            session.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_login_page_renders_role_forms(self):
        response = self.client.get("/staff/login?redirect=/staff-rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/staff/login"', response.text)
        self.assertIn('name="redirect_to" value="/staff-rooms/"', response.text)
        self.assertIn('name="role" value="can_edit"', response.text)
        self.assertIn('name="role" value="admin"', response.text)
        self.assertIn('name="role" value="view_only"', response.text)

    def test_login_sets_staff_session_and_redirects(self):
        response = self.client.post(
            "/staff/login",
            data={"role": "admin", "redirect_to": "/staff-rooms/"},
            follow_redirects=False,
        )

        cookies = response.headers.get("set-cookie", "")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff-rooms/")
        self.assertIn(f"{MOCK_ROLE_COOKIE}=admin", cookies)
        self.assertIn(f"{MOCK_STAFF_ID_COOKIE}=1", cookies)

    def test_logout_clears_staff_session_and_redirects_to_login(self):
        response = self.client.post(
            "/staff/logout",
            data={"redirect_to": "/staff/login"},
            follow_redirects=False,
        )

        cookies = response.headers.get("set-cookie", "")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff/login")
        self.assertIn(f"{MOCK_ROLE_COOKIE}=", cookies)
        self.assertIn(f"{MOCK_STAFF_ID_COOKIE}=", cookies)


if __name__ == "__main__":
    unittest.main()
