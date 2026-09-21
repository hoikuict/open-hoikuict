from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import date
import html
import os
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from sqlalchemy import event, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import Session, SQLModel, create_engine

from auth import LOCAL_STAFF_SESSION_COOKIE, Role, StaffUser
from csrf import CSRF_COOKIE_NAME, CsrfTokenMiddleware
import family_deletion as deletion
from family_support import bootstrap_family_data
from models import (
    BillingClaim, BillingCycle, BillingPaymentMethod, Child, ChildStatus, Family,
    FamilyBillingProfile, FamilyBillingProfileChangeLog, ParentAccount,
    ParentAccountStatus, ParentEnrollment, ParentRegistrationRequest, ProfilePhoto, Survey, SurveyAnswer, User,
    ZenginExport, ZenginExportLine,
)
import routers.families as families_module


class FamilyDeletionTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, {
            "HOIKUICT_ENV": "test", "HOIKUICT_STAFF_AUTH_MODE": "local_password",
            "HOIKUICT_COOKIE_SECURE": "0", "HOIKUICT_CSRF_ENFORCE": "1",
            "HOIKUICT_SECRET_KEY": "family-deletion-synthetic-test-key-0123456789",
        })
        self.environment.start()
        self.tmp = tempfile.TemporaryDirectory(prefix="hoikuict-family-delete-")
        self.engine = create_engine("sqlite:///" + (Path(self.tmp.name) / "test.sqlite").as_posix(),
                                    connect_args={"check_same_thread": False, "timeout": 2})

        @event.listens_for(self.engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        with self.engine.connect() as connection:
            connection.exec_driver_sql("PRAGMA journal_mode=WAL")
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            user = User(email="manager@example.invalid", display_name="架空の台帳担当", can_manage_child_records=True)
            session.add(user)
            session.flush()
            self.user_id = user.id
            session.add(Family(id=101, family_name="あおぞら家", home_address="架空住所", home_phone="000-0000-0000",
                               shared_profile={"guardians": [{"order": 1, "last_name": "青空", "first_name": "はるか",
                                "email": "haruka@example.invalid", "workplace": "架空事業所"}]}))
            session.add(Family(id=102, family_name="あおぞら家"))
            session.commit()
        self.current_user = StaffUser(role=Role.CAN_EDIT, name="架空の台帳担当", user_id=self.user_id,
                                      can_manage_child_records=True)
        self.app = FastAPI()
        self.app.add_middleware(CsrfTokenMiddleware)
        self.app.include_router(families_module.router)
        self.app.mount("/static", StaticFiles(directory="static"), name="static")

        def get_session():
            with Session(self.engine) as session:
                yield session
        self.app.dependency_overrides[families_module.get_session] = get_session
        self.app.dependency_overrides[families_module.get_current_staff_user] = lambda: self.current_user
        self.client = TestClient(self.app)
        self.client.cookies.set(LOCAL_STAFF_SESSION_COOKIE, "synthetic-session")

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        self.tmp.cleanup()
        self.environment.stop()

    def review(self, family_id=101, q=""):
        return self.client.get(f"/families/{family_id}/delete", params={"q": q})

    def token(self, family_id=101):
        response = self.review(family_id)
        self.assertEqual(response.status_code, 200)
        token = re.search(r'name="review_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(token, response.text)
        return html.unescape(token.group(1))

    def submit(self, token, family_id=101, **changes):
        fields = {"review_token": token, "confirmed": "yes", "csrf_token": self.client.cookies.get(CSRF_COOKIE_NAME)}
        fields.update(changes)
        return self.client.post(f"/families/{family_id}/delete", data=fields, follow_redirects=False)

    def assert_family_exists(self, family_id=101):
        with Session(self.engine) as session:
            self.assertIsNotNone(session.get(Family, family_id))

    @staticmethod
    def child(family_id=101, status=ChildStatus.enrolled):
        return Child(last_name="青空", first_name="ひなた", last_name_kana="アオゾラ", first_name_kana="ヒナタ",
                     birth_date=date(2023, 1, 1), enrollment_date=date(2026, 4, 1), family_id=family_id, status=status)

    def test_review_cancel_and_success_preserve_duplicate_and_search(self):
        response = self.review(q="あおぞら & /?")
        self.assertEqual(response.status_code, 200)
        self.assertIn("private, no-store", response.headers["cache-control"])
        self.assertIn("F-00101", response.text)
        self.assertIn("haruka@example.invalid", response.text)
        self.assertIn("架空事業所", response.text)
        self.assert_family_exists()
        token = self.token()
        with self.assertLogs("uvicorn.error.family_deletion", level="INFO") as logs:
            response = self.submit(token, q="あおぞら & /?")
        self.assertEqual(response.status_code, 303, response.text)
        self.assertNotIn("haruka", " ".join(logs.output))
        self.assertNotIn("あおぞら", " ".join(logs.output))
        self.assertIn("result=deleted", " ".join(logs.output))
        self.assertNotIn("あおぞら", response.headers["location"])
        result = self.client.get(response.headers["location"])
        self.assertEqual(result.status_code, 200)
        self.assertIn("あおぞら家（F-00101）を削除しました。", result.text)
        self.assertIn('value="あおぞら &amp; /?"', result.text)
        self.assertNotIn("を削除しました。", self.client.get("/families/").text)
        with Session(self.engine) as session:
            self.assertIsNone(session.get(Family, 101))
            self.assertIsNotNone(session.get(Family, 102))
            bootstrap_family_data(session)
            session.commit()
            self.assertIsNone(session.get(Family, 101))

    def test_family_code_search_and_no_family_name_in_notice_url(self):
        response = self.client.get("/families/", params={"q": "F-00101"})
        self.assertIn("F-00101を削除", response.text)
        self.assertNotIn("F-00102を削除", response.text)
        response = self.submit(self.token())
        self.assertEqual(response.headers["location"], "/families/")
        self.assertIn("HttpOnly", response.headers["set-cookie"])

    def test_no_confirmation_or_invalid_csrf_cannot_delete(self):
        token = self.token()
        self.assertEqual(self.submit(token, confirmed="").status_code, 400)
        self.assertEqual(self.submit(token, csrf_token="bad").status_code, 403)
        self.assert_family_exists()

    def test_tampered_expired_or_other_family_confirmation_cannot_delete(self):
        token = self.token()
        for invalid in ("", token[:-1] + ("a" if token[-1] != "a" else "b"), "あ.あ"):
            with self.subTest(token=invalid[:10]):
                self.assertEqual(self.submit(invalid).status_code, 409)
        self.assertEqual(self.submit(token, family_id=102).status_code, 409)
        with patch("family_deletion.time", return_value=10**11):
            self.assertEqual(self.submit(token).status_code, 409)
        self.assert_family_exists()
        self.assert_family_exists(102)

    def test_confirmation_bound_to_session(self):
        token = self.token()
        self.client.cookies.set(LOCAL_STAFF_SESSION_COOKIE, "replacement-session")
        self.assertEqual(self.submit(token).status_code, 409)
        self.assert_family_exists()

    def test_confirmation_bound_to_staff_identity(self):
        token = self.token()
        with Session(self.engine) as session:
            actor = User(email="second@example.invalid", display_name="別の架空職員", can_manage_child_records=True)
            session.add(actor)
            session.commit()
            actor_id = actor.id
        self.current_user = StaffUser(role=Role.CAN_EDIT, name="別の架空職員", user_id=actor_id, can_manage_child_records=True)
        self.assertEqual(self.submit(token).status_code, 409)
        self.assert_family_exists()

    def test_live_permission_revocation_and_disabled_user(self):
        token = self.token()
        for change in ("can_manage_child_records", "is_active"):
            with self.subTest(change=change):
                with Session(self.engine) as session:
                    user = session.get(User, self.user_id)
                    user.can_manage_child_records = user.is_active = True
                    setattr(user, change, False)
                    session.commit()
                self.assertEqual(self.review().status_code, 403)
                self.assertEqual(self.submit(token).status_code, 403)
        self.assert_family_exists()

    def test_viewer_cannot_delete_or_see_delete_links(self):
        token = self.token()
        self.current_user = StaffUser(role=Role.VIEW_ONLY, user_id=self.user_id)
        self.assertEqual(self.review().status_code, 403)
        self.assertEqual(self.submit(token).status_code, 403)
        self.assertNotIn('aria-label="F-00101を削除"', self.client.get("/families/").text)
        self.assert_family_exists()

    def test_changed_family_is_shown_again_without_confirmation(self):
        token = self.token()
        with Session(self.engine) as session:
            family = session.get(Family, 101)
            family.home_address = "更新された架空住所"
            # Deliberately leave updated_at unchanged: inspect all saved fields.
            session.commit()
        response = self.submit(token)
        self.assertEqual(response.status_code, 409)
        self.assertIn("確認後に家族情報が変更", response.text)
        self.assertIn("更新された架空住所", response.text)
        self.assertNotIn('value="yes" checked', response.text)
        self.assert_family_exists()

    def test_new_child_after_review_blocks_deletion(self):
        token = self.token()
        with Session(self.engine) as session:
            session.add(self.child())
            session.commit()
        response = self.submit(token)
        self.assertEqual(response.status_code, 409)
        self.assertNotIn('name="review_token"', response.text)
        self.assert_family_exists()

    def test_graduated_and_withdrawn_children_are_protected(self):
        for status in (ChildStatus.graduated, ChildStatus.withdrawn):
            with self.subTest(status=status), Session(self.engine) as session:
                child = self.child(status=status)
                session.add(child)
                session.commit()
                response = self.review()
                self.assertIn("この家族は削除できません", response.text)
                self.assertNotIn('name="review_token"', response.text)
                session.delete(child)
                session.commit()

    def test_stopped_parent_account_is_protected(self):
        with Session(self.engine) as session:
            account = ParentAccount(display_name="架空保護者", email="parent@example.invalid", family_id=101,
                                    status=ParentAccountStatus.inactive)
            session.add(account)
            session.commit()
        self.assertIn("この家族は削除できません", self.review().text)

    def test_all_financial_and_survey_references_are_protected(self):
        with Session(self.engine) as session:
            cycle = BillingCycle(year_month="2026-09", period_start=date(2026,9,1), period_end=date(2026,9,30), withdrawal_date=date(2026,10,1))
            survey = Survey(title="架空アンケート")
            session.add_all([cycle, survey])
            session.flush()
            claim = BillingClaim(family_id=102, billing_cycle_id=cycle.id, payment_method=BillingPaymentMethod.cash)
            export = ZenginExport(billing_cycle_id=cycle.id, withdrawal_date=date(2026,10,1), file_name="synthetic.txt", content_hash="synthetic", created_by="架空管理者")
            session.add_all([claim, export])
            session.commit()
            factories = [
                lambda: FamilyBillingProfile(family_id=101, customer_number="synthetic"),
                lambda: BillingClaim(family_id=101, billing_cycle_id=cycle.id, payment_method=BillingPaymentMethod.cash),
                lambda: ZenginExportLine(family_id=101, billing_claim_id=claim.id, zengin_export_id=export.id, customer_number="synthetic", amount=0),
                lambda: FamilyBillingProfileChangeLog(family_id=101, changed_by_name_snapshot="架空管理者"),
                lambda: SurveyAnswer(family_id=101, survey_id=survey.id),
            ]
            for make in factories:
                record = make()
                with self.subTest(record=type(record).__name__):
                    session.add(record)
                    session.commit()
                    response = self.review()
                    self.assertIn("この家族は削除できません", response.text)
                    self.assertNotIn('name="review_token"', response.text)
                    session.delete(record)
                    session.commit()

    def test_photos_and_json_links_are_protected(self):
        with Session(self.engine) as session:
            photo = ProfilePhoto(family_id=101, content=b"synthetic")
            session.add(photo)
            session.commit()
            self.assertIn("この家族は削除できません", self.review().text)
            session.delete(photo)
            session.commit()
            for link in ({"photo_id": "stale-photo"}, {"parent_account_id": 987}):
                with self.subTest(link=link):
                    family = session.get(Family, 101)
                    family.shared_profile = {"guardians": [{"order": 1, **link}]}
                    session.commit()
                    self.assertIn("この家族は削除できません", self.review().text)

    def test_future_cascading_foreign_key_is_blocked(self):
        token = self.token()
        with self.engine.begin() as connection:
            connection.execute(text("CREATE TABLE future_family_records (id INTEGER PRIMARY KEY, owner_family INTEGER REFERENCES families(id) ON DELETE CASCADE)"))
            connection.execute(text("INSERT INTO future_family_records(owner_family) VALUES (101)"))
        response = self.submit(token)
        self.assertEqual(response.status_code, 409)
        self.assertIn("その他の関連記録", response.text)
        with self.engine.connect() as connection:
            self.assertEqual(connection.execute(text("SELECT COUNT(*) FROM future_family_records")).scalar_one(), 1)

    def test_enrollment_json_reference_is_protected(self):
        token = self.token()
        with Session(self.engine) as session:
            parent = ParentAccount(display_name="初回入力用保護者", email="intake@example.invalid")
            session.add(parent)
            session.flush()
            invitation = ParentRegistrationRequest(parent_account_id=parent.id, email_normalized_snapshot=parent.email)
            session.add(invitation)
            session.flush()
            session.add(ParentEnrollment(registration_request_id=invitation.id, child_name="架空園児",
                                          source_snapshot={"family_id": 101}))
            session.commit()
        response = self.submit(token)
        self.assertEqual(response.status_code, 409)
        self.assertIn("保護者の初回入力依頼・記録", response.text)
        self.assert_family_exists()

    def test_database_failure_rolls_back(self):
        token = self.token()
        with patch.object(Session, "commit", side_effect=OperationalError("COMMIT", {}, Exception("synthetic failure"))):
            response = self.submit(token)
        self.assertEqual(response.status_code, 503)
        self.assertIn("削除できませんでした", response.text)
        self.assert_family_exists()

    def test_repeat_and_reused_id_do_not_delete_another_family(self):
        token = self.token(102)
        self.assertEqual(self.submit(token, family_id=102).status_code, 303)
        self.assertEqual(self.submit(token, family_id=102).status_code, 404)
        with Session(self.engine) as session:
            session.add(Family(id=102, family_name="新しい家族"))
            session.commit()
        self.assertEqual(self.submit(token, family_id=102).status_code, 409)
        self.assert_family_exists(102)

    def test_parallel_writer_cannot_link_during_deletion(self):
        with Session(self.engine) as session:
            session.add(self.child(family_id=102))
            session.commit()
        token = self.token()
        inspected, resume = threading.Event(), threading.Event()
        original = deletion.dependency_counts

        def hold_inspection(session, family):
            result = original(session, family)
            inspected.set()
            self.assertTrue(resume.wait(5))
            return result

        with ThreadPoolExecutor(max_workers=1) as pool, patch.object(deletion, "dependency_counts", side_effect=hold_inspection):
            future = pool.submit(self.submit, token)
            self.assertTrue(inspected.wait(5))
            try:
                with self.engine.connect() as connection:
                    connection.exec_driver_sql("PRAGMA busy_timeout=50")
                    with self.assertRaises(OperationalError):
                        connection.execute(text("UPDATE children SET family_id=101 WHERE family_id=102"))
            finally:
                resume.set()
            self.assertEqual(future.result(5).status_code, 303)
        with self.engine.connect() as connection:
            self.assertEqual(connection.exec_driver_sql("PRAGMA foreign_key_check").all(), [])
            self.assertEqual(connection.execute(text("SELECT family_id FROM children")).scalar_one(), 102)
            with self.assertRaises(IntegrityError):
                connection.execute(text("UPDATE children SET family_id=101 WHERE family_id=102"))


if __name__ == "__main__":
    unittest.main()
