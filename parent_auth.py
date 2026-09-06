from __future__ import annotations

import hashlib
import asyncio
import hmac
import os
import re
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID
from urllib.parse import urlsplit

from fastapi import Request
from sqlalchemy import and_, or_, update
from sqlmodel import Session, select

from auth_mail import send_auth_mail

from local_auth import (
    AuthenticationFailed,
    LoginThrottled,
    PASSWORD_HASHER,
    PasswordPolicyError,
    _bucket_hash,
    _dummy_hash,
    _is_bucket_blocked,
    _record_failure,
    hash_password,
    issue_credential_action_token,
    normalize_login_id,
    normalize_password,
    validate_new_password,
    verify_password,
)
from models import (
    AuthenticationEvent,
    AuthSession,
    CredentialActionToken,
    Family,
    Guardian,
    LoginThrottle,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentEnrollment,
    ParentCredentialProvisioningAudit,
    ParentMailDelivery,
    ParentPushSubscription,
    ParentPushSubscriptionStatus,
    ParentRegistrationRequest,
    ParentRegistrationSession,
    PasswordCredential,
    User,
)
from time_utils import ensure_utc, format_jst_datetime, utc_now


PRINCIPAL_PARENT = "parent"
PARENT_LOGIN_FAILURE_MESSAGE = "ログインIDまたはパスワードを確認してください"
REGISTRATION_GENERIC_MESSAGE = "園に確認を依頼しました"
INVITATION_TTL = timedelta(hours=24)
PARENT_ACTION_CODE_TTL = timedelta(hours=24)
REGISTRATION_SESSION_TTL = timedelta(minutes=15)
PARENT_SESSION_IDLE = timedelta(hours=12)
PARENT_SESSION_ABSOLUTE = timedelta(days=7)
MAX_VERIFICATION_ATTEMPTS = 5
PARENT_MAIL_LEASE = timedelta(minutes=2)
PARENT_MAIL_RETRY_BASE = timedelta(seconds=30)
PARENT_CODE_MAIL_TYPES = ("parent_activate", "parent_reset")


@dataclass(frozen=True, slots=True)
class ParentLoginResult:
    account: ParentAccount
    credential: PasswordCredential
    session_token: str


def token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def normalize_verification_name(value: str, name_type: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "")
    if name_type == "kana":
        compact = "".join(
            character for character in normalized if not character.isspace()
        )
        return "".join(
            chr(ord(character) + 0x60)
            if "\u3041" <= character <= "\u3096"
            else character
            for character in compact
        )
    if name_type == "latin":
        normalized = normalized.strip()
        normalized = re.sub(r"\s+", " ", normalized)
        normalized = normalized.translate(
            str.maketrans(
                {
                    "‐": "-",
                    "‑": "-",
                    "‒": "-",
                    "–": "-",
                    "—": "-",
                    "−": "-",
                    "’": "'",
                    "‘": "'",
                    "ʼ": "'",
                    "＇": "'",
                }
            )
        )
        return normalized.casefold()
    raise ValueError("照合用氏名の表記種別は kana または latin で指定してください")


def _event(
    session: Session,
    *,
    event_type: str,
    result: str,
    reason_code: str,
    credential: PasswordCredential | None = None,
    parent_account_id: int | None = None,
    request: Request | None = None,
    network_bucket_hash: str | None = None,
) -> None:
    session.add(
        AuthenticationEvent(
            event_type=event_type,
            result=result,
            reason_code=reason_code,
            principal_type=PRINCIPAL_PARENT,
            parent_account_id=parent_account_id,
            credential_id=credential.id if credential else None,
            request_id=request.headers.get("X-Request-ID") if request else None,
            network_bucket_hash=network_bucket_hash,
        )
    )


def _request_network(request: Request | None) -> str:
    return (
        request.client.host
        if request and request.client and request.client.host
        else "unknown"
    )


def _credential_for_parent(
    session: Session, parent_account_id: int
) -> PasswordCredential | None:
    return session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_PARENT,
            PasswordCredential.parent_account_id == parent_account_id,
        )
    ).first()


def ensure_parent_credential(
    session: Session, account: ParentAccount
) -> PasswordCredential:
    credential = _credential_for_parent(session, account.id)
    login_id = account.email.strip()
    normalized = normalize_login_id(login_id)
    if not normalized:
        raise ValueError("招待先メールアドレスを登録してください")
    duplicate = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_PARENT,
            PasswordCredential.login_id_normalized == normalized,
            PasswordCredential.parent_account_id != account.id,
        )
    ).first()
    if duplicate is not None:
        raise ValueError(
            "このメールアドレスは別の保護者ログインIDとして使用されています"
        )
    if credential is None:
        credential = PasswordCredential(
            principal_type=PRINCIPAL_PARENT,
            parent_account_id=account.id,
            login_id=login_id,
            login_id_normalized=normalized,
        )
        session.add(credential)
        session.flush()
    elif credential.password_hash is None:
        credential.login_id = login_id
        credential.login_id_normalized = normalized
        credential.updated_at = utc_now()
        session.add(credential)
    return credential


def _linked_children(session: Session, parent_account_id: int):
    return session.exec(
        select(ParentChildLink).where(
            ParentChildLink.parent_account_id == parent_account_id
        )
    ).all()


def parent_invitation_requirements(session: Session, account: ParentAccount) -> list[str]:
    from parent_enrollment import latest_enrollment, prepare_enrollment
    enrollment = latest_enrollment(session, account.id)
    if enrollment and not enrollment.applied_at:
        try:
            prepare_enrollment(session, account, enrollment.child_name, enrollment.child_id, enrollment.guardian_order)
        except ValueError as exc:
            return [str(exc)]
        return []
    missing = []
    if account.status != ParentAccountStatus.active:
        missing.append("有効な保護者だけを招待できます")
    if (
        not account.registration_verification_name
        or account.registration_verification_name_type not in {"kana", "latin"}
    ):
        missing.append("保護者の照合用氏名と表記種別を登録してください")
    links = _linked_children(session, account.id)
    eligible = [
        link.child
        for link in links
        if link.child
        and link.child.registration_verification_name
        and link.child.registration_verification_name_type in {"kana", "latin"}
        and link.child.birth_date
    ]
    if not eligible:
        missing.append("明示的に紐付く園児へ照合用氏名と生年月日を登録してください")
    return missing


def _validate_invitation_ledger(session: Session, account: ParentAccount) -> None:
    missing = parent_invitation_requirements(session, account)
    if missing:
        raise ValueError(missing[0])


def cancel_open_parent_registrations(
    session: Session,
    parent_account_id: int,
    now: datetime | None = None,
) -> None:
    cancelled_at = now or utc_now()
    requests = session.exec(
        select(ParentRegistrationRequest).where(
            ParentRegistrationRequest.parent_account_id == parent_account_id,
            ParentRegistrationRequest.status.in_(
                ["invited", "pending_review", "approved"]
            ),
        )
    ).all()
    for item in requests:
        item.status = "cancelled"
        item.invitation_token_hash = None
        item.completion_token_hash = None
        item.updated_at = cancelled_at
        session.add(item)
        for delivery in session.exec(select(ParentMailDelivery).where(
            ParentMailDelivery.registration_request_id == item.id,
            ParentMailDelivery.status == "pending",
        )).all():
            delivery.status = "cancelled"
            delivery.next_retry_at = None
            session.add(delivery)


def issue_parent_invitation(
    session: Session,
    *,
    account: ParentAccount,
    actor_user: User,
    reason: str,
    enrollment: ParentEnrollment | None = None,
) -> tuple[ParentRegistrationRequest, str]:
    if not reason.strip():
        raise ValueError("操作理由を入力してください")
    from parent_enrollment import latest_enrollment, prepare_enrollment
    previous_enrollment = enrollment or latest_enrollment(session, account.id)
    if previous_enrollment and not previous_enrollment.applied_at:
        enrollment = prepare_enrollment(session, account, previous_enrollment.child_name,
                                        previous_enrollment.child_id, previous_enrollment.guardian_order)
    else:
        _validate_invitation_ledger(session, account)
    credential = ensure_parent_credential(session, account)
    now = utc_now()
    recent_deliveries = session.exec(
        select(ParentMailDelivery)
        .where(
            ParentMailDelivery.parent_account_id == account.id,
            ParentMailDelivery.message_type == "invitation",
            ParentMailDelivery.created_at >= now - timedelta(days=1),
        )
        .order_by(ParentMailDelivery.created_at.desc())
    ).all()
    if recent_deliveries and ensure_utc(
        recent_deliveries[0].created_at
    ) > now - timedelta(seconds=60):
        raise ValueError("招待の再送は60秒以上あけてください")
    if len(recent_deliveries) >= 10:
        raise ValueError("本日の招待送信上限に達しました")
    previous = session.exec(
        select(ParentRegistrationRequest)
        .where(ParentRegistrationRequest.parent_account_id == account.id)
        .order_by(ParentRegistrationRequest.created_at.desc())
    ).first()
    cancel_open_parent_registrations(session, account.id, now)
    raw_token = secrets.token_urlsafe(32)
    registration = ParentRegistrationRequest(
        parent_account_id=account.id,
        email_normalized_snapshot=normalize_login_id(account.email),
        status="invited",
        invitation_token_hash=token_hash(raw_token),
        invitation_expires_at=now + INVITATION_TTL,
        created_at=now,
        updated_at=now,
    )
    session.add(registration)
    session.flush()
    if enrollment:
        enrollment.registration_request_id = registration.id
        session.add(enrollment)
    operation = "invitation_resend" if previous else "invitation_issue"
    session.add(
        ParentCredentialProvisioningAudit(
            parent_account_id=account.id,
            credential_id=credential.id,
            operation=operation,
            actor_user_id=actor_user.id,
            reason=reason.strip(),
        )
    )
    account.invited_at = now
    account.updated_at = now
    session.add(account)
    _event(
        session,
        event_type="parent_invitation_issued",
        result="success",
        reason_code=operation,
        credential=credential,
        parent_account_id=account.id,
    )
    _queue_registration_mail(session, registration, account, raw_token, "invitation")
    session.commit()
    return registration, raw_token


def _registration_base_url() -> str:
    return (
        os.getenv("HOIKUICT_PARENT_REGISTRATION_BASE_URL") or "http://localhost:8000"
    ).rstrip("/")


def registration_token_from_input(value: str, purpose: str) -> str:
    """Accept a mail code or our original fragment link without following it."""
    if purpose not in {"invite", "complete"}:
        raise ValueError("Unknown registration purpose.")
    value = value.strip()
    if len(value) > 2048:
        raise AuthenticationFailed("登録コードを確認してください。")
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        try:
            link = urlsplit(value)
            expected = urlsplit(
                f"{_registration_base_url()}/parent-portal/register/{purpose}"
            )
            if (
                (link.scheme, link.netloc, link.path)
                != (expected.scheme, expected.netloc, expected.path)
                or link.query
            ):
                raise ValueError("Not a registration link for this page.")
            value = link.fragment
        except ValueError:
            raise AuthenticationFailed("登録コードを確認してください。") from None
    if not re.fullmatch(r"[A-Za-z0-9_-]{43}", value):
        raise AuthenticationFailed("登録コードを確認してください。")
    return value


def list_pending_parent_registrations(session: Session):
    """Metadata for admin review queues; do not load tokens or submitted profiles."""
    return session.exec(
        select(
            ParentRegistrationRequest.id.label("registration_id"),
            ParentRegistrationRequest.parent_account_id,
            ParentRegistrationRequest.submitted_at,
            ParentRegistrationRequest.created_at,
            ParentEnrollment.child_name,
            ParentAccount.display_name,
            ParentAccount.email,
        )
        .join(ParentAccount, ParentAccount.id == ParentRegistrationRequest.parent_account_id)
        .outerjoin(ParentEnrollment, ParentEnrollment.registration_request_id == ParentRegistrationRequest.id)
        .where(ParentRegistrationRequest.status == "pending_review")
        .order_by(ParentRegistrationRequest.submitted_at, ParentRegistrationRequest.created_at)
    ).all()


def _queue_registration_mail(
    session: Session,
    registration: ParentRegistrationRequest,
    account: ParentAccount,
    raw_token: str,
    message_type: str,
) -> None:
    if message_type == "invitation":
        link = f"{_registration_base_url()}/parent-portal/register/invite#{raw_token}"
        subject = "保護者ポータル 初回登録のご案内"
        body = f"保護者ポータルの初回登録手続きを開始してください。\n\n{link}\n\nこのリンクは24時間有効です。"
        if session.get(ParentEnrollment, registration.id):
            subject = "入園時の情報入力のお願い"
            body = f"入園に必要なお子さま・保護者・連絡先の情報をご入力ください。園が内容を確認後、パスワード設定の案内をお送りします。\n\n{link}\n\nこのリンクは24時間有効です。"
    else:
        link = f"{_registration_base_url()}/parent-portal/register/complete#{raw_token}"
        subject = "保護者ポータル パスワード設定のご案内"
        body = f"施設での確認が完了しました。パスワードを設定してください。\n\n{link}\n\nこのリンクは24時間有効です。"
    body += (
        "\n\nリンクを開いても入力画面へ進めない場合は、画面の「登録コードまたはメールのリンク」に"
        "次の登録コードをコピーして貼り付けてください。Cloudflareの認証コードとは別のコードです。"
        f"\n\n登録コード：\n{raw_token}\n\n"
        "登録コードも24時間有効で、リンクと共通の1回限りです。他の方へ共有しないでください。"
    )
    session.add(
        ParentMailDelivery(
            parent_account_id=account.id,
            registration_request_id=registration.id,
            message_type=message_type,
            recipient=account.email,
            subject=subject,
            body=body,
        )
    )


def _mail_claim_conditions(at: datetime) -> tuple:
    return (
        or_(
            ParentMailDelivery.status == "pending",
            and_(
                ParentMailDelivery.status == "processing",
                ParentMailDelivery.lease_expires_at.is_not(None),
                ParentMailDelivery.lease_expires_at <= at,
            ),
        ),
        or_(
            ParentMailDelivery.next_retry_at.is_(None),
            ParentMailDelivery.next_retry_at <= at,
        ),
    )


def _action_code_mail_is_current(session: Session, delivery: ParentMailDelivery) -> bool:
    token = session.get(CredentialActionToken, delivery.action_token_hash) if delivery.action_token_hash else None
    if (
        token is None or token.action != delivery.message_type or token.consumed_at
        or token.revoked_at or ensure_utc(token.expires_at) <= utc_now()
    ):
        return False
    credential = session.get(PasswordCredential, token.credential_id)
    account = session.get(ParentAccount, delivery.parent_account_id)
    if (
        credential is None or credential.principal_type != PRINCIPAL_PARENT
        or credential.parent_account_id != delivery.parent_account_id
        or account is None or account.status != ParentAccountStatus.active
        or normalize_login_id(account.email) != normalize_login_id(delivery.recipient)
    ):
        return False
    if token.action == "parent_reset":
        return bool(credential.password_hash and credential.disabled_at is None)
    return not credential.password_hash or credential.disabled_at is not None


def dispatch_pending_parent_mail(
    session: Session,
    *,
    registration_request_id: UUID | None = None,
) -> None:
    now = utc_now()
    statement = select(ParentMailDelivery.id).where(*_mail_claim_conditions(now))
    if registration_request_id is not None:
        statement = statement.where(
            ParentMailDelivery.registration_request_id == registration_request_id
        )
    delivery_ids = session.exec(statement).all()
    transport = (
        (os.getenv("HOIKUICT_PARENT_MAIL_TRANSPORT") or "capture").strip().lower()
    )
    for delivery_id in delivery_ids:
        claimed_at = utc_now()
        claim_result = session.execute(
            update(ParentMailDelivery)
            .where(
                ParentMailDelivery.id == delivery_id,
                *_mail_claim_conditions(claimed_at),
            )
            .values(
                status="processing",
                attempt_count=ParentMailDelivery.attempt_count + 1,
                processing_started_at=claimed_at,
                lease_expires_at=claimed_at + PARENT_MAIL_LEASE,
                last_attempt_at=claimed_at,
            )
            .execution_options(synchronize_session=False)
        )
        session.commit()
        if claim_result.rowcount != 1:
            continue
        delivery = session.get(ParentMailDelivery, delivery_id)
        if delivery is None:
            continue
        if delivery.message_type in PARENT_CODE_MAIL_TYPES and not _action_code_mail_is_current(session, delivery):
            delivery.status = "cancelled"
            delivery.failure_code = "action_code_no_longer_valid"
            delivery.next_retry_at = None
            delivery.lease_expires_at = None
            session.add(delivery)
            session.commit()
            continue
        try:
            if transport == "capture":
                delivery.status = "captured"
            elif transport == "smtp":
                _send_smtp(delivery)
                delivery.status = "sent"
            else:
                raise RuntimeError("mail_transport_disabled")
            delivery.failure_code = None
            delivery.next_retry_at = None
            delivery.sent_at = utc_now()
        except Exception as exc:  # SMTP response bodies must not be persisted.
            delivery.status = "pending" if delivery.attempt_count < 3 else "failed"
            delivery.failure_code = type(exc).__name__[:64]
            if delivery.status == "pending":
                delivery.next_retry_at = utc_now() + PARENT_MAIL_RETRY_BASE * (
                    2 ** (delivery.attempt_count - 1)
                )
            else:
                delivery.next_retry_at = None
        delivery.lease_expires_at = None
        session.add(delivery)
        session.commit()


async def parent_mail_worker_loop() -> None:
    import database

    def run_cycle() -> None:
        with Session(database.engine) as worker_session:
            dispatch_pending_parent_mail(worker_session)

    while True:
        await asyncio.sleep(5)
        await asyncio.to_thread(run_cycle)


def _send_smtp(delivery: ParentMailDelivery) -> None:
    send_auth_mail(recipient=delivery.recipient, subject=delivery.subject, body=delivery.body)


def _issue_registration_session(
    session: Session,
    *,
    parent_account_id: int,
    purpose: str,
    registration_request_id: UUID | None = None,
    credential_id: UUID | None = None,
) -> str:
    raw = secrets.token_urlsafe(32)
    session.add(
        ParentRegistrationSession(
            token_hash=token_hash(raw),
            parent_account_id=parent_account_id,
            registration_request_id=registration_request_id,
            credential_id=credential_id,
            purpose=purpose,
            expires_at=utc_now() + REGISTRATION_SESSION_TTL,
        )
    )
    return raw


def exchange_invitation_token(session: Session, raw_token: str) -> str:
    now = utc_now()
    registration = session.exec(
        select(ParentRegistrationRequest).where(
            ParentRegistrationRequest.invitation_token_hash == token_hash(raw_token),
            ParentRegistrationRequest.status == "invited",
        )
    ).first()
    if registration is None:
        raise AuthenticationFailed("招待リンクを確認してください")
    account = session.get(ParentAccount, registration.parent_account_id)
    if ensure_utc(registration.invitation_expires_at) <= now or account is None:
        registration.status = "expired"
        registration.invitation_token_hash = None
        registration.updated_at = now
        session.add(registration)
        session.commit()
        raise AuthenticationFailed("招待リンクを確認してください")
    if registration.email_normalized_snapshot != normalize_login_id(account.email):
        registration.status = "expired"
        registration.invitation_token_hash = None
        session.add(registration)
        session.commit()
        raise AuthenticationFailed("招待リンクを確認してください")
    if account.status != ParentAccountStatus.active:
        raise AuthenticationFailed("招待リンクを確認してください")
    raw_state = _issue_registration_session(
        session,
        parent_account_id=registration.parent_account_id,
        registration_request_id=registration.id,
        purpose="identity",
    )
    if session.get(ParentEnrollment, registration.id):
        state = session.get(ParentRegistrationSession, token_hash(raw_state))
        state.expires_at = now + timedelta(hours=2)
        session.add(state)
    registration.invitation_token_hash = None
    registration.updated_at = now
    session.add(registration)
    session.commit()
    return raw_state


def _get_registration_session(
    session: Session,
    raw_state: str,
    purpose: str,
    *,
    consume: bool = False,
) -> ParentRegistrationSession:
    state = session.get(ParentRegistrationSession, token_hash(raw_state or ""))
    now = utc_now()
    if (
        state is None
        or state.purpose != purpose
        or state.consumed_at is not None
        or ensure_utc(state.expires_at) <= now
    ):
        raise AuthenticationFailed("手続きを最初からやり直してください")
    if consume:
        state.consumed_at = now
        session.add(state)
    return state


def submit_parent_identity(
    session: Session,
    *,
    raw_state: str,
    guardian_name: str,
    child_name: str,
    child_birth_date: date,
) -> ParentRegistrationRequest:
    state = _get_registration_session(session, raw_state, "identity")
    registration = session.get(ParentRegistrationRequest, state.registration_request_id)
    if session.get(ParentEnrollment, state.registration_request_id):
        raise AuthenticationFailed("初回情報入力フォームから送信してください")
    account = session.get(ParentAccount, state.parent_account_id)
    if (
        registration is None
        or account is None
        or registration.status not in {"invited", "pending_review"}
    ):
        raise AuthenticationFailed("手続きを最初からやり直してください")
    if registration.verification_attempt_count >= MAX_VERIFICATION_ATTEMPTS:
        registration.status = "expired"
        registration.updated_at = utc_now()
        session.add(registration)
        session.commit()
        raise AuthenticationFailed("手続きを最初からやり直してください")
    registration.verification_attempt_count += 1
    guardian_match = hmac.compare_digest(
        normalize_verification_name(
            guardian_name, account.registration_verification_name_type
        ).encode("utf-8"),
        normalize_verification_name(
            account.registration_verification_name,
            account.registration_verification_name_type,
        ).encode("utf-8"),
    )
    matched_link = None
    child_name_any = False
    birth_date_any = False
    for link in _linked_children(session, account.id):
        child = link.child
        if (
            not child
            or child.registration_verification_name_type not in {"kana", "latin"}
            or not child.registration_verification_name
        ):
            continue
        name_match = hmac.compare_digest(
            normalize_verification_name(
                child_name, child.registration_verification_name_type
            ).encode("utf-8"),
            normalize_verification_name(
                child.registration_verification_name,
                child.registration_verification_name_type,
            ).encode("utf-8"),
        )
        birth_match = child.birth_date == child_birth_date
        child_name_any = child_name_any or name_match
        birth_date_any = birth_date_any or birth_match
        if name_match and birth_match:
            matched_link = link
            break
    registration.guardian_name_matched = guardian_match
    registration.child_name_matched = (
        bool(matched_link) if matched_link else child_name_any
    )
    registration.child_birth_date_matched = (
        bool(matched_link) if matched_link else birth_date_any
    )
    registration.matched_child_id = (
        matched_link.child_id if guardian_match and matched_link else None
    )
    matched = bool(registration.matched_child_id)
    exhausted = (
        registration.verification_attempt_count >= MAX_VERIFICATION_ATTEMPTS
        and not matched
    )
    registration.status = "expired" if exhausted else "pending_review"
    if matched or exhausted:
        state.consumed_at = utc_now()
        session.add(state)
    registration.submitted_at = utc_now()
    registration.updated_at = utc_now()
    session.add(registration)
    session.commit()
    return registration


def review_parent_registration(
    session: Session,
    *,
    registration: ParentRegistrationRequest,
    actor_user: User,
    approve: bool,
    reason: str,
    enrollment_confirmed: bool = False,
) -> str | None:
    if not reason.strip():
        raise ValueError("操作理由を入力してください")
    if registration.status != "pending_review":
        raise ValueError("確認待ちの申請ではありません")
    account = session.get(ParentAccount, registration.parent_account_id)
    if account is None or account.status != ParentAccountStatus.active:
        raise ValueError("保護者アカウントが見つかりません")
    credential = _credential_for_parent(session, account.id)
    now = utc_now()
    raw_token = None
    if approve:
        enrollment = session.get(ParentEnrollment, registration.id)
        if enrollment:
            if not enrollment_confirmed:
                raise ValueError("初回入力の内容と保護者・園児の対応を確認してください")
            from parent_enrollment import apply_enrollment
            apply_enrollment(session, registration, account, actor_user)
        elif not (
            registration.guardian_name_matched
            and registration.child_name_matched
            and registration.child_birth_date_matched
            and registration.matched_child_id
        ):
            raise ValueError("照合結果に不一致がある申請は承認できません")
        current_link = session.exec(
            select(ParentChildLink).where(
                ParentChildLink.parent_account_id == account.id,
                ParentChildLink.child_id == registration.matched_child_id,
            )
        ).first()
        if current_link is None:
            raise ValueError("園児との紐付けが変更されています。再招待してください")
        if registration.email_normalized_snapshot != normalize_login_id(account.email):
            raise ValueError("メールアドレスが変更されています。再招待してください")
        raw_token = secrets.token_urlsafe(32)
        registration.status = "approved"
        registration.completion_token_hash = token_hash(raw_token)
        registration.completion_expires_at = now + INVITATION_TTL
        operation = "registration_approve"
        _queue_registration_mail(
            session, registration, account, raw_token, "completion"
        )
    else:
        registration.status = "rejected"
        registration.completion_token_hash = None
        operation = "registration_reject"
    registration.reviewed_by_user_id = actor_user.id
    registration.reviewed_at = now
    registration.review_reason = reason.strip()
    registration.updated_at = now
    session.add(registration)
    session.add(
        ParentCredentialProvisioningAudit(
            parent_account_id=account.id,
            credential_id=credential.id if credential else None,
            operation=operation,
            actor_user_id=actor_user.id,
            reason=reason.strip(),
        )
    )
    session.commit()
    return raw_token


def exchange_completion_token(session: Session, raw_token: str) -> str:
    now = utc_now()
    registration = session.exec(
        select(ParentRegistrationRequest).where(
            ParentRegistrationRequest.completion_token_hash == token_hash(raw_token),
            ParentRegistrationRequest.status == "approved",
        )
    ).first()
    if registration is None:
        raise AuthenticationFailed("パスワード設定リンクを確認してください")
    if ensure_utc(registration.completion_expires_at) <= now:
        registration.status = "expired"
        registration.completion_token_hash = None
        registration.updated_at = now
        session.add(registration)
        session.commit()
        raise AuthenticationFailed("パスワード設定リンクを確認してください")
    account = session.get(ParentAccount, registration.parent_account_id)
    if (
        account is None
        or account.status != ParentAccountStatus.active
        or registration.email_normalized_snapshot != normalize_login_id(account.email)
        or session.exec(
            select(ParentChildLink).where(
                ParentChildLink.parent_account_id == registration.parent_account_id,
                ParentChildLink.child_id == registration.matched_child_id,
            )
        ).first()
        is None
    ):
        registration.status = "expired"
        registration.completion_token_hash = None
        registration.updated_at = now
        session.add(registration)
        session.commit()
        raise AuthenticationFailed("パスワード設定リンクを確認してください")
    credential = _credential_for_parent(session, registration.parent_account_id)
    raw_state = _issue_registration_session(
        session,
        parent_account_id=registration.parent_account_id,
        registration_request_id=registration.id,
        credential_id=credential.id if credential else None,
        purpose="complete",
    )
    registration.completion_token_hash = None
    registration.updated_at = now
    session.add(registration)
    session.commit()
    return raw_state


def complete_parent_registration(
    session: Session,
    *,
    raw_state: str,
    password: str,
    password_confirmation: str,
) -> ParentAccount:
    state = _get_registration_session(session, raw_state, "complete", consume=True)
    registration = session.get(ParentRegistrationRequest, state.registration_request_id)
    account = session.get(ParentAccount, state.parent_account_id)
    credential = (
        _credential_for_parent(session, account.id) if account is not None else None
    )
    if (
        account is None
        or registration is None
        or registration.status != "approved"
        or credential is None
    ):
        raise AuthenticationFailed("手続きを最初からやり直してください")
    normalized = validate_new_password(
        password,
        login_id=credential.login_id,
        email=account.email,
        display_name=account.display_name,
    )
    if not hmac.compare_digest(
        normalized.encode(), normalize_password(password_confirmation).encode()
    ):
        raise PasswordPolicyError("確認用パスワードが一致しません")
    now = utc_now()
    credential.password_hash = hash_password(normalized)
    credential.password_changed_at = now
    credential.disabled_at = None
    credential.disabled_reason = None
    credential.credential_version += 1
    credential.updated_at = now
    registration.status = "completed"
    registration.completed_at = now
    registration.updated_at = now
    session.add(credential)
    session.add(registration)
    _event(
        session,
        event_type="password_activated",
        result="success",
        reason_code="registration_completed",
        credential=credential,
        parent_account_id=account.id,
    )
    session.commit()
    return account


def authenticate_parent(
    session: Session,
    *,
    login_id: str,
    password: str,
    request: Request | None = None,
) -> ParentLoginResult:
    now = utc_now()
    normalized = normalize_login_id(login_id)
    account_bucket = _bucket_hash(PRINCIPAL_PARENT, "account", normalized)
    network_bucket = _bucket_hash(
        PRINCIPAL_PARENT, "network", _request_network(request)
    )
    if _is_bucket_blocked(session, account_bucket, now) or _is_bucket_blocked(
        session, network_bucket, now
    ):
        _event(
            session,
            event_type="login_throttled",
            result="failure",
            reason_code="temporarily_blocked",
            request=request,
            network_bucket_hash=network_bucket,
        )
        session.commit()
        raise LoginThrottled(PARENT_LOGIN_FAILURE_MESSAGE)
    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_PARENT,
            PasswordCredential.login_id_normalized == normalized,
        )
    ).first()
    password_hash = (
        credential.password_hash
        if credential and credential.password_hash
        else _dummy_hash()
    )
    password_matches = verify_password(password_hash, password)
    account = (
        session.get(ParentAccount, credential.parent_account_id) if credential else None
    )
    valid = bool(
        password_matches
        and credential
        and credential.password_hash
        and credential.hash_scheme == "argon2id"
        and credential.disabled_at is None
        and account
        and account.status == ParentAccountStatus.active
    )
    if not valid:
        _record_failure(session, account_bucket, "account", now)
        _record_failure(session, network_bucket, "network", now)
        _event(
            session,
            event_type="login",
            result="failure",
            reason_code="invalid_credentials",
            credential=credential,
            parent_account_id=account.id if account else None,
            request=request,
            network_bucket_hash=network_bucket,
        )
        session.commit()
        raise AuthenticationFailed(PARENT_LOGIN_FAILURE_MESSAGE)
    throttle = session.get(LoginThrottle, account_bucket)
    if throttle:
        session.delete(throttle)
    if PASSWORD_HASHER.check_needs_rehash(credential.password_hash):
        credential.password_hash = hash_password(password)
        credential.updated_at = now
        session.add(credential)
    raw = _create_parent_auth_session(session, account, credential, now)
    account.last_login_at = now
    account.updated_at = now
    session.add(account)
    _event(
        session,
        event_type="login",
        result="success",
        reason_code="password_verified",
        credential=credential,
        parent_account_id=account.id,
        request=request,
        network_bucket_hash=network_bucket,
    )
    session.commit()
    return ParentLoginResult(account=account, credential=credential, session_token=raw)


def _create_parent_auth_session(
    session: Session,
    account: ParentAccount,
    credential: PasswordCredential,
    now: datetime | None = None,
) -> str:
    created_at = now or utc_now()
    raw = secrets.token_urlsafe(32)
    absolute = created_at + PARENT_SESSION_ABSOLUTE
    session.add(
        AuthSession(
            token_hash=token_hash(raw),
            principal_type=PRINCIPAL_PARENT,
            credential_id=credential.id,
            parent_account_id=account.id,
            credential_version=credential.credential_version,
            created_at=created_at,
            last_seen_at=created_at,
            idle_expires_at=min(created_at + PARENT_SESSION_IDLE, absolute),
            absolute_expires_at=absolute,
        )
    )
    return raw


def resolve_parent_session(session: Session, raw_token: str) -> ParentAccount | None:
    if not raw_token or len(raw_token) > 256:
        return None
    now = utc_now()
    auth_session = session.get(AuthSession, token_hash(raw_token))
    if (
        not auth_session
        or auth_session.principal_type != PRINCIPAL_PARENT
        or auth_session.revoked_at
    ):
        return None
    credential = session.get(PasswordCredential, auth_session.credential_id)
    account = (
        session.get(ParentAccount, auth_session.parent_account_id)
        if auth_session.parent_account_id
        else None
    )
    reason = None
    if ensure_utc(auth_session.idle_expires_at) <= now:
        reason = "idle_expired"
    elif ensure_utc(auth_session.absolute_expires_at) <= now:
        reason = "absolute_expired"
    elif not credential or credential.disabled_at:
        reason = "credential_disabled"
    elif credential.credential_version != auth_session.credential_version:
        reason = "credential_version_changed"
    elif not account or account.status != ParentAccountStatus.active:
        reason = "parent_disabled"
    if reason:
        auth_session.revoked_at = now
        auth_session.revoke_reason = reason
        session.add(auth_session)
        session.commit()
        return None
    if ensure_utc(auth_session.last_seen_at) <= now - timedelta(minutes=5):
        auth_session.last_seen_at = now
        auth_session.idle_expires_at = min(
            now + PARENT_SESSION_IDLE, ensure_utc(auth_session.absolute_expires_at)
        )
        session.add(auth_session)
        session.commit()
    return account


def revoke_parent_session_token(
    session: Session, raw_token: str | None, reason: str = "explicit_logout"
) -> None:
    if not raw_token:
        return
    auth_session = session.get(AuthSession, token_hash(raw_token))
    if (
        not auth_session
        or auth_session.principal_type != PRINCIPAL_PARENT
        or auth_session.revoked_at
    ):
        return
    auth_session.revoked_at = utc_now()
    auth_session.revoke_reason = reason
    session.add(auth_session)
    _event(
        session,
        event_type="logout",
        result="success",
        reason_code=reason,
        parent_account_id=auth_session.parent_account_id,
    )
    session.commit()


def revoke_parent_sessions(
    session: Session, parent_account_id: int, reason: str, now: datetime | None = None
) -> None:
    revoked_at = now or utc_now()
    sessions = session.exec(
        select(AuthSession).where(
            AuthSession.principal_type == PRINCIPAL_PARENT,
            AuthSession.parent_account_id == parent_account_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    for item in sessions:
        item.revoked_at = revoked_at
        item.revoke_reason = reason
        session.add(item)


def disable_parent_push_subscriptions(
    session: Session, parent_account_id: int, reason: str, now: datetime | None = None
) -> None:
    disabled_at = now or utc_now()
    subscriptions = session.exec(
        select(ParentPushSubscription).where(
            ParentPushSubscription.parent_account_id == parent_account_id,
            ParentPushSubscription.status == ParentPushSubscriptionStatus.active,
        )
    ).all()
    for item in subscriptions:
        item.status = ParentPushSubscriptionStatus.revoked
        item.disabled_at = disabled_at
        item.disabled_reason = reason
        item.updated_at = disabled_at
        session.add(item)


def issue_parent_password_code(
    session: Session,
    *,
    account: ParentAccount,
    actor_user: User,
    reason: str,
    action: str = "parent_reset",
    send_email: bool = False,
) -> str:
    if not reason.strip():
        raise ValueError("操作理由を入力してください")
    if action == "parent_activate":
        from parent_enrollment import latest_enrollment
        enrollment = latest_enrollment(session, account.id)
        if enrollment and not enrollment.applied_at:
            raise ValueError("保護者の初回入力を確認して承認してください")
        _validate_invitation_ledger(session, account)
    elif action != "parent_reset":
        raise ValueError("未対応の保護者資格情報操作です")
    credential = ensure_parent_credential(session, account)
    if action == "parent_reset":
        if not credential.password_hash:
            raise ValueError("この保護者は初期登録を完了していません")
        if (
            credential.disabled_at is not None
            or account.status != ParentAccountStatus.active
        ):
            raise ValueError("停止中の保護者には再設定コードを発行できません")
    elif credential.password_hash and credential.disabled_at is None:
        raise ValueError("有効な保護者には初期設定コードを発行できません")
    if send_email:
        _validate_action_code_mail_request(session, account)
    raw_code = issue_credential_action_token(
        session,
        credential=credential,
        action=action,
        expires_in=PARENT_ACTION_CODE_TTL,
        created_by_user_id=actor_user.id,
    )
    session.add(
        ParentCredentialProvisioningAudit(
            parent_account_id=account.id,
            credential_id=credential.id,
            operation="reset_issue"
            if action == "parent_reset"
            else "reactivation_issue",
            actor_user_id=actor_user.id,
            reason=reason.strip(),
        )
    )
    # Reissuing a code invalidates older queued messages, including manual reissues.
    for delivery in session.exec(select(ParentMailDelivery).where(
        ParentMailDelivery.parent_account_id == account.id,
        ParentMailDelivery.message_type == action,
        ParentMailDelivery.status == "pending",
    )).all():
        delivery.status = "cancelled"
        delivery.next_retry_at = None
        session.add(delivery)
    if send_email:
        session.flush()
        token = session.get(CredentialActionToken, token_hash(raw_code))
        action_path = "activate" if action == "parent_activate" else "reset"
        label = "初回パスワード設定・利用再開" if action == "parent_activate" else "パスワード再設定"
        base_url = _registration_base_url()
        session.add(ParentMailDelivery(
            parent_account_id=account.id, action_token_hash=token.token_hash,
            message_type=action, recipient=account.email,
            subject=f"保護者ポータル {label}のご案内",
            body=(
                f"施設から{label}の案内が届いています。\n"
                "次のURLを開き、認証コードを入力してパスワードを設定してください。\n\n"
                f"コード入力URL：\n{base_url}/parent-portal/{action_path}\n\n"
                f"認証コード：{raw_code}\n"
                f"有効期限：{format_jst_datetime(token.expires_at)} JST（発行から24時間・1回限り）\n\n"
                f"設定後のログインURL：\n{base_url}/parent-portal/login\n"
                f"ログインID：{credential.login_id}\n\n"
                "認証コードはログイン用のパスワードではありません。設定したパスワードでログインしてください。\n"
                "Cloudflareの認証が表示された場合は、その認証を済ませてから上記のコードを入力してください。\n"
                "心当たりがない場合や期限が切れた場合は施設へご連絡ください。"
            ),
        ))
    session.commit()
    return raw_code


def _validate_action_code_mail_request(session: Session, account: ParentAccount) -> None:
    from family_support import validate_parent_contact_email

    validate_parent_contact_email(session, account.email, account.id)
    if (os.getenv("HOIKUICT_PARENT_MAIL_TRANSPORT") or "capture").strip().lower() not in {"capture", "smtp"}:
        raise ValueError("メール送信が無効です。送信設定を確認してください")
    now = utc_now()
    recent = session.exec(select(ParentMailDelivery.created_at).where(
        ParentMailDelivery.parent_account_id == account.id,
        ParentMailDelivery.message_type.in_(PARENT_CODE_MAIL_TYPES),
        ParentMailDelivery.created_at >= now - timedelta(days=1),
    ).order_by(ParentMailDelivery.created_at.desc())).all()
    if recent and ensure_utc(recent[0]) > now - timedelta(seconds=60):
        raise ValueError("コードの再発行・メール送信は60秒以上あけてください")
    if len(recent) >= 10:
        raise ValueError("本日のコード送信上限に達しました")


def exchange_parent_action_code(
    session: Session,
    raw_code: str,
    action: str,
    request: Request | None = None,
) -> str:
    normalized = raw_code.strip().upper()
    now = utc_now()
    network_bucket = _bucket_hash(
        PRINCIPAL_PARENT, "action_code", _request_network(request)
    )
    if _is_bucket_blocked(session, network_bucket, now):
        raise LoginThrottled("再設定コードを確認してください")
    token = session.get(CredentialActionToken, token_hash(normalized))
    if (
        not token
        or token.action != action
        or token.consumed_at
        or token.revoked_at
        or ensure_utc(token.expires_at) <= now
    ):
        _record_failure(session, network_bucket, "action_code", now)
        session.commit()
        raise AuthenticationFailed("再設定コードを確認してください")
    credential = session.get(PasswordCredential, token.credential_id)
    if not credential or credential.principal_type != PRINCIPAL_PARENT:
        _record_failure(session, network_bucket, "action_code", now)
        session.commit()
        raise AuthenticationFailed("再設定コードを確認してください")
    token.consumed_at = now
    session.add(token)
    raw_state = _issue_registration_session(
        session,
        parent_account_id=credential.parent_account_id,
        credential_id=credential.id,
        purpose=action,
    )
    session.commit()
    return raw_state


def complete_parent_action_password(
    session: Session,
    *,
    raw_state: str,
    purpose: str,
    password: str,
    password_confirmation: str,
) -> ParentAccount:
    if purpose not in {"parent_reset", "parent_activate"}:
        raise AuthenticationFailed("手続きを最初からやり直してください")
    state = _get_registration_session(session, raw_state, purpose, consume=True)
    account = session.get(ParentAccount, state.parent_account_id)
    credential = session.get(PasswordCredential, state.credential_id)
    if (
        account is None
        or credential is None
        or credential.parent_account_id != account.id
    ):
        raise AuthenticationFailed("手続きを最初からやり直してください")
    if account.status != ParentAccountStatus.active:
        raise AuthenticationFailed("手続きを最初からやり直してください")
    if purpose == "parent_reset" and credential.disabled_at is not None:
        raise AuthenticationFailed("手続きを最初からやり直してください")
    if purpose == "parent_activate":
        _validate_invitation_ledger(session, account)
    normalized = validate_new_password(
        password,
        login_id=credential.login_id,
        email=account.email,
        display_name=account.display_name,
    )
    if not hmac.compare_digest(
        normalized.encode(), normalize_password(password_confirmation).encode()
    ):
        raise PasswordPolicyError("確認用パスワードが一致しません")
    now = utc_now()
    credential.password_hash = hash_password(normalized)
    credential.password_changed_at = now
    if purpose == "parent_activate":
        credential.disabled_at = None
        credential.disabled_reason = None
    credential.credential_version += 1
    credential.updated_at = now
    account.updated_at = now
    session.add(credential)
    session.add(account)
    revoke_parent_sessions(session, account.id, "password_reset", now)
    disable_parent_push_subscriptions(session, account.id, "password_reset", now)
    _event(
        session,
        event_type="password_reset"
        if purpose == "parent_reset"
        else "password_activated",
        result="success",
        reason_code=purpose,
        credential=credential,
        parent_account_id=account.id,
    )
    session.commit()
    return account


def change_parent_password(
    session: Session,
    *,
    account: ParentAccount,
    current_password: str,
    new_password: str,
    password_confirmation: str,
) -> str:
    credential = _credential_for_parent(session, account.id)
    if (
        not credential
        or not credential.password_hash
        or not verify_password(credential.password_hash, current_password)
    ):
        raise AuthenticationFailed("現在のパスワードを確認してください")
    normalized = validate_new_password(
        new_password,
        login_id=credential.login_id,
        email=account.email,
        display_name=account.display_name,
    )
    if not hmac.compare_digest(
        normalized.encode(), normalize_password(password_confirmation).encode()
    ):
        raise PasswordPolicyError("確認用パスワードが一致しません")
    now = utc_now()
    credential.password_hash = hash_password(normalized)
    credential.password_changed_at = now
    credential.credential_version += 1
    credential.updated_at = now
    session.add(credential)
    revoke_parent_sessions(session, account.id, "password_changed", now)
    disable_parent_push_subscriptions(session, account.id, "password_changed", now)
    raw = _create_parent_auth_session(session, account, credential, now)
    _event(
        session,
        event_type="password_changed",
        result="success",
        reason_code="self_service",
        credential=credential,
        parent_account_id=account.id,
    )
    session.commit()
    return raw


def change_parent_login_id_by_admin(
    session: Session,
    *,
    account: ParentAccount,
    actor_user: User,
    new_email: str,
    reason: str,
) -> None:
    normalized_reason = reason.strip()
    if not normalized_reason:
        raise ValueError("変更理由を入力してください")
    if len(normalized_reason) > 300:
        raise ValueError("変更理由は300文字以内で入力してください")

    requested_email = (new_email or "").strip()
    normalized_login_id = normalize_login_id(requested_email)
    if (
        not normalized_login_id
        or len(requested_email) > 255
        or "@" not in requested_email
    ):
        raise ValueError("受信可能な新しいメールアドレスを入力してください")

    credential = _credential_for_parent(session, account.id)
    if credential is None or credential.password_hash is None:
        raise ValueError("初回登録完了後の保護者だけログインIDを変更できます")

    duplicate_credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_PARENT,
            PasswordCredential.login_id_normalized == normalized_login_id,
            PasswordCredential.id != credential.id,
        )
    ).first()
    if duplicate_credential is not None:
        raise ValueError("このメールアドレスは別の保護者ログインIDで使用されています")

    other_accounts = session.exec(
        select(ParentAccount).where(ParentAccount.id != account.id)
    ).all()
    if any(
        normalize_login_id(other.email) == normalized_login_id
        for other in other_accounts
    ):
        raise ValueError("このメールアドレスは別の保護者アカウントで使用されています")

    old_email = account.email
    old_login_id = credential.login_id
    if (
        normalize_login_id(old_email) == normalized_login_id
        and credential.login_id_normalized == normalized_login_id
    ):
        raise ValueError("登録メールアドレスとログインIDは既に同じ値です")

    now = utc_now()
    account.email = requested_email
    account.updated_at = now
    credential.login_id = requested_email
    credential.login_id_normalized = normalized_login_id
    credential.credential_version += 1
    credential.updated_at = now
    session.add(account)
    session.add(credential)

    if account.family_id is not None:
        family = session.get(Family, account.family_id)
        if family is not None:
            profiles = [dict(item) for item in family.guardian_profiles()]
            family_profile_changed = False
            for profile in profiles:
                if profile.get("parent_account_id") == account.id:
                    profile["email"] = requested_email
                    family_profile_changed = True
            if family_profile_changed:
                family.shared_profile = {"guardians": profiles}
                family.updated_at = now
                session.add(family)
    linked_guardians = session.exec(
        select(Guardian).where(Guardian.parent_account_id == account.id)
    ).all()
    for guardian in linked_guardians:
        guardian.email = requested_email
        session.add(guardian)

    revoke_parent_sessions(session, account.id, "login_id_changed", now)
    disable_parent_push_subscriptions(session, account.id, "login_id_changed", now)
    revoke_parent_recovery_artifacts(session, account.id, now)

    audit_reason = (
        f"{normalized_reason} | ログインID変更: {old_login_id} -> {requested_email}"
    )
    session.add(
        ParentCredentialProvisioningAudit(
            parent_account_id=account.id,
            credential_id=credential.id,
            operation="login_id_change",
            actor_user_id=actor_user.id,
            reason=audit_reason[:500],
        )
    )
    _event(
        session,
        event_type="login_id_changed",
        result="success",
        reason_code="admin_confirmed",
        credential=credential,
        parent_account_id=account.id,
    )

    subject = "保護者ポータル 登録メールアドレス変更のお知らせ"
    previous_recipients = {
        recipient.strip()
        for recipient in (old_email, old_login_id)
        if recipient and "@" in recipient and recipient.strip() != requested_email
    }
    for previous_recipient in previous_recipients:
        session.add(
            ParentMailDelivery(
                parent_account_id=account.id,
                message_type="login_id_change",
                recipient=previous_recipient,
                subject=subject,
                body=(
                    "保護者ポータルの登録メールアドレスとログインIDが変更されました。\n"
                    f"新しいログインID: {requested_email}\n\n"
                    "お心当たりがない場合は施設へご連絡ください。"
                ),
            )
        )
    session.add(
        ParentMailDelivery(
            parent_account_id=account.id,
            message_type="login_id_change",
            recipient=requested_email,
            subject=subject,
            body=(
                "保護者ポータルの登録メールアドレスとログインIDが変更されました。\n"
                "次回からこのメールアドレスと、これまでのパスワードでログインしてください。\n\n"
                "安全のため、ログイン中だった端末と通知登録は解除されています。"
            ),
        )
    )
    session.commit()


def disable_parent_authentication(
    session: Session, account: ParentAccount, actor_user: User, reason: str
) -> None:
    if not reason.strip():
        raise ValueError("操作理由を入力してください")
    now = utc_now()
    credential = suspend_parent_authentication(
        session,
        account,
        reason=reason.strip(),
        now=now,
    )
    session.add(
        ParentCredentialProvisioningAudit(
            parent_account_id=account.id,
            credential_id=credential.id if credential else None,
            operation="disable",
            actor_user_id=actor_user.id,
            reason=reason.strip(),
        )
    )
    _event(
        session,
        event_type="credential_disabled",
        result="success",
        reason_code="admin_disabled",
        credential=credential,
        parent_account_id=account.id,
    )
    session.commit()


def suspend_parent_authentication(
    session: Session,
    account: ParentAccount,
    *,
    reason: str,
    now: datetime | None = None,
) -> PasswordCredential | None:
    disabled_at = now or utc_now()
    credential = _credential_for_parent(session, account.id)
    if credential and not credential.disabled_at:
        credential.disabled_at = disabled_at
        credential.disabled_reason = reason
        credential.credential_version += 1
        credential.updated_at = disabled_at
        session.add(credential)
    revoke_parent_sessions(session, account.id, "credential_disabled", disabled_at)
    disable_parent_push_subscriptions(
        session, account.id, "credential_disabled", disabled_at
    )
    revoke_parent_recovery_artifacts(session, account.id, disabled_at)
    return credential


def revoke_parent_recovery_artifacts(
    session: Session,
    parent_account_id: int,
    now: datetime | None = None,
) -> None:
    revoked_at = now or utc_now()
    credential = _credential_for_parent(session, parent_account_id)
    if credential is not None:
        tokens = session.exec(
            select(CredentialActionToken).where(
                CredentialActionToken.credential_id == credential.id,
                CredentialActionToken.consumed_at.is_(None),
                CredentialActionToken.revoked_at.is_(None),
            )
        ).all()
        for token in tokens:
            token.revoked_at = revoked_at
            session.add(token)
    states = session.exec(
        select(ParentRegistrationSession).where(
            ParentRegistrationSession.parent_account_id == parent_account_id,
            ParentRegistrationSession.consumed_at.is_(None),
        )
    ).all()
    for state in states:
        state.consumed_at = revoked_at
        session.add(state)
    cancel_open_parent_registrations(session, parent_account_id, revoked_at)
