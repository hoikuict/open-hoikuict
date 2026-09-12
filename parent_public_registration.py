"""Common QR entry, email ownership verification, and explicit staff approval."""

from __future__ import annotations

from datetime import date, timedelta
from ipaddress import ip_address
import math
import re
import secrets
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from local_auth import _bucket_hash, _request_network, normalize_login_id
from family_support import guardian_profiles_from_child
from models import (
    AuthenticationEvent,
    Child,
    LoginThrottle,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentEnrollment,
    ParentPublicRegistration,
    ParentPublicRegistrationSettings,
    ParentRegistrationRequest,
    ParentRegistrationSession,
    PasswordCredential,
)
from parent_auth import (
    INVITATION_TTL,
    _queue_registration_mail,
    _registration_base_url,
    cancel_open_parent_registrations,
    ensure_parent_credential,
    token_hash,
)
from parent_enrollment import compact_name, enrollment_target, source_snapshot
from time_utils import ensure_utc, utc_now

PUBLIC_PATH = "/parent-portal/register/apply"


class RegistrationLimited(Exception):
    def __init__(self, retry_after: int):
        self.retry_after = retry_after


class InvalidRegistrationEmail(ValueError):
    pass


def public_registration_enabled(session: Session) -> bool:
    settings = session.get(ParentPublicRegistrationSettings, 1)
    return bool(settings and settings.enabled)


def public_registration_url() -> str:
    base = _registration_base_url()
    parsed = urlsplit(base)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("保護者登録の公開URL設定を確認してください")
    return base + PUBLIC_PATH


def consume_registration_limit(
    session: Session,
    value: str,
    *,
    bucket_type="signup_ip",
    limit=5,
    window=timedelta(minutes=10),
    cooldown=timedelta(minutes=15),
) -> None:
    """Reserve an attempt atomically; a failed application still counts."""
    now = utc_now()
    key = _bucket_hash("parent_public_signup", bucket_type, value)
    try:
        with session.begin_nested():
            session.add(
                LoginThrottle(
                    bucket_hash=key,
                    bucket_type=bucket_type,
                    failure_count=0,
                    window_started_at=now,
                )
            )
            session.flush()
    except IntegrityError:
        pass
    expired = LoginThrottle.window_started_at <= now - window
    allowed = session.execute(
        update(LoginThrottle)
        .where(
            LoginThrottle.bucket_hash == key,
            or_(
                LoginThrottle.blocked_until.is_(None),
                LoginThrottle.blocked_until <= now,
            ),
            or_(expired, LoginThrottle.failure_count < limit),
        )
        .values(
            failure_count=case((expired, 1), else_=LoginThrottle.failure_count + 1),
            window_started_at=case(
                (expired, now), else_=LoginThrottle.window_started_at
            ),
            blocked_until=case(
                (
                    (~expired) & (LoginThrottle.failure_count >= limit - 1),
                    now + cooldown,
                ),
                else_=None,
            ),
            updated_at=now,
        )
        .execution_options(synchronize_session=False)
    )
    session.commit()
    if allowed.rowcount != 1:
        bucket = session.get(LoginThrottle, key, populate_existing=True)
        until = (
            ensure_utc(bucket.blocked_until)
            if bucket.blocked_until
            else ensure_utc(bucket.window_started_at) + window
        )
        raise RegistrationLimited(max(1, math.ceil((until - now).total_seconds())))


def limit_public_network(session: Session, request: Request) -> None:
    # Uvicorn resolves trusted proxies; never trust client-supplied forwarding headers here.
    network = _request_network(request)
    try:
        address = ip_address(network)
        network = str(getattr(address, "ipv4_mapped", None) or address)
    except ValueError:
        pass
    consume_registration_limit(session, network)


def request_public_registration(session: Session, email: str) -> None:
    """Always use the same public response for existing and new addresses."""
    email = normalize_login_id(email.strip())
    if (
        len(email) > 255
        or not email.isascii()
        or not re.fullmatch(
            r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-z0-9][a-z0-9.-]*\.[a-z]{2,63}", email
        )
    ):
        raise InvalidRegistrationEmail("受信できるメールアドレスを入力してください")
    try:
        consume_registration_limit(
            session,
            email,
            bucket_type="signup_email",
            limit=3,
            window=timedelta(days=1),
            cooldown=timedelta(days=1),
        )
    except RegistrationLimited:
        return
    now = utc_now()
    account = session.exec(
        select(ParentAccount).where(func.lower(ParentAccount.email) == email)
    ).first()
    if account:
        latest = session.exec(
            select(ParentRegistrationRequest)
            .where(
                ParentRegistrationRequest.parent_account_id == account.id,
            )
            .order_by(ParentRegistrationRequest.created_at.desc())
        ).first()
        credential = session.exec(
            select(PasswordCredential).where(
                PasswordCredential.parent_account_id == account.id,
            )
        ).first()
        if (
            account.status != ParentAccountStatus.active
            or account.family_id
            or (credential and (credential.password_hash or credential.disabled_at))
            or session.exec(
                select(ParentChildLink).where(
                    ParentChildLink.parent_account_id == account.id
                )
            ).first()
            or not latest
            or not session.get(ParentPublicRegistration, latest.id)
            or latest.status not in {"invited", "expired"}
            or ensure_utc(latest.created_at) > now - timedelta(seconds=60)
        ):
            return
        active_form = session.exec(
            select(ParentRegistrationSession).where(
                ParentRegistrationSession.registration_request_id == latest.id,
                ParentRegistrationSession.purpose == "identity",
                ParentRegistrationSession.consumed_at.is_(None),
                ParentRegistrationSession.expires_at > now,
            )
        ).first()
        if active_form:
            return
        cancel_open_parent_registrations(session, account.id, now)
    else:
        account = ParentAccount(
            display_name="共通QRからの申請（メール確認待ち）", email=email
        )
        session.add(account)
        session.flush()
    credential = ensure_parent_credential(session, account)
    raw_token = secrets.token_urlsafe(32)
    registration = ParentRegistrationRequest(
        parent_account_id=account.id,
        email_normalized_snapshot=email,
        invitation_token_hash=token_hash(raw_token),
        invitation_expires_at=now + INVITATION_TTL,
        created_at=now,
        updated_at=now,
    )
    session.add(registration)
    session.flush()
    session.add(
        ParentEnrollment(registration_request_id=registration.id, child_name="初回申請")
    )
    session.add(ParentPublicRegistration(registration_request_id=registration.id))
    account.invited_at = now
    account.updated_at = now
    session.add(account)
    session.add(
        AuthenticationEvent(
            event_type="parent_public_registration",
            result="success",
            reason_code="email_requested",
            principal_type="parent",
            parent_account_id=account.id,
            credential_id=credential.id,
        )
    )
    _queue_registration_mail(session, registration, account, raw_token, "invitation")
    session.commit()


def public_registration_targets(session: Session) -> list[dict]:
    choices = []
    for child in session.exec(
        select(Child).order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all():
        profiles = (
            child.family.guardian_profiles()
            if child.family
            else guardian_profiles_from_child(child)
        )
        for profile in profiles or [{"order": 1}]:
            if profile.get("parent_account_id"):
                continue
            name = " ".join(
                filter(None, [profile.get("last_name"), profile.get("first_name")])
            )
            choices.append(
                {
                    "value": f"{child.id}:{profile['order']}",
                    "label": f"{child.full_name}（{child.birth_date or '生年月日未登録'}） / {name or '保護者1'}",
                }
            )
    return choices


def select_public_registration_target(
    session: Session, registration, target: str
) -> None:
    if not session.get(ParentPublicRegistration, registration.id):
        return
    enrollment = session.get(ParentEnrollment, registration.id)
    if not target:
        raise ValueError(
            "共通QRからの申請は、既存の園児・保護者または新規園児を選択してください"
        )
    if target == "new":
        values = enrollment.submitted_data
        if any(
            compact_name(child.full_name)
            == compact_name(values["last_name"] + values["first_name"])
            and child.birth_date == date.fromisoformat(values["birth_date"])
            for child in session.exec(select(Child)).all()
        ):
            raise ValueError(
                "同じ氏名・生年月日の園児が台帳にいます。既存の園児・保護者を選択してください"
            )
        enrollment.child_id = None
        enrollment.guardian_order = None
        enrollment.source_snapshot = None
    else:
        if target not in {
            choice["value"] for choice in public_registration_targets(session)
        }:
            raise ValueError(
                "承認先の園児・保護者を選択してください。登録状況が変更された場合は画面を開き直してください"
            )
        try:
            child_id, order = map(int, target.split(":"))
        except ValueError:
            raise ValueError("承認先の園児・保護者を選択してください") from None
        child, order = enrollment_target(session, child_id, order)
        values = enrollment.submitted_data
        if compact_name(child.full_name) != compact_name(
            values["last_name"] + values["first_name"]
        ) or child.birth_date != date.fromisoformat(values["birth_date"]):
            raise ValueError("選択した園児の氏名・生年月日が申請と一致しません")
        enrollment.child_id = child.id
        enrollment.guardian_order = order
        enrollment.source_snapshot = source_snapshot(child)
    session.add(enrollment)
