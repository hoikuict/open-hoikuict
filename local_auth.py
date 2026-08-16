from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from uuid import UUID

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from fastapi import Request
from sqlmodel import Session, select

from models import (
    AuthenticationEvent,
    AuthSession,
    CredentialActionToken,
    InitialAdminBootstrapAudit,
    LoginThrottle,
    PasswordCredential,
    StaffCredentialProvisioningAudit,
    User,
    USER_SOURCE_MANUAL,
)
from security_config import deployment_environment
from staff_user_service import STAFF_USER_SORT_ORDER_LIMIT
from time_utils import ensure_utc, utc_now


PRINCIPAL_STAFF = "staff"
STAFF_SESSION_IDLE_MINUTES_DEFAULT = 30
STAFF_SESSION_ABSOLUTE_HOURS_DEFAULT = 12
LOGIN_WINDOW = timedelta(minutes=15)
ACCOUNT_FAILURE_LIMIT = 5
NETWORK_FAILURE_LIMIT = 20
ACTION_CODE_ALPHABET = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"
ACTION_CODE_LENGTH = 6
ACTION_CODE_TTL_MINUTES = 30
ACTION_CODE_TTL = timedelta(minutes=ACTION_CODE_TTL_MINUTES)
LOGIN_FAILURE_MESSAGE = "ログインIDまたはパスワードを確認してください"
ACTIVATION_FAILURE_MESSAGE = "有効化コードを確認してください"
RESET_FAILURE_MESSAGE = "再設定コードを確認してください"
PASSWORD_MIN_LENGTH = 8

PASSWORD_HASHER = PasswordHasher(
    time_cost=3,
    memory_cost=65_536,
    parallelism=1,
    hash_len=32,
    salt_len=16,
)

_dummy_password_hash: str | None = None
_BUILTIN_BLOCKLIST = {
    "password",
    "passwordpassword",
    "open-hoikuict",
    "openhoikuict",
    "hoikuhoiku",
    "123456789012345",
}


class AuthenticationFailed(Exception):
    pass


class LoginThrottled(AuthenticationFailed):
    pass


class PasswordPolicyError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class StaffLoginResult:
    user: User
    credential: PasswordCredential
    session_token: str


@dataclass(frozen=True, slots=True)
class StaffActivationDetails:
    credential: PasswordCredential
    user: User


def bootstrap_admin(
    session: Session,
    *,
    display_name: str,
    email: str,
    login_id: str,
    reason: str,
    actor: str,
    approver: str,
) -> tuple[User, str]:
    if not all(value.strip() for value in (display_name, email, login_id, reason, actor, approver)):
        raise ValueError("表示名、メール、ログインID、理由、実行者、承認者は必須です")
    active_admin = session.exec(
        select(User).where(User.is_active.is_(True), User.staff_role == "admin")
    ).first()
    if active_admin is not None:
        raise ValueError("有効な管理者が既に存在するため初期管理者を作成できません")
    duplicate_email = session.exec(
        select(User).where(User.email == email.strip())
    ).first()
    if duplicate_email is not None:
        raise ValueError("同じメールアドレスの職員が存在します")

    user = User(
        email=email.strip(),
        display_name=display_name.strip(),
        staff_role="admin",
        staff_sort_order=10,
        is_calendar_admin=True,
        can_manage_child_records=True,
        can_manage_billing_accounts=True,
        provisioning_source=USER_SOURCE_MANUAL,
        is_active=True,
    )
    session.add(user)
    session.flush()
    credential, activation_code = create_staff_credential(
        session,
        user=user,
        login_id=login_id,
    )
    session.add(
        InitialAdminBootstrapAudit(
            staff_user_id=user.id,
            credential_id=credential.id,
            actor=actor.strip(),
            approver=approver.strip(),
            reason=reason.strip(),
            database_fingerprint=hashlib.sha256(
                str(session.get_bind().url).encode("utf-8")
            ).hexdigest(),
        )
    )
    _add_event(
        session,
        event_type="bootstrap_admin",
        result="success",
        reason_code="offline_cli",
        credential=credential,
        staff_user_id=user.id,
        request_id=_bootstrap_audit_reference(reason, actor, approver),
    )
    session.commit()
    session.refresh(user)
    return user, activation_code


def normalize_login_id(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def normalize_password(value: str) -> str:
    return unicodedata.normalize("NFC", value)


def validate_new_password(
    password: str,
    *,
    login_id: str = "",
    email: str = "",
    display_name: str = "",
) -> str:
    normalized = normalize_password(password)
    if len(normalized) < PASSWORD_MIN_LENGTH:
        raise PasswordPolicyError(
            f"パスワードは{PASSWORD_MIN_LENGTH}文字以上で入力してください"
        )
    if len(normalized) > 128 or len(normalized.encode("utf-8")) > 1_024:
        raise PasswordPolicyError("パスワードは128文字、UTF-8で1024バイト以内にしてください")
    if any(unicodedata.category(char).startswith("C") for char in normalized):
        raise PasswordPolicyError("パスワードに制御文字は使用できません")

    comparison = normalized.casefold()
    blocked = _load_password_blocklist()
    if comparison in blocked:
        raise PasswordPolicyError("推測されやすいパスワードは使用できません")

    for identity in (login_id, email, display_name):
        identity_normalized = normalize_login_id(identity)
        compact_identity = "".join(identity_normalized.split())
        if len(compact_identity) >= 4 and compact_identity in "".join(comparison.split()):
            raise PasswordPolicyError("ログインIDや氏名を含むパスワードは使用できません")
    return normalized


def hash_password(password: str) -> str:
    return PASSWORD_HASHER.hash(normalize_password(password))


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return PASSWORD_HASHER.verify(password_hash, normalize_password(password))
    except (InvalidHashError, VerificationError, VerifyMismatchError):
        return False


def create_staff_credential(
    session: Session,
    *,
    user: User,
    login_id: str,
    created_by_user_id: UUID | None = None,
) -> tuple[PasswordCredential, str]:
    normalized_login_id = normalize_login_id(login_id)
    if not normalized_login_id:
        raise ValueError("ログインIDを入力してください")
    if len(normalized_login_id) > 255:
        raise ValueError("ログインIDは255文字以内で入力してください")
    duplicate = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_STAFF,
            PasswordCredential.login_id_normalized == normalized_login_id,
        )
    ).first()
    if duplicate is not None:
        raise ValueError("同じログインIDの職員資格情報が存在します")
    existing = session.exec(
        select(PasswordCredential).where(PasswordCredential.staff_user_id == user.id)
    ).first()
    if existing is not None:
        raise ValueError("この職員には既に資格情報が存在します")

    credential = PasswordCredential(
        principal_type=PRINCIPAL_STAFF,
        staff_user_id=user.id,
        login_id=login_id.strip(),
        login_id_normalized=normalized_login_id,
        password_hash=None,
    )
    session.add(credential)
    session.flush()
    raw_token = issue_credential_action_token(
        session,
        credential=credential,
        action="activate",
        expires_in=ACTION_CODE_TTL,
        created_by_user_id=created_by_user_id,
    )
    _add_event(
        session,
        event_type="credential_created",
        result="success",
        reason_code="staff_credential_created",
        credential=credential,
        staff_user_id=user.id,
    )
    return credential, raw_token


def issue_existing_staff_activation(
    session: Session,
    *,
    user: User,
    login_id: str,
    reason: str,
    actor: str,
    approver: str,
) -> tuple[PasswordCredential, str]:
    if not user.is_active or user.staff_sort_order >= STAFF_USER_SORT_ORDER_LIMIT:
        raise ValueError("有効な職員だけを認証対象にできます")
    if not all(value.strip() for value in (login_id, reason, actor, approver)):
        raise ValueError("ログインID、理由、実行者、承認者は必須です")

    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_STAFF,
            PasswordCredential.staff_user_id == user.id,
        )
    ).first()
    if credential is None:
        credential, activation_code = create_staff_credential(
            session,
            user=user,
            login_id=login_id,
        )
        operation = "credential_created"
    else:
        if credential.password_hash is not None and credential.disabled_at is None:
            raise ValueError("この職員は既にパスワード認証を利用できます")
        if normalize_login_id(login_id) != credential.login_id_normalized:
            raise ValueError(
                f"この職員のログインIDは既に「{credential.login_id}」で登録されています"
            )
        if credential.disabled_at is not None:
            credential.disabled_at = None
            credential.disabled_reason = None
            credential.credential_version += 1
            credential.updated_at = utc_now()
            session.add(credential)
        activation_code = issue_credential_action_token(
            session,
            credential=credential,
            action="activate",
            expires_in=ACTION_CODE_TTL,
        )
        operation = "activation_reissued"

    session.add(
        StaffCredentialProvisioningAudit(
            staff_user_id=user.id,
            credential_id=credential.id,
            operation=operation,
            actor=actor.strip(),
            approver=approver.strip(),
            reason=reason.strip(),
        )
    )
    _add_event(
        session,
        event_type="activation_issued",
        result="success",
        reason_code=operation,
        credential=credential,
        staff_user_id=user.id,
        request_id=_bootstrap_audit_reference(reason, actor, approver),
    )
    session.commit()
    return credential, activation_code


def issue_credential_action_token(
    session: Session,
    *,
    credential: PasswordCredential,
    action: str,
    expires_in: timedelta,
    created_by_user_id: UUID | None = None,
) -> str:
    now = utc_now()
    existing_tokens = session.exec(
        select(CredentialActionToken).where(
            CredentialActionToken.credential_id == credential.id,
            CredentialActionToken.action == action,
            CredentialActionToken.consumed_at.is_(None),
            CredentialActionToken.revoked_at.is_(None),
        )
    ).all()
    for item in existing_tokens:
        item.revoked_at = now
        session.add(item)

    for _ in range(20):
        raw_token = "".join(
            secrets.choice(ACTION_CODE_ALPHABET) for _ in range(ACTION_CODE_LENGTH)
        )
        token_hash = _token_hash(raw_token)
        if session.get(CredentialActionToken, token_hash) is None:
            break
    else:  # pragma: no cover - 30 bitのコード空間では実運用上到達しない
        raise RuntimeError("認証コードを生成できませんでした")
    session.add(
        CredentialActionToken(
            token_hash=token_hash,
            credential_id=credential.id,
            action=action,
            created_by_user_id=created_by_user_id,
            created_at=now,
            expires_at=now + expires_in,
        )
    )
    return raw_token


def issue_staff_password_reset(
    session: Session,
    *,
    user: User,
    reason: str,
    actor_user: User,
) -> str:
    if not reason.strip():
        raise ValueError("発行理由を入力してください")
    if not user.is_active or user.staff_sort_order >= STAFF_USER_SORT_ORDER_LIMIT:
        raise ValueError("有効な職員だけがパスワードを再設定できます")
    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_STAFF,
            PasswordCredential.staff_user_id == user.id,
        )
    ).first()
    if (
        credential is None
        or credential.password_hash is None
        or credential.disabled_at is not None
    ):
        raise ValueError("先に職員認証の初期設定を完了してください")

    reset_code = issue_credential_action_token(
        session,
        credential=credential,
        action="reset_password",
        expires_in=ACTION_CODE_TTL,
        created_by_user_id=actor_user.id,
    )
    session.add(
        StaffCredentialProvisioningAudit(
            staff_user_id=user.id,
            credential_id=credential.id,
            operation="password_reset_issued",
            actor=actor_user.display_name,
            approver=actor_user.display_name,
            reason=reason.strip(),
        )
    )
    _add_event(
        session,
        event_type="password_reset_issued",
        result="success",
        reason_code="admin_issued",
        credential=credential,
        staff_user_id=user.id,
        request_id=f"actor:{actor_user.id}",
    )
    session.commit()
    return reset_code


def activate_staff_password(
    session: Session,
    *,
    activation_code: str,
    login_id: str | None = None,
    password: str,
    password_confirmation: str,
) -> User:
    now = utc_now()
    details = get_staff_activation_details(session, activation_code=activation_code)
    credential = details.credential
    user = details.user
    token = session.get(
        CredentialActionToken,
        _token_hash(_normalize_action_code(activation_code)),
    )

    requested_login_id = credential.login_id if login_id is None else login_id.strip()
    normalized_login_id = normalize_login_id(requested_login_id)
    if not normalized_login_id:
        raise PasswordPolicyError("ログインIDを入力してください")
    if len(normalized_login_id) > 255:
        raise PasswordPolicyError("ログインIDは255文字以内で入力してください")
    duplicate = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_STAFF,
            PasswordCredential.login_id_normalized == normalized_login_id,
            PasswordCredential.id != credential.id,
        )
    ).first()
    if duplicate is not None:
        raise PasswordPolicyError("このログインIDは既に使用されています")

    normalized_password = validate_new_password(
        password,
        login_id=requested_login_id,
        email=user.email,
        display_name=user.display_name,
    )
    if not hmac.compare_digest(
        normalized_password.encode("utf-8"),
        normalize_password(password_confirmation).encode("utf-8"),
    ):
        raise PasswordPolicyError("確認用パスワードが一致しません")

    credential.login_id = requested_login_id
    credential.login_id_normalized = normalized_login_id
    credential.password_hash = hash_password(normalized_password)
    credential.password_changed_at = now
    credential.credential_version += 1
    credential.must_change_password = False
    credential.updated_at = now
    token.consumed_at = now
    session.add(credential)
    session.add(token)
    revoke_staff_sessions(
        session,
        staff_user_id=user.id,
        reason="password_activated",
        now=now,
    )
    _add_event(
        session,
        event_type="password_activated",
        result="success",
        reason_code="activation_completed",
        credential=credential,
        staff_user_id=user.id,
    )
    session.commit()
    return user


def get_staff_activation_details(
    session: Session,
    *,
    activation_code: str,
    request: Request | None = None,
) -> StaffActivationDetails:
    now = utc_now()
    action_bucket = _action_code_bucket(request)
    if action_bucket and _is_bucket_blocked(session, action_bucket, now):
        raise LoginThrottled(ACTIVATION_FAILURE_MESSAGE)
    normalized_code = _normalize_action_code(activation_code)
    token = session.get(CredentialActionToken, _token_hash(normalized_code))
    if (
        token is None
        or token.action != "activate"
        or token.consumed_at is not None
        or token.revoked_at is not None
        or _as_utc(token.expires_at) <= now
    ):
        if action_bucket:
            _record_failure(session, action_bucket, "action_code", now)
            session.commit()
        raise AuthenticationFailed(ACTIVATION_FAILURE_MESSAGE)
    credential = session.get(PasswordCredential, token.credential_id)
    user = session.get(User, credential.staff_user_id) if credential else None
    if (
        credential is None
        or credential.principal_type != PRINCIPAL_STAFF
        or credential.disabled_at is not None
        or user is None
        or not user.is_active
        or user.staff_sort_order >= STAFF_USER_SORT_ORDER_LIMIT
    ):
        raise AuthenticationFailed(ACTIVATION_FAILURE_MESSAGE)
    return StaffActivationDetails(credential=credential, user=user)


def reset_staff_password(
    session: Session,
    *,
    reset_code: str,
    password: str,
    password_confirmation: str,
    request: Request | None = None,
) -> User:
    now = utc_now()
    action_bucket = _action_code_bucket(request)
    if action_bucket and _is_bucket_blocked(session, action_bucket, now):
        raise LoginThrottled(RESET_FAILURE_MESSAGE)
    normalized_code = _normalize_action_code(reset_code)
    token = session.get(CredentialActionToken, _token_hash(normalized_code))
    if (
        token is None
        or token.action != "reset_password"
        or token.consumed_at is not None
        or token.revoked_at is not None
        or _as_utc(token.expires_at) <= now
    ):
        if action_bucket:
            _record_failure(session, action_bucket, "action_code", now)
            session.commit()
        raise AuthenticationFailed(RESET_FAILURE_MESSAGE)
    credential = session.get(PasswordCredential, token.credential_id)
    user = session.get(User, credential.staff_user_id) if credential else None
    if (
        credential is None
        or credential.principal_type != PRINCIPAL_STAFF
        or credential.disabled_at is not None
        or user is None
        or not user.is_active
        or user.staff_sort_order >= STAFF_USER_SORT_ORDER_LIMIT
    ):
        raise AuthenticationFailed(RESET_FAILURE_MESSAGE)

    normalized_password = validate_new_password(
        password,
        login_id=credential.login_id,
        email=user.email,
        display_name=user.display_name,
    )
    if not hmac.compare_digest(
        normalized_password.encode("utf-8"),
        normalize_password(password_confirmation).encode("utf-8"),
    ):
        raise PasswordPolicyError("確認用パスワードが一致しません")

    credential.password_hash = hash_password(normalized_password)
    credential.password_changed_at = now
    credential.credential_version += 1
    credential.must_change_password = False
    credential.updated_at = now
    token.consumed_at = now
    session.add(credential)
    session.add(token)
    revoke_staff_sessions(
        session,
        staff_user_id=user.id,
        reason="password_reset",
        now=now,
    )
    _add_event(
        session,
        event_type="password_reset",
        result="success",
        reason_code="reset_completed",
        credential=credential,
        staff_user_id=user.id,
    )
    session.commit()
    return user


def authenticate_staff(
    session: Session,
    *,
    login_id: str,
    password: str,
    request: Request | None = None,
) -> StaffLoginResult:
    now = utc_now()
    normalized_login_id = normalize_login_id(login_id)
    network = _request_network(request)
    account_bucket = _bucket_hash(PRINCIPAL_STAFF, "account", normalized_login_id)
    network_bucket = _bucket_hash(PRINCIPAL_STAFF, "network", network)
    if _is_bucket_blocked(session, account_bucket, now) or _is_bucket_blocked(
        session, network_bucket, now
    ):
        _add_event(
            session,
            event_type="login_throttled",
            result="failure",
            reason_code="temporarily_blocked",
            network_bucket_hash=network_bucket,
            request=request,
        )
        session.commit()
        raise LoginThrottled(LOGIN_FAILURE_MESSAGE)

    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_STAFF,
            PasswordCredential.login_id_normalized == normalized_login_id,
        )
    ).first()
    password_hash = credential.password_hash if credential and credential.password_hash else _dummy_hash()
    password_matches = verify_password(password_hash, password)
    user = session.get(User, credential.staff_user_id) if credential else None
    valid = bool(
        password_matches
        and credential is not None
        and credential.password_hash is not None
        and credential.hash_scheme == "argon2id"
        and credential.disabled_at is None
        and user is not None
        and user.is_active
        and user.staff_sort_order < STAFF_USER_SORT_ORDER_LIMIT
    )
    if not valid:
        _record_failure(session, account_bucket, "account", now)
        _record_failure(session, network_bucket, "network", now)
        _add_event(
            session,
            event_type="login",
            result="failure",
            reason_code="invalid_credentials",
            credential=credential,
            staff_user_id=user.id if user else None,
            network_bucket_hash=network_bucket,
            request=request,
        )
        session.commit()
        raise AuthenticationFailed(LOGIN_FAILURE_MESSAGE)

    if PASSWORD_HASHER.check_needs_rehash(credential.password_hash):
        credential.password_hash = hash_password(password)
        credential.updated_at = now
        session.add(credential)

    throttle = session.get(LoginThrottle, account_bucket)
    if throttle is not None:
        session.delete(throttle)

    raw_session_token = secrets.token_urlsafe(32)
    absolute_expires_at = now + timedelta(hours=_staff_absolute_hours())
    auth_session = AuthSession(
        token_hash=_token_hash(raw_session_token),
        principal_type=PRINCIPAL_STAFF,
        credential_id=credential.id,
        staff_user_id=user.id,
        credential_version=credential.credential_version,
        created_at=now,
        last_seen_at=now,
        idle_expires_at=min(
            now + timedelta(minutes=_staff_idle_minutes()),
            absolute_expires_at,
        ),
        absolute_expires_at=absolute_expires_at,
    )
    session.add(auth_session)
    _add_event(
        session,
        event_type="login",
        result="success",
        reason_code="password_verified",
        credential=credential,
        staff_user_id=user.id,
        network_bucket_hash=network_bucket,
        request=request,
    )
    session.commit()
    session.refresh(user)
    return StaffLoginResult(user=user, credential=credential, session_token=raw_session_token)


def resolve_staff_session(session: Session, raw_token: str) -> User | None:
    if not raw_token or len(raw_token) > 256:
        return None
    now = utc_now()
    auth_session = session.get(AuthSession, _token_hash(raw_token))
    if auth_session is None or auth_session.principal_type != PRINCIPAL_STAFF:
        return None
    if auth_session.revoked_at is not None:
        return None

    credential = session.get(PasswordCredential, auth_session.credential_id)
    user = session.get(User, auth_session.staff_user_id) if auth_session.staff_user_id else None
    revoke_reason = None
    if _as_utc(auth_session.idle_expires_at) <= now:
        revoke_reason = "idle_expired"
    elif _as_utc(auth_session.absolute_expires_at) <= now:
        revoke_reason = "absolute_expired"
    elif credential is None or credential.disabled_at is not None:
        revoke_reason = "credential_disabled"
    elif credential.credential_version != auth_session.credential_version:
        revoke_reason = "credential_version_changed"
    elif (
        user is None
        or not user.is_active
        or user.staff_sort_order >= STAFF_USER_SORT_ORDER_LIMIT
    ):
        revoke_reason = "staff_disabled"
    if revoke_reason:
        auth_session.revoked_at = now
        auth_session.revoke_reason = revoke_reason
        session.add(auth_session)
        session.commit()
        return None

    if _as_utc(auth_session.last_seen_at) <= now - timedelta(minutes=5):
        auth_session.last_seen_at = now
        auth_session.idle_expires_at = min(
            now + timedelta(minutes=_staff_idle_minutes()),
            _as_utc(auth_session.absolute_expires_at),
        )
        session.add(auth_session)
        session.commit()
    return user


def revoke_session_token(
    session: Session,
    raw_token: str | None,
    *,
    reason: str = "explicit_logout",
) -> None:
    if not raw_token:
        return
    auth_session = session.get(AuthSession, _token_hash(raw_token))
    if auth_session is None or auth_session.revoked_at is not None:
        return
    auth_session.revoked_at = utc_now()
    auth_session.revoke_reason = reason
    session.add(auth_session)
    _add_event(
        session,
        event_type="logout",
        result="success",
        reason_code=reason,
        staff_user_id=auth_session.staff_user_id,
        credential_id=auth_session.credential_id,
    )
    session.commit()


def revoke_staff_sessions(
    session: Session,
    *,
    staff_user_id: UUID,
    reason: str,
    now: datetime | None = None,
) -> None:
    revoked_at = now or utc_now()
    sessions = session.exec(
        select(AuthSession).where(
            AuthSession.principal_type == PRINCIPAL_STAFF,
            AuthSession.staff_user_id == staff_user_id,
            AuthSession.revoked_at.is_(None),
        )
    ).all()
    for item in sessions:
        item.revoked_at = revoked_at
        item.revoke_reason = reason
        session.add(item)


def disable_staff_authentication(
    session: Session,
    *,
    user: User,
    changed_by_user_id: UUID | None,
    reason: str = "staff_account_disabled",
) -> None:
    now = utc_now()
    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.principal_type == PRINCIPAL_STAFF,
            PasswordCredential.staff_user_id == user.id,
        )
    ).first()
    if credential is not None and credential.disabled_at is None:
        credential.disabled_at = now
        credential.disabled_reason = reason
        credential.credential_version += 1
        credential.updated_at = now
        session.add(credential)
    revoke_staff_sessions(
        session,
        staff_user_id=user.id,
        reason=reason,
        now=now,
    )
    _add_event(
        session,
        event_type="credential_disabled",
        result="success",
        reason_code=reason,
        credential=credential,
        staff_user_id=user.id,
        request_id=(f"actor:{changed_by_user_id}" if changed_by_user_id else None),
    )


def _dummy_hash() -> str:
    global _dummy_password_hash
    if _dummy_password_hash is None:
        _dummy_password_hash = PASSWORD_HASHER.hash(secrets.token_urlsafe(32))
    return _dummy_password_hash


def _token_hash(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()


def _normalize_action_code(raw_code: str) -> str:
    code = raw_code.strip()
    upper_code = code.upper()
    if len(upper_code) == ACTION_CODE_LENGTH and all(
        character in ACTION_CODE_ALPHABET for character in upper_code
    ):
        return upper_code
    # 変更前に発行した長いコードは、そのコード固有の期限までは利用できる。
    return code


def _action_code_bucket(request: Request | None) -> str | None:
    if request is None:
        return None
    return _bucket_hash(PRINCIPAL_STAFF, "action_code", _request_network(request))


def _load_password_blocklist() -> set[str]:
    configured = os.getenv("HOIKUICT_PASSWORD_BLOCKLIST_PATH", "").strip()
    if not configured:
        return _BUILTIN_BLOCKLIST
    path = Path(configured)
    try:
        return {
            normalize_password(line.strip()).casefold()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        } | _BUILTIN_BLOCKLIST
    except OSError as exc:
        raise PasswordPolicyError("パスワード禁止リストを読み込めません") from exc


def _throttle_key() -> bytes:
    configured = os.getenv("HOIKUICT_LOGIN_THROTTLE_HMAC_KEY", "")
    if configured:
        return configured.encode("utf-8")
    if deployment_environment() in {"development", "test"}:
        return b"open-hoikuict-test-throttle-key-only"
    raise RuntimeError("HOIKUICT_LOGIN_THROTTLE_HMAC_KEY が必要です")


def _bucket_hash(principal_type: str, bucket_type: str, value: str) -> str:
    payload = f"{principal_type}\0{bucket_type}\0{value}".encode("utf-8")
    return hmac.new(_throttle_key(), payload, hashlib.sha256).hexdigest()


def _is_bucket_blocked(session: Session, bucket_hash: str, now: datetime) -> bool:
    throttle = session.get(LoginThrottle, bucket_hash)
    return bool(
        throttle
        and throttle.blocked_until is not None
        and _as_utc(throttle.blocked_until) > now
    )


def _record_failure(
    session: Session,
    bucket_hash: str,
    bucket_type: str,
    now: datetime,
) -> None:
    throttle = session.get(LoginThrottle, bucket_hash)
    if throttle is None:
        throttle = LoginThrottle(
            bucket_hash=bucket_hash,
            bucket_type=bucket_type,
            failure_count=0,
            window_started_at=now,
        )
    elif _as_utc(throttle.window_started_at) <= now - LOGIN_WINDOW:
        throttle.failure_count = 0
        throttle.window_started_at = now
        throttle.blocked_until = None
    throttle.failure_count += 1
    limit = ACCOUNT_FAILURE_LIMIT if bucket_type == "account" else NETWORK_FAILURE_LIMIT
    if throttle.failure_count >= limit:
        exponent = min(throttle.failure_count - limit, 5)
        throttle.blocked_until = now + timedelta(seconds=min(30 * (2**exponent), 900))
    throttle.updated_at = now
    session.add(throttle)


def _add_event(
    session: Session,
    *,
    event_type: str,
    result: str,
    reason_code: str,
    credential: PasswordCredential | None = None,
    credential_id: UUID | None = None,
    staff_user_id: UUID | None = None,
    network_bucket_hash: str | None = None,
    request: Request | None = None,
    request_id: str | None = None,
) -> None:
    session.add(
        AuthenticationEvent(
            event_type=event_type,
            result=result,
            reason_code=reason_code,
            principal_type=PRINCIPAL_STAFF,
            staff_user_id=staff_user_id,
            credential_id=credential.id if credential else credential_id,
            request_id=(request.headers.get("X-Request-ID") if request else request_id),
            network_bucket_hash=network_bucket_hash,
        )
    )


def _request_network(request: Request | None) -> str:
    if request is None or request.client is None:
        return "unknown"
    return request.client.host or "unknown"


def _bootstrap_audit_reference(reason: str, actor: str, approver: str) -> str:
    payload = "\0".join(item.strip() for item in (reason, actor, approver))
    return "bootstrap:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:32]


def _staff_idle_minutes() -> int:
    return _bounded_int(
        "HOIKUICT_STAFF_SESSION_IDLE_MINUTES",
        STAFF_SESSION_IDLE_MINUTES_DEFAULT,
        5,
        480,
    )


def _staff_absolute_hours() -> int:
    return _bounded_int(
        "HOIKUICT_STAFF_SESSION_ABSOLUTE_HOURS",
        STAFF_SESSION_ABSOLUTE_HOURS_DEFAULT,
        1,
        24,
    )


def staff_session_cookie_max_age() -> int:
    return _staff_absolute_hours() * 60 * 60


def _bounded_int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw is not None else default
    except ValueError as exc:
        raise RuntimeError(f"{name} は整数で指定してください") from exc
    if not minimum <= value <= maximum:
        raise RuntimeError(f"{name} は {minimum}〜{maximum} の範囲で指定してください")
    return value


def _as_utc(value: datetime) -> datetime:
    return ensure_utc(value) or value
