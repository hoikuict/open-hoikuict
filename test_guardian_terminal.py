import os
import unittest
from datetime import date
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware, verify_csrf
from database import get_session
from guardian_terminal import TERMINAL_COOKIE
from kiosk_security import KIOSK_DEVICE_COOKIE, kiosk_device_cookie_is_valid
from models import AttendanceRecord, Child, Classroom
from routers import guardian


class GuardianTerminalTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "HOIKUICT_ENV": "development", "HOIKUICT_KIOSK_ACCESS_MODE": "token",
            "HOIKUICT_KIOSK_TOKEN": "synthetic-terminal-token", "HOIKUICT_SECRET_KEY": "s" * 32,
            "HOIKUICT_COOKIE_SECURE": "0", "HOIKUICT_CSRF_ENFORCE": "1",
        })
        self.environment.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI(dependencies=[Depends(verify_csrf)])
        self.app.add_middleware(CsrfTokenMiddleware)
        self.app.include_router(guardian.router)

        def sessions():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[get_session] = sessions
        self.client = TestClient(self.app)
        with Session(self.engine) as session:
            room = Classroom(name="キオスク確認組")
            session.add(room)
            session.flush()
            child = Child(last_name="端末", first_name="確認", last_name_kana="タンマツ", first_name_kana="カクニン",
                          birth_date=date(2022, 4, 1), enrollment_date=date(2025, 4, 1), classroom_id=room.id)
            session.add(child)
            session.commit()
            self.child_id, self.room_id = child.id, room.id
        self.today = guardian.local_today().isoformat()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.environment.stop()

    def post(self, path, **data):
        return self.client.post(path, data={"csrf_token": self.client.cookies.get(CSRF_COOKIE_NAME), **data}, follow_redirects=False)

    def activate(self):
        self.client.get("/guardian/terminal")
        response = self.post("/guardian/activate", kiosk_token="synthetic-terminal-token")
        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/guardian/terminal")

    def test_terminal_registration_does_not_grant_access_without_device_token(self):
        page = self.client.get("/guardian/terminal")
        self.assertEqual(page.status_code, 200)
        self.assertIn('id="kiosk-token"', page.text)
        self.assertEqual(self.client.cookies.get(TERMINAL_COOKIE), "1")
        self.assertNotIn("キオスク確認組", page.text)
        self.assertEqual(self.client.get("/guardian/").status_code, 404)
        self.assertEqual(self.post("/guardian/activate", kiosk_token="wrong").status_code, 403)
        self.activate()
        self.assertTrue(kiosk_device_cookie_is_valid(self.client.cookies.get(KIOSK_DEVICE_COOKIE)))
        page = self.client.get("/guardian/terminal")
        self.assertIn("キオスク確認組", page.text)
        self.assertNotIn('id="staff-sidebar"', page.text)
        self.assertNotIn('href="/staff/', page.text)
        self.assertNotIn('href="/children', page.text)
        self.assertEqual(page.headers["cache-control"], "no-store")

    def test_terminal_always_displays_today_and_rejects_stale_posts(self):
        self.activate()
        page = self.client.get(f"/guardian/?date=2000-01-01&class_id={self.room_id}&child_id={self.child_id}")
        self.assertEqual(page.status_code, 200)
        self.assertNotIn('type="date"', page.text)
        self.assertIn(f'name="date" value="{self.today}"', page.text)
        for action in ("check-in", "pickup", "pickup/commit", "check-out", "check-out/commit"):
            response = self.post(f"/guardian/child/{self.child_id}/{action}", date="2000-01-01", class_id=self.room_id)
            self.assertEqual(response.status_code, 409, response.text)
            self.assertIn("日付が変わりました", response.text)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(AttendanceRecord)).all(), [])

    def test_terminal_flow_preserves_csrf_and_returns_to_start_after_checkout(self):
        self.activate()
        path = f"/guardian/child/{self.child_id}"
        denied = self.client.post(path + "/check-in", data={"date": self.today}, follow_redirects=False)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(self.post(path + "/check-in", date=self.today).status_code, 303)
        pickup = self.post(path + "/pickup/commit", date=self.today, planned_pickup_time="17:00", pickup_person="母")
        self.assertEqual(pickup.status_code, 200)
        self.assertIn('href="/guardian/terminal"', pickup.text)
        checkout = self.post(path + "/check-out/commit", date=self.today)
        self.assertEqual(checkout.status_code, 200)
        self.assertIn("降園を受け付けました", checkout.text)
        self.assertIn('href="/guardian/terminal"', checkout.text)
        with Session(self.engine) as session:
            record = session.exec(select(AttendanceRecord)).one()
            self.assertIsNotNone(record.check_out_at)
        self.assertEqual(self.post(path + "/check-out/commit", date=self.today).status_code, 400)

    def test_status_requires_registration_and_detects_revocation(self):
        self.assertEqual(self.client.get("/guardian/terminal/status").status_code, 404)
        self.activate()
        response = self.client.get("/guardian/terminal/status")
        self.assertEqual(response.json(), {"kiosk": True, "today": self.today})
        self.assertEqual(response.headers["cache-control"], "no-store")
        with patch.dict(os.environ, {"HOIKUICT_KIOSK_TOKEN": "rotated"}):
            self.assertEqual(self.client.get("/guardian/terminal/status").status_code, 404)
            self.assertIn('id="kiosk-token"', self.client.get("/guardian/terminal").text)

    def test_manifest_and_icons_are_available_without_exposing_children(self):
        response = self.client.get("/guardian/manifest.webmanifest")
        manifest = response.json()
        self.assertEqual(manifest["start_url"], "/guardian/terminal")
        self.assertEqual(manifest["scope"], "/guardian/")
        self.assertEqual(manifest["display"], "standalone")
        for icon in manifest["icons"]:
            image = self.client.get(icon["src"])
            self.assertEqual(image.status_code, 200)
            self.assertEqual(image.content[:8], b"\x89PNG\r\n\x1a\n")
            size = int(icon["sizes"].split("x")[0])
            self.assertEqual(int.from_bytes(image.content[16:20], "big"), size)
        self.assertEqual(self.client.get("/guardian/assets/unknown.txt").status_code, 404)

    def test_disabled_terminal_never_shows_children(self):
        with patch.dict(os.environ, {"HOIKUICT_KIOSK_ACCESS_MODE": "disabled"}):
            response = self.client.get("/guardian/terminal")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("キオスク確認組", response.text)
