import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from auth import MOCK_ROLE_COOKIE
import routers.staff_auth as staff_auth_module


class StaffAuthRouterTests(unittest.TestCase):
    def setUp(self):
        self.app = FastAPI()
        self.app.include_router(staff_auth_module.router)
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()

    def test_login_page_renders_role_forms(self):
        response = self.client.get("/staff/login?redirect=/staff-rooms/")

        self.assertEqual(response.status_code, 200)
        self.assertIn('action="/staff/login"', response.text)
        self.assertIn('name="redirect_to" value="/staff-rooms/"', response.text)
        self.assertIn("職員ログイン", response.text)
        self.assertIn("編集可", response.text)
        self.assertIn("管理者", response.text)
        self.assertIn("閲覧のみ", response.text)

    def test_login_sets_role_cookie_and_redirects(self):
        response = self.client.post(
            "/staff/login",
            data={"role": "admin", "redirect_to": "/staff-rooms/"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff-rooms/")
        self.assertIn(f"{MOCK_ROLE_COOKIE}=admin", response.headers.get("set-cookie", ""))

    def test_logout_returns_to_view_only_and_redirects_to_login(self):
        response = self.client.post(
            "/staff/logout",
            data={"redirect_to": "/staff/login"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/staff/login")
        self.assertIn(f"{MOCK_ROLE_COOKIE}=view_only", response.headers.get("set-cookie", ""))


if __name__ == "__main__":
    unittest.main()
