import os
import unittest
from datetime import date, timedelta
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from local_auth import AuthenticationFailed, PasswordPolicyError
from models import (
    Child,
    ChildStatus,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentMailDelivery,
    ParentRegistrationRequest,
    ParentRegistrationSession,
    PasswordCredential,
    User,
)
from parent_auth import (
    authenticate_parent,
    complete_parent_action_password,
    complete_parent_registration,
    disable_parent_authentication,
    dispatch_pending_parent_mail,
    exchange_completion_token,
    exchange_invitation_token,
    exchange_parent_action_code,
    issue_parent_invitation,
    issue_parent_password_code,
    normalize_verification_name,
    resolve_parent_session,
    review_parent_registration,
    submit_parent_identity,
    token_hash,
)
from time_utils import utc_now


class LocalParentAuthenticationTests(unittest.TestCase):
    PASSWORD = "Cedar!9274Blue"

    def setUp(self):
        self.environment = patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "test",
                "HOIKUICT_PARENT_AUTH_MODE": "local_password",
                "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture",
                "HOIKUICT_PARENT_REGISTRATION_BASE_URL": "http://testserver",
                "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "t" * 40,
            },
            clear=False,
        )
        self.environment.start()
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            actor = User(
                email="admin@example.com",
                display_name="園長",
                staff_role="admin",
                staff_sort_order=10,
                is_active=True,
            )
            child = Child(
                last_name="髙橋",
                first_name="花",
                last_name_kana="タカハシ",
                first_name_kana="ハナ",
                registration_verification_name="タカハシ ハナ",
                registration_verification_name_type="kana",
                birth_date=date(2021, 5, 4),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
            )
            account = ParentAccount(
                display_name="髙橋 真由美",
                registration_verification_name="タカハシ マユミ",
                registration_verification_name_type="kana",
                email="parent@example.com",
                status=ParentAccountStatus.active,
            )
            session.add(actor)
            session.add(child)
            session.add(account)
            session.flush()
            session.add(
                ParentChildLink(parent_account_id=account.id, child_id=child.id)
            )
            session.commit()
            self.actor_id = actor.id
            self.account_id = account.id

    def tearDown(self):
        self.engine.dispose()
        self.environment.stop()

    def _invite(self):
        with Session(self.engine) as session:
            account = session.get(ParentAccount, self.account_id)
            actor = session.get(User, self.actor_id)
            registration, raw_token = issue_parent_invitation(
                session,
                account=account,
                actor_user=actor,
                reason="新規利用開始",
            )
            return registration.id, raw_token

    def _complete_initial_registration(self):
        registration_id, invitation_token = self._invite()
        with Session(self.engine) as session:
            state = exchange_invitation_token(session, invitation_token)
            registration = submit_parent_identity(
                session,
                raw_state=state,
                guardian_name="タカハシ マユミ",
                child_name="タカハシ ハナ",
                child_birth_date=date(2021, 5, 4),
            )
            actor = session.get(User, self.actor_id)
            completion_token = review_parent_registration(
                session,
                registration=registration,
                actor_user=actor,
                approve=True,
                reason="台帳と紐付けを確認",
            )
            completion_state = exchange_completion_token(session, completion_token)
            complete_parent_registration(
                session,
                raw_state=completion_state,
                password=self.PASSWORD,
                password_confirmation=self.PASSWORD,
            )
        return registration_id

    def test_kana_and_latin_normalization_follow_registered_type(self):
        self.assertEqual(
            normalize_verification_name(" たかはし　はな ", "kana"),
            "タカハシハナ",
        )
        self.assertEqual(
            normalize_verification_name(" Jean—D’Arc  ", "latin"),
            "jean-d'arc",
        )

    def test_invite_review_complete_and_login_store_only_token_hashes(self):
        registration_id, invitation_token = self._invite()
        with Session(self.engine) as session:
            registration = session.get(ParentRegistrationRequest, registration_id)
            delivery = session.exec(select(ParentMailDelivery)).one()
            credential = session.exec(
                select(PasswordCredential).where(
                    PasswordCredential.parent_account_id == self.account_id
                )
            ).one()
            self.assertNotEqual(registration.invitation_token_hash, invitation_token)
            self.assertNotIn("髙橋", delivery.body)
            self.assertNotIn("parent@example.com", delivery.body)
            self.assertIsNone(credential.password_hash)

            state = exchange_invitation_token(session, invitation_token)
            submitted = submit_parent_identity(
                session,
                raw_state=state,
                guardian_name="たかはし まゆみ",
                child_name="ﾀｶﾊｼ ﾊﾅ",
                child_birth_date=date(2021, 5, 4),
            )
            self.assertEqual(submitted.status, "pending_review")
            actor = session.get(User, self.actor_id)
            completion_token = review_parent_registration(
                session,
                registration=submitted,
                actor_user=actor,
                approve=True,
                reason="台帳と紐付けを確認",
            )
            completion_state = exchange_completion_token(session, completion_token)
            complete_parent_registration(
                session,
                raw_state=completion_state,
                password=self.PASSWORD,
                password_confirmation=self.PASSWORD,
            )

            login = authenticate_parent(
                session,
                login_id="PARENT@example.com",
                password=self.PASSWORD,
            )
            self.assertEqual(login.account.id, self.account_id)
            self.assertEqual(
                resolve_parent_session(session, login.session_token).id,
                self.account_id,
            )

    def test_mismatched_identity_never_becomes_approvable(self):
        registration_id, invitation_token = self._invite()
        with Session(self.engine) as session:
            state = exchange_invitation_token(session, invitation_token)
            submitted = submit_parent_identity(
                session,
                raw_state=state,
                guardian_name="別人",
                child_name="別人",
                child_birth_date=date(2020, 1, 1),
            )
            actor = session.get(User, self.actor_id)
            with self.assertRaisesRegex(ValueError, "承認できません"):
                review_parent_registration(
                    session,
                    registration=submitted,
                    actor_user=actor,
                    approve=True,
                    reason="確認",
                )

    def test_invitation_requires_an_explicit_parent_child_link(self):
        with Session(self.engine) as session:
            for link in session.exec(select(ParentChildLink)).all():
                session.delete(link)
            session.commit()
            account = session.get(ParentAccount, self.account_id)
            actor = session.get(User, self.actor_id)
            with self.assertRaisesRegex(ValueError, "明示的に紐付く"):
                issue_parent_invitation(
                    session,
                    account=account,
                    actor_user=actor,
                    reason="新規利用開始",
                )

    def test_identity_can_be_retried_five_times_with_the_same_invitation(self):
        _registration_id, invitation_token = self._invite()
        with Session(self.engine) as session:
            state = exchange_invitation_token(session, invitation_token)
            for attempt in range(1, 5):
                registration = submit_parent_identity(
                    session,
                    raw_state=state,
                    guardian_name="別人",
                    child_name="別人",
                    child_birth_date=date(2020, 1, 1),
                )
                self.assertEqual(registration.status, "pending_review")
                self.assertEqual(registration.verification_attempt_count, attempt)
                stored_state = session.get(ParentRegistrationSession, token_hash(state))
                self.assertIsNone(stored_state.consumed_at)

            registration = submit_parent_identity(
                session,
                raw_state=state,
                guardian_name="別人",
                child_name="別人",
                child_birth_date=date(2020, 1, 1),
            )
            self.assertEqual(registration.status, "expired")
            self.assertEqual(registration.verification_attempt_count, 5)
            with self.assertRaises(AuthenticationFailed):
                submit_parent_identity(
                    session,
                    raw_state=state,
                    guardian_name="タカハシ マユミ",
                    child_name="タカハシ ハナ",
                    child_birth_date=date(2021, 5, 4),
                )

    def test_password_validation_error_keeps_reset_state_reusable(self):
        self._complete_initial_registration()
        with Session(self.engine) as session:
            account = session.get(ParentAccount, self.account_id)
            actor = session.get(User, self.actor_id)
            code = issue_parent_password_code(
                session,
                account=account,
                actor_user=actor,
                reason="本人確認済み",
            )
            state = exchange_parent_action_code(session, code, "parent_reset")

        with Session(self.engine) as session:
            with self.assertRaises(PasswordPolicyError):
                complete_parent_action_password(
                    session,
                    raw_state=state,
                    purpose="parent_reset",
                    password="Different!9274Blue",
                    password_confirmation="Mismatch!9274Blue",
                )

        new_password = "Maple!5831Green"
        with Session(self.engine) as session:
            complete_parent_action_password(
                session,
                raw_state=state,
                purpose="parent_reset",
                password=new_password,
                password_confirmation=new_password,
            )
            login = authenticate_parent(
                session,
                login_id="parent@example.com",
                password=new_password,
            )
            self.assertEqual(login.account.id, self.account_id)

    def test_disabling_parent_revokes_exchanged_reset_state(self):
        self._complete_initial_registration()
        with Session(self.engine) as session:
            account = session.get(ParentAccount, self.account_id)
            actor = session.get(User, self.actor_id)
            reset_code = issue_parent_password_code(
                session,
                account=account,
                actor_user=actor,
                reason="本人確認済み",
            )
            reset_state = exchange_parent_action_code(
                session, reset_code, "parent_reset"
            )
            disable_parent_authentication(session, account, actor, "利用停止")

        with Session(self.engine) as session:
            with self.assertRaises(AuthenticationFailed):
                complete_parent_action_password(
                    session,
                    raw_state=reset_state,
                    purpose="parent_reset",
                    password="Maple!5831Green",
                    password_confirmation="Maple!5831Green",
                )
            account = session.get(ParentAccount, self.account_id)
            actor = session.get(User, self.actor_id)
            with self.assertRaisesRegex(ValueError, "停止中"):
                issue_parent_password_code(
                    session,
                    account=account,
                    actor_user=actor,
                    reason="本人確認済み",
                )

    def test_disabled_parent_can_be_reactivated_only_with_activation_code(self):
        self._complete_initial_registration()
        new_password = "Maple!5831Green"
        with Session(self.engine) as session:
            account = session.get(ParentAccount, self.account_id)
            actor = session.get(User, self.actor_id)
            disable_parent_authentication(session, account, actor, "利用停止")
            activation_code = issue_parent_password_code(
                session,
                account=account,
                actor_user=actor,
                reason="再開時の本人確認済み",
                action="parent_activate",
            )
            activation_state = exchange_parent_action_code(
                session, activation_code, "parent_activate"
            )
            complete_parent_action_password(
                session,
                raw_state=activation_state,
                purpose="parent_activate",
                password=new_password,
                password_confirmation=new_password,
            )
            login = authenticate_parent(
                session,
                login_id="parent@example.com",
                password=new_password,
            )
            self.assertEqual(login.account.id, self.account_id)

    def test_mail_retry_waits_until_next_retry_and_stops_after_three_attempts(self):
        registration_id, _ = self._invite()
        with patch.dict(os.environ, {"HOIKUICT_PARENT_MAIL_TRANSPORT": "disabled"}):
            with Session(self.engine) as session:
                dispatch_pending_parent_mail(
                    session,
                    registration_request_id=registration_id,
                )
                delivery = session.exec(select(ParentMailDelivery)).one()
                self.assertEqual(delivery.attempt_count, 1)
                self.assertEqual(delivery.status, "pending")
                self.assertIsNotNone(delivery.next_retry_at)

                dispatch_pending_parent_mail(
                    session,
                    registration_request_id=registration_id,
                )
                session.refresh(delivery)
                self.assertEqual(delivery.attempt_count, 1)

                for expected_attempt in (2, 3):
                    delivery.next_retry_at = utc_now() - timedelta(seconds=1)
                    session.add(delivery)
                    session.commit()
                    dispatch_pending_parent_mail(
                        session,
                        registration_request_id=registration_id,
                    )
                    session.refresh(delivery)
                    self.assertEqual(delivery.attempt_count, expected_attempt)
                self.assertEqual(delivery.status, "failed")
                self.assertIsNone(delivery.lease_expires_at)


if __name__ == "__main__":
    unittest.main()
