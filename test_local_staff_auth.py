import os
import io
import unittest
import re
from contextlib import redirect_stdout
from datetime import timedelta
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select
from starlette.exceptions import HTTPException as StarletteHTTPException

import database
from auth import (
    LOCAL_STAFF_SESSION_COOKIE,
    configure_auth_backends_from_environment,
    get_current_staff_user,
    reset_auth_backends,
    staff_auth_http_exception_handler,
)
from local_auth import (
    ACTION_CODE_ALPHABET,
    ACTION_CODE_LENGTH,
    ACTION_CODE_TTL_MINUTES,
    PasswordPolicyError,
    activate_staff_password,
    create_staff_credential,
    issue_existing_staff_activation,
    validate_new_password,
)
from models import (
    AuthenticationEvent,
    AuthSession,
    CredentialActionToken,
    LoginThrottle,
    PasswordCredential,
    StaffCredentialProvisioningAudit,
    User,
)
from routers.staff_auth import get_session, local_login_router, router
from scripts.auth_user import activate_existing_staff_command
from time_utils import utc_now


class LocalStaffAuthenticationTests(unittest.TestCase):
    PASSWORD = "correct horse battery staple 2026"

    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "test",
                "HOIKUICT_ENABLE_MOCK_AUTH": "0",
                "HOIKUICT_STAFF_AUTH_MODE": "local_password",
                "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "t" * 40,
                "HOIKUICT_COOKIE_SECURE": "0",
                "HOIKUICT_CSRF_ENFORCE": "0",
            },
        )
        self.environment.start()
        configure_auth_backends_from_environment()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.original_engine = database.engine
        database.engine = self.engine

        with Session(self.engine) as session:
            user = User(
                email="principal@example.com",
                display_name="園長",
                staff_role="admin",
                staff_sort_order=10,
                is_calendar_admin=True,
            )
            session.add(user)
            session.flush()
            credential, activation_code = create_staff_credential(
                session,
                user=user,
                login_id="principal",
            )
            session.commit()
            self.user_id = user.id
            self.credential_id = credential.id
            self.activation_code = activation_code

        self.app = FastAPI()
        self.app.add_exception_handler(
            StarletteHTTPException,
            staff_auth_http_exception_handler,
        )
        self.app.include_router(router)
        self.app.include_router(local_login_router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[get_session] = override_get_session

        @self.app.get("/protected")
        def protected(current_user=Depends(get_current_staff_user)):
            return {
                "name": current_user.name,
                "role": current_user.role.value,
            }

        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        database.engine = self.original_engine
        self.engine.dispose()
        reset_auth_backends()
        self.environment.stop()

    def _activate(self):
        with Session(self.engine) as session:
            activate_staff_password(
                session,
                activation_code=self.activation_code,
                password=self.PASSWORD,
                password_confirmation=self.PASSWORD,
            )

    def _login(self, *, redirect_to="/protected"):
        return self.client.post(
            "/staff/login",
            data={
                "login_id": "principal",
                "password": self.PASSWORD,
                "redirect_to": redirect_to,
            },
            follow_redirects=False,
        )

    def _action_code_from(self, response):
        match = re.search(
            r'id="credential-action-code"[^>]*>([^<]+)</code>',
            response.text,
        )
        self.assertIsNotNone(match)
        return match.group(1).strip()

    def test_login_form_has_no_staff_directory_and_uses_password_autocomplete(self):
        response = self.client.get("/staff/login")

        self.assertEqual(response.status_code, 200)
        self.assertIn('autocomplete="username"', response.text)
        self.assertIn('autocomplete="current-password"', response.text)
        self.assertNotIn("園長", response.text)
        self.assertEqual(response.headers["cache-control"], "private, no-store")

    def test_password_minimum_length_is_eight_characters(self):
        self.assertEqual(validate_new_password("Ab3!xyZ9"), "Ab3!xyZ9")
        with self.assertRaisesRegex(PasswordPolicyError, "8文字以上"):
            validate_new_password("Ab3!xyZ")

    def test_action_code_is_six_easy_to_read_characters_and_expires_in_30_minutes(self):
        self.assertEqual(len(self.activation_code), ACTION_CODE_LENGTH)
        self.assertTrue(set(self.activation_code) <= set(ACTION_CODE_ALPHABET))
        with Session(self.engine) as session:
            token = session.exec(
                select(CredentialActionToken).where(
                    CredentialActionToken.credential_id == self.credential_id
                )
            ).one()
        self.assertEqual(
            token.expires_at - token.created_at,
            timedelta(minutes=ACTION_CODE_TTL_MINUTES),
        )

    def test_activation_hashes_password_and_consumes_only_hashed_code(self):
        self._activate()

        with Session(self.engine) as session:
            credential = session.get(PasswordCredential, self.credential_id)
            token = session.get(
                CredentialActionToken,
                next(
                    item.token_hash
                    for item in session.exec(select(CredentialActionToken)).all()
                ),
            )
        self.assertTrue(credential.password_hash.startswith("$argon2id$"))
        self.assertNotIn(self.PASSWORD, credential.password_hash)
        self.assertIsNotNone(token.consumed_at)
        self.assertNotEqual(token.token_hash, self.activation_code)

    def test_existing_staff_can_receive_a_new_activation_code(self):
        with Session(self.engine) as session:
            user = session.get(User, self.user_id)
            _, new_code = issue_existing_staff_activation(
                session,
                user=user,
                login_id="principal",
                reason="既存DBへの認証導入",
                actor="実行者",
                approver="承認者",
            )
        self.assertNotEqual(new_code, self.activation_code)

        with Session(self.engine) as session:
            active_tokens = session.exec(
                select(CredentialActionToken).where(
                    CredentialActionToken.revoked_at.is_(None),
                    CredentialActionToken.consumed_at.is_(None),
                )
            ).all()
            audits = session.exec(select(StaffCredentialProvisioningAudit)).all()
            audit_operation = audits[0].operation
            activate_staff_password(
                session,
                activation_code=new_code,
                password=self.PASSWORD,
                password_confirmation=self.PASSWORD,
            )
        self.assertEqual(len(active_tokens), 1)
        self.assertEqual(len(audits), 1)
        self.assertEqual(audit_operation, "activation_reissued")

    def test_activate_staff_cli_prints_code_after_commit(self):
        output = io.StringIO()
        answers = ["1", "", "既存DBへの認証導入", "実行者", "承認者", "yes"]
        with patch("builtins.input", side_effect=answers), redirect_stdout(output):
            result = activate_existing_staff_command()

        self.assertEqual(result, 0)
        self.assertIn("園長 の有効化コードを発行しました", output.getvalue())
        self.assertIn("有効期限は30分です", output.getvalue())
        self.assertIn("/staff/activate", output.getvalue())

    def test_valid_login_sets_opaque_cookie_and_resolves_live_role(self):
        self._activate()
        response = self._login()

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers["location"], "/protected")
        raw_cookie = self.client.cookies.get(LOCAL_STAFF_SESSION_COOKIE)
        self.assertTrue(raw_cookie)
        self.assertNotIn(str(self.user_id), raw_cookie)
        self.assertEqual(
            self.client.get("/protected").json(),
            {"name": "園長", "role": "admin"},
        )

        with Session(self.engine) as session:
            user = session.get(User, self.user_id)
            user.staff_role = "view_only"
            session.add(user)
            session.commit()
        self.assertEqual(self.client.get("/protected").json()["role"], "view_only")

    def test_two_staff_can_stay_logged_in_in_separate_browser_sessions(self):
        self._activate()
        with Session(self.engine) as session:
            teacher = User(
                email="teacher@example.com",
                display_name="担任",
                staff_role="can_edit",
                staff_sort_order=50,
            )
            session.add(teacher)
            session.flush()
            _, teacher_code = create_staff_credential(
                session,
                user=teacher,
                login_id="teacher",
            )
            session.commit()
            activate_staff_password(
                session,
                activation_code=teacher_code,
                password="Maple!9274Blue",
                password_confirmation="Maple!9274Blue",
            )

        with TestClient(self.app) as second_browser:
            principal_login = self._login()
            teacher_login = second_browser.post(
                "/staff/login",
                data={
                    "login_id": "teacher",
                    "password": "Maple!9274Blue",
                    "redirect_to": "/protected",
                },
                follow_redirects=False,
            )

            self.assertEqual(principal_login.status_code, 303)
            self.assertEqual(teacher_login.status_code, 303)
            self.assertEqual(self.client.get("/protected").json()["name"], "園長")
            self.assertEqual(second_browser.get("/protected").json()["name"], "担任")

    def test_expired_login_throttle_window_is_reused_without_unique_error(self):
        first_failure = self.client.post(
            "/staff/login",
            data={"login_id": "principal", "password": "wrong"},
        )
        self.assertEqual(first_failure.status_code, 400)

        with Session(self.engine) as session:
            throttles = session.exec(select(LoginThrottle)).all()
            self.assertEqual(len(throttles), 2)
            for throttle in throttles:
                throttle.window_started_at = utc_now() - timedelta(minutes=16)
                session.add(throttle)
            session.commit()

        next_failure = self.client.post(
            "/staff/login",
            data={"login_id": "principal", "password": "still-wrong"},
        )
        self.assertEqual(next_failure.status_code, 400)
        with Session(self.engine) as session:
            throttles = session.exec(select(LoginThrottle)).all()
            self.assertTrue(all(item.failure_count == 1 for item in throttles))

    def test_admin_can_issue_activation_code_from_staff_management(self):
        self._activate()
        self._login(redirect_to="/staff/users")
        with Session(self.engine) as session:
            teacher = User(
                email="teacher@example.com",
                display_name="担任",
                staff_role="can_edit",
                staff_sort_order=50,
            )
            session.add(teacher)
            session.commit()
            teacher_id = teacher.id

        listing = self.client.get("/staff/users?source=all")
        self.assertIn("認証管理", listing.text)
        self.assertIn("未設定", listing.text)
        self.assertIn("ログインID: principal", listing.text)
        self.assertIn("メール: principal@example.com", listing.text)

        page = self.client.get(f"/staff/users/{teacher_id}/authentication")
        self.assertEqual(page.status_code, 200)
        self.assertIn("職員認証を設定", page.text)
        response = self.client.post(
            f"/staff/users/{teacher_id}/authentication/activate",
            data={"login_id": "teacher", "reason": "新規職員の初期設定"},
        )
        activation_code = self._action_code_from(response)
        self.assertNotIn(activation_code, str(self.engine.url))

        confirmation = self.client.post(
            "/staff/activate/check",
            data={"activation_code": activation_code.lower()},
        )
        self.assertEqual(confirmation.status_code, 200)
        self.assertIn("担任", confirmation.text)
        self.assertIn('name="login_id"', confirmation.text)
        self.assertIn('value="teacher"', confirmation.text)

        activated = self.client.post(
            "/staff/activate",
            data={
                "activation_code": activation_code.lower(),
                "login_id": "teacher-login",
                "password": "Maple!9274Blue",
                "password_confirmation": "Maple!9274Blue",
            },
            follow_redirects=False,
        )
        self.assertEqual(activated.status_code, 303)
        with Session(self.engine) as session:
            teacher_credential = session.exec(
                select(PasswordCredential).where(
                    PasswordCredential.staff_user_id == teacher_id
                )
            ).one()
            self.assertEqual(teacher_credential.login_id, "teacher-login")

    def test_activation_rejects_duplicate_edited_login_id_without_consuming_code(self):
        with Session(self.engine) as session:
            teacher = User(
                email="teacher@example.com",
                display_name="担任",
                staff_role="can_edit",
                staff_sort_order=50,
            )
            session.add(teacher)
            session.flush()
            credential, activation_code = create_staff_credential(
                session,
                user=teacher,
                login_id="teacher",
            )
            session.commit()
            credential_id = credential.id

        rejected = self.client.post(
            "/staff/activate",
            data={
                "activation_code": activation_code,
                "login_id": "principal",
                "password": "Maple!9274Blue",
                "password_confirmation": "Maple!9274Blue",
            },
        )
        self.assertEqual(rejected.status_code, 400)
        self.assertIn("このログインIDは既に使用されています", rejected.text)
        self.assertIn('value="principal"', rejected.text)

        with Session(self.engine) as session:
            credential = session.get(PasswordCredential, credential_id)
            token = session.get(
                CredentialActionToken,
                next(
                    item.token_hash
                    for item in session.exec(select(CredentialActionToken)).all()
                    if item.credential_id == credential_id
                ),
            )
            self.assertEqual(credential.login_id, "teacher")
            self.assertIsNone(credential.password_hash)
            self.assertIsNone(token.consumed_at)

    def test_admin_reset_code_changes_password_and_revokes_sessions(self):
        self._activate()
        self._login(redirect_to="/staff/users")
        response = self.client.post(
            f"/staff/users/{self.user_id}/authentication/reset",
            data={"reason": "本人からパスワード紛失の申告"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('name="password"', response.text)
        reset_code = self._action_code_from(response)
        self.assertEqual(len(reset_code), ACTION_CODE_LENGTH)
        self.assertTrue(set(reset_code) <= set(ACTION_CODE_ALPHABET))

        new_password = "Fresh!9274Blue"
        changed = self.client.post(
            "/staff/reset-password",
            data={
                "reset_code": reset_code,
                "password": new_password,
                "password_confirmation": new_password,
            },
            follow_redirects=False,
        )
        self.assertEqual(changed.status_code, 303)
        self.assertEqual(changed.headers["location"], "/staff/login?password_reset=1")
        self.assertEqual(
            self.client.get("/protected", headers={"Accept": "application/json"}).status_code,
            401,
        )

        reused = self.client.post(
            "/staff/reset-password",
            data={
                "reset_code": reset_code,
                "password": "Another!9274Blue",
                "password_confirmation": "Another!9274Blue",
            },
        )
        self.assertEqual(reused.status_code, 400)
        self.assertIn("再設定コードを確認してください", reused.text)

        old_login = self._login()
        self.assertEqual(old_login.status_code, 400)
        new_login = self.client.post(
            "/staff/login",
            data={
                "login_id": "principal",
                "password": new_password,
                "redirect_to": "/protected",
            },
            follow_redirects=False,
        )
        self.assertEqual(new_login.status_code, 303)

    def test_action_code_guesses_are_throttled_by_network(self):
        for _ in range(20):
            response = self.client.post(
                "/staff/activate/check",
                data={"activation_code": "AAAAAA"},
            )
            self.assertEqual(response.status_code, 400)

        with Session(self.engine) as session:
            throttle = session.exec(
                select(LoginThrottle).where(LoginThrottle.bucket_type == "action_code")
            ).one()
            self.assertEqual(throttle.failure_count, 20)
            self.assertIsNotNone(throttle.blocked_until)

        blocked = self.client.post(
            "/staff/activate/check",
            data={"activation_code": self.activation_code},
        )
        self.assertEqual(blocked.status_code, 400)
        self.assertIn("有効化コードを確認してください", blocked.text)

    def test_unknown_and_wrong_password_use_same_response(self):
        self._activate()
        wrong = self.client.post(
            "/staff/login",
            data={"login_id": "principal", "password": "wrong"},
        )
        unknown = self.client.post(
            "/staff/login",
            data={"login_id": "not-a-user", "password": "wrong"},
        )

        self.assertEqual(wrong.status_code, 400)
        self.assertEqual(unknown.status_code, 400)
        expected = "ログインIDまたはパスワードを確認してください"
        self.assertIn(expected, wrong.text)
        self.assertIn(expected, unknown.text)
        with Session(self.engine) as session:
            failures = session.exec(
                select(AuthenticationEvent).where(
                    AuthenticationEvent.event_type == "login",
                    AuthenticationEvent.result == "failure",
                )
            ).all()
        self.assertEqual(len(failures), 2)

    def test_disabled_user_and_expired_session_are_rejected_immediately(self):
        self._activate()
        self._login()
        with Session(self.engine) as session:
            auth_session = session.exec(select(AuthSession)).one()
            auth_session.idle_expires_at = utc_now() - timedelta(seconds=1)
            session.add(auth_session)
            session.commit()
        expired = self.client.get(
            "/protected",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(expired.status_code, 401)

        self.client.cookies.clear()
        self._login()
        with Session(self.engine) as session:
            user = session.get(User, self.user_id)
            user.is_active = False
            session.add(user)
            session.commit()
        disabled = self.client.get(
            "/protected",
            headers={"Accept": "application/json"},
        )
        self.assertEqual(disabled.status_code, 401)

    def test_logout_revokes_database_session(self):
        self._activate()
        self._login()

        response = self.client.post("/staff/logout", follow_redirects=False)
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            auth_session = session.exec(select(AuthSession)).one()
        self.assertIsNotNone(auth_session.revoked_at)
        self.assertEqual(auth_session.revoke_reason, "explicit_logout")

    def test_external_redirect_is_rejected(self):
        self._activate()
        response = self._login(redirect_to="https://attacker.example/")
        self.assertEqual(response.headers["location"], "/")


if __name__ == "__main__":
    unittest.main()
