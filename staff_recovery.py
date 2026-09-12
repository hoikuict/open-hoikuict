"""Email recovery for active, password-configured administrators."""

import asyncio
import hmac
import logging
import os
import re
import secrets
from datetime import timedelta

from fastapi import Request
from sqlalchemy import and_, case, delete, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from auth_mail import send_auth_mail
from local_auth import (
    AuthenticationFailed,
    PasswordPolicyError,
    _add_event,
    _bucket_hash,
    _request_network,
    _token_hash,
    hash_password,
    normalize_password,
    revoke_staff_sessions,
    validate_new_password,
)
from models import (
    CredentialActionToken,
    LoginThrottle,
    PasswordCredential,
    StaffMailDelivery,
    StaffPasswordRecovery,
    User,
)
from security_config import staff_auth_mode, staff_recovery_base_url
from staff_user_service import STAFF_USER_SORT_ORDER_LIMIT
from time_utils import ensure_utc, utc_now

RECOVERY_TTL = timedelta(minutes=30)
RECOVERY_FAILURE = "リンクが無効か、有効期限が切れています。再設定メールをもう一度申請してください。"
REQUEST_ACCEPTED = "登録情報が一致し、メールを送信できる場合は、再設定の案内をお送りします。"
logger = logging.getLogger(__name__)


def mail_transport() -> str:
    return (os.getenv("HOIKUICT_PARENT_MAIL_TRANSPORT") or "capture").strip().lower()


def _take_rate_slot(session, value, kind, *, limit, cooldown=timedelta(0)):
    """Atomic counters separate from password-login lockouts; no raw address/IP."""
    now = utc_now()
    key = _bucket_hash("staff_recovery", kind, value)
    if session.get(LoginThrottle, key) is None:
        try:
            with session.begin_nested():
                session.add(LoginThrottle(
                    bucket_hash=key, bucket_type=kind, failure_count=0,
                    window_started_at=now, updated_at=now - cooldown,
                ))
                session.flush()
        except IntegrityError:
            pass  # Another request initialized this counter.
    expired = LoginThrottle.window_started_at <= now - timedelta(hours=1)
    result = session.execute(
        update(LoginThrottle).where(
            LoginThrottle.bucket_hash == key,
            or_(expired, LoginThrottle.failure_count < limit),
            LoginThrottle.updated_at <= now - cooldown,
        ).values(
            failure_count=case((expired, 1), else_=LoginThrottle.failure_count + 1),
            window_started_at=case((expired, now), else_=LoginThrottle.window_started_at),
            updated_at=now,
        ).execution_options(synchronize_session=False)
    )
    return result.rowcount == 1


def _admin_conditions():
    return (
        User.is_active.is_(True), User.staff_role == "admin",
        User.staff_sort_order < STAFF_USER_SORT_ORDER_LIMIT,
        PasswordCredential.principal_type == "staff",
        PasswordCredential.password_hash.is_not(None),
        PasswordCredential.disabled_at.is_(None),
    )


def _recovery_subject(session, recovery):
    if recovery is None or recovery.consumed_at is not None or ensure_utc(recovery.expires_at) <= utc_now():
        return None
    return session.exec(
        select(User, PasswordCredential)
        .join(PasswordCredential, PasswordCredential.staff_user_id == User.id)
        .where(
            *_admin_conditions(), User.id == recovery.staff_user_id,
            User.email == recovery.recipient,
            PasswordCredential.id == recovery.credential_id,
            PasswordCredential.credential_version == recovery.credential_version,
        )
    ).first()


def request_admin_password_recovery(session: Session, email: str, request: Request) -> None:
    # All callers receive the same response, including unknown/disabled accounts.
    if not _take_rate_slot(session, _request_network(request), "recovery_network", limit=20):
        session.commit()
        return
    email = email.strip()
    if len(email) > 255 or not re.fullmatch(r"[^\s<>@]+@[^\s<>@]+", email):
        session.commit()
        return
    if not _take_rate_slot(session, email.lower(), "recovery_email", limit=5, cooldown=timedelta(minutes=1)):
        session.commit()
        return
    users = session.exec(select(User).where(func.lower(func.trim(User.email)) == email.lower()).limit(2)).all()
    # Case variants in legacy records must not choose an arbitrary identity.
    subject = None
    if len(users) == 1:
        subject = session.exec(
            select(User, PasswordCredential)
            .join(PasswordCredential, PasswordCredential.staff_user_id == User.id)
            .where(User.id == users[0].id, *_admin_conditions())
        ).first()
    if subject is None or mail_transport() not in {"smtp", "capture"}:
        session.commit()
        return
    try:
        base_url = staff_recovery_base_url()
    except RuntimeError:
        logger.error("Staff recovery URL is not configured correctly")
        session.commit()
        return
    user, credential = subject
    raw_token = secrets.token_urlsafe(32)
    recovery = StaffPasswordRecovery(
        token_hash=_token_hash(raw_token), staff_user_id=user.id,
        credential_id=credential.id, credential_version=credential.credential_version,
        recipient=user.email, expires_at=utc_now() + RECOVERY_TTL,
    )
    session.add(recovery)
    session.flush()
    session.add(StaffMailDelivery(
        staff_user_id=user.id, recovery_token_hash=recovery.token_hash,
        message_type="password_recovery", recipient=user.email,
        subject="OPEN保育ICT 管理者パスワード再設定のご案内",
        body=(
            "管理者アカウントのパスワード再設定を受け付けました。\n\n"
            f"{base_url}/staff/recover-password#{raw_token}\n\n"
            "このリンクは申請から30分間、1回限り有効です。\n"
            "申請しただけではパスワードは変更されません。\n"
            "お心当たりがない場合は、このメールのリンクを使わないでください。"
        ), expires_at=recovery.expires_at,
    ))
    _add_event(session, event_type="password_recovery_requested", result="success",
               reason_code="email_queued", credential=credential, staff_user_id=user.id)
    session.commit()


def complete_admin_password_recovery(
    session: Session, *, token: str, password: str, password_confirmation: str,
) -> User:
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", token):
        raise AuthenticationFailed(RECOVERY_FAILURE)
    recovery = session.get(StaffPasswordRecovery, _token_hash(token))
    subject = _recovery_subject(session, recovery)
    if subject is None:
        raise AuthenticationFailed(RECOVERY_FAILURE)
    user, credential = subject
    normalized = validate_new_password(password, login_id=credential.login_id,
                                       email=user.email, display_name=user.display_name)
    if not hmac.compare_digest(normalized.encode(), normalize_password(password_confirmation).encode()):
        raise PasswordPolicyError("確認用パスワードが一致しません")
    password_hash = hash_password(normalized)
    now = utc_now()
    # Check and consume within the password transaction, not when a mail scanner
    # or browser opens the link. Version CAS also serializes different links.
    claimed = session.execute(update(StaffPasswordRecovery).where(
        StaffPasswordRecovery.token_hash == recovery.token_hash,
        StaffPasswordRecovery.consumed_at.is_(None), StaffPasswordRecovery.expires_at > now,
    ).values(consumed_at=now).execution_options(synchronize_session=False))
    eligible_user = select(User.id).where(
        User.id == user.id, User.email == recovery.recipient, User.is_active.is_(True),
        User.staff_role == "admin", User.staff_sort_order < STAFF_USER_SORT_ORDER_LIMIT,
    )
    changed = session.execute(update(PasswordCredential).where(
        PasswordCredential.id == recovery.credential_id,
        PasswordCredential.staff_user_id.in_(eligible_user),
        PasswordCredential.principal_type == "staff",
        PasswordCredential.password_hash.is_not(None), PasswordCredential.disabled_at.is_(None),
        PasswordCredential.credential_version == recovery.credential_version,
    ).values(password_hash=password_hash, password_changed_at=now, updated_at=now,
             credential_version=PasswordCredential.credential_version + 1,
             must_change_password=False).execution_options(synchronize_session=False))
    if claimed.rowcount != 1 or changed.rowcount != 1:
        session.rollback()
        raise AuthenticationFailed(RECOVERY_FAILURE)
    session.execute(update(StaffPasswordRecovery).where(
        StaffPasswordRecovery.credential_id == credential.id,
        StaffPasswordRecovery.consumed_at.is_(None),
    ).values(consumed_at=now).execution_options(synchronize_session=False))
    session.execute(update(CredentialActionToken).where(
        CredentialActionToken.credential_id == credential.id,
        CredentialActionToken.consumed_at.is_(None), CredentialActionToken.revoked_at.is_(None),
    ).values(revoked_at=now).execution_options(synchronize_session=False))
    session.execute(update(StaffMailDelivery).where(
        StaffMailDelivery.staff_user_id == user.id,
        StaffMailDelivery.message_type == "password_recovery",
    ).values(body="", status="cancelled").execution_options(synchronize_session=False))
    revoke_staff_sessions(session, staff_user_id=user.id, reason="email_password_reset", now=now)
    session.execute(delete(LoginThrottle).where(LoginThrottle.bucket_hash ==
                    _bucket_hash("staff", "account", credential.login_id_normalized)))
    session.add(StaffMailDelivery(
        staff_user_id=user.id, message_type="password_reset_completed", recipient=user.email,
        subject="OPEN保育ICT 管理者パスワード変更のお知らせ",
        body=("管理者アカウントのパスワードが変更されました。\n"
              "以前のログインはすべて解除されています。\n"
              f"ログインID: {credential.login_id}\n"
              "新しいパスワードで通常のログイン画面からログインしてください。\n"
              "お心当たりがない場合は、施設の保守担当者へご連絡ください。"),
        expires_at=now + timedelta(days=1),
    ))
    _add_event(session, event_type="password_reset", result="success",
               reason_code="email_recovery_completed", credential=credential, staff_user_id=user.id)
    session.commit()
    return user


def _claim_conditions(now):
    return (
        or_(StaffMailDelivery.status == "pending", and_(StaffMailDelivery.status == "processing",
            StaffMailDelivery.lease_expires_at <= now)),
        or_(StaffMailDelivery.next_retry_at.is_(None), StaffMailDelivery.next_retry_at <= now),
        StaffMailDelivery.expires_at > now,
    )


def dispatch_pending_staff_mail(session: Session) -> None:
    now = utc_now()
    session.execute(update(StaffMailDelivery).where(
        StaffMailDelivery.expires_at <= now, StaffMailDelivery.body != "",
    ).values(body="", status="expired").execution_options(synchronize_session=False))
    session.commit()
    if staff_auth_mode() != "local_password" or mail_transport() not in {"smtp", "capture"}:
        return
    ids = session.exec(select(StaffMailDelivery.id).where(*_claim_conditions(now)).limit(20)).all()
    for delivery_id in ids:
        now = utc_now()
        claim = session.execute(update(StaffMailDelivery).where(
            StaffMailDelivery.id == delivery_id, *_claim_conditions(now),
        ).values(status="processing", attempt_count=StaffMailDelivery.attempt_count + 1,
                 lease_expires_at=now + timedelta(minutes=2))
          .execution_options(synchronize_session=False))
        session.commit()
        if claim.rowcount != 1:
            continue
        delivery = session.get(StaffMailDelivery, delivery_id)
        if delivery.recovery_token_hash and _recovery_subject(
            session, session.get(StaffPasswordRecovery, delivery.recovery_token_hash)
        ) is None:
            delivery.status, delivery.body = "cancelled", ""
        else:
            try:
                if mail_transport() == "capture":
                    delivery.status = "captured"
                else:
                    send_auth_mail(recipient=delivery.recipient, subject=delivery.subject, body=delivery.body)
                    delivery.status, delivery.body = "sent", ""
                delivery.sent_at = utc_now()
                delivery.failure_code = None
                delivery.next_retry_at = None
            except Exception as exc:
                delivery.failure_code = type(exc).__name__[:64]
                delivery.status = "pending" if delivery.attempt_count < 3 else "failed"
                delivery.next_retry_at = utc_now() + timedelta(seconds=30 * (2 ** (delivery.attempt_count - 1)))
                if delivery.status == "failed":
                    delivery.body = ""
                logger.warning("Staff recovery mail delivery failed (%s)", delivery.failure_code)
        delivery.lease_expires_at = None
        session.add(delivery)
        session.commit()


async def staff_mail_worker_loop() -> None:
    import database

    def run_cycle():
        with Session(database.engine) as session:
            dispatch_pending_staff_mail(session)

    while True:
        await asyncio.sleep(5)
        try:
            await asyncio.to_thread(run_cycle)
        except Exception as exc:
            # Do not log addresses, tokens or SMTP response text.
            logger.error("Staff recovery mail worker failed (%s)", type(exc).__name__)
