"""One view of parent access, and explicit administrator lifecycle transitions."""
from __future__ import annotations

import hashlib
import json

from sqlalchemy import update
from sqlmodel import Session, select

from models import (
    CredentialActionToken, ParentAccount, ParentAccountStatus, ParentChildLink,
    ParentCredentialProvisioningAudit, ParentRegistrationRequest,
    ParentRegistrationSession, PasswordCredential, User,
)
from time_utils import ensure_utc, utc_now


LABELS = {
    "active": "利用中", "stopped": "停止中", "resume_pending": "再開手続き待ち",
    "initial_pending": "初回設定待ち", "review": "登録確認待ち", "unregistered": "未登録",
}
ACTIONS = {
    "stop": "利用停止", "resume": "利用再開",
    "reset_resume": "パスワード再設定を伴う利用再開", "cancel_pending": "再開手続き取消",
}


class StaleParentLifecycle(ValueError):
    pass


def parent_lifecycle_states(session: Session, accounts) -> dict:
    accounts = list(accounts)
    ids = [a.id for a in accounts if a.id is not None]
    if not ids:
        return {}
    now = utc_now()
    credentials = {c.parent_account_id: c for c in session.exec(select(PasswordCredential).where(
        PasswordCredential.parent_account_id.in_(ids), PasswordCredential.principal_type == "parent",
    )).all()}
    credential_ids = [c.id for c in credentials.values()]
    pending = {}
    if credential_ids:
        for token in session.exec(select(CredentialActionToken).where(
            CredentialActionToken.credential_id.in_(credential_ids),
            CredentialActionToken.action.in_(["parent_activate", "parent_resume"]),
            CredentialActionToken.revoked_at.is_(None), CredentialActionToken.consumed_at.is_(None),
            CredentialActionToken.expires_at > now,
        )).all():
            pending.setdefault(token.credential_id, []).append((token.action, token.token_hash))
    for state in session.exec(select(ParentRegistrationSession).where(
        ParentRegistrationSession.parent_account_id.in_(ids),
        ParentRegistrationSession.purpose.in_(["parent_activate", "parent_resume", "complete"]),
        ParentRegistrationSession.consumed_at.is_(None), ParentRegistrationSession.expires_at > now,
    )).all():
        pending.setdefault(state.credential_id, []).append((state.purpose, state.token_hash))
    registrations = {}
    for reg in session.exec(select(ParentRegistrationRequest).where(
        ParentRegistrationRequest.parent_account_id.in_(ids),
    ).order_by(ParentRegistrationRequest.created_at, ParentRegistrationRequest.id)).all():
        registrations[reg.parent_account_id] = reg
    links = {}
    for link in session.exec(select(ParentChildLink).where(ParentChildLink.parent_account_id.in_(ids))).all():
        links.setdefault(link.parent_account_id, []).append((link.child_id, link.relationship_label, link.is_primary_contact))
    result = {}
    for account in accounts:
        c = credentials.get(account.id)
        reg = registrations.get(account.id)
        artifacts = sorted(pending.get(c.id, [])) if c else []
        has_password = bool(c and c.password_hash)
        stopped = account.email_removed or account.status != ParentAccountStatus.active or bool(c and c.disabled_at)
        resume_pending = has_password and any(kind in {"parent_resume", "parent_activate"} for kind, _ in artifacts)
        if account.email_removed:
            code = "stopped"
        elif not has_password and artifacts:
            code = "initial_pending"
        elif stopped:
            code = "resume_pending" if resume_pending else "stopped"
        elif has_password:
            code = "active"
        elif artifacts or (reg and reg.status == "approved" and reg.completion_expires_at and ensure_utc(reg.completion_expires_at) > now):
            code = "initial_pending"
        elif reg and reg.status == "pending_review":
            code = "review"
        else:
            code = "unregistered"
        snapshot = [str(account.status), account.email, str(account.updated_at),
                    [str(c.id), c.credential_version, str(c.disabled_at), c.must_change_password, str(c.updated_at)] if c else None,
                    artifacts, [str(reg.id), reg.status, str(reg.updated_at)] if reg else None,
                    sorted(links.get(account.id, [])), code]
        revision = hashlib.sha256(json.dumps(snapshot, ensure_ascii=False).encode()).hexdigest()
        result[account.id] = {
            "code": code, "label": LABELS[code], "revision": revision,
            "child_count": len(links.get(account.id, [])),
            "can_resume": code == "stopped" and has_password and not account.email_removed and not c.must_change_password,
            "can_reset_resume": code in {"stopped", "resume_pending"} and has_password and not account.email_removed,
            "requires_reset": bool(c and c.must_change_password),
        }
    return result


def parent_lifecycle_state(session: Session, account: ParentAccount) -> dict:
    return parent_lifecycle_states(session, [account])[account.id]


def validate_parent_lifecycle(session, account, *, action, reason, revision):
    state = parent_lifecycle_state(session, account)
    if revision != state["revision"]:
        raise StaleParentLifecycle("状態が更新されています。最新の内容を確認して、もう一度操作してください。")
    if not reason.strip() or len(reason.strip()) > 500:
        raise ValueError("操作理由を1〜500文字で入力してください。")
    allowed = {
        "stop": state["code"] not in {"stopped", "resume_pending"},
        "resume": state["can_resume"], "reset_resume": state["can_reset_resume"],
        "cancel_pending": state["code"] == "resume_pending",
    }
    if not allowed.get(action):
        raise ValueError("現在の状態ではこの操作を行えません。初回登録と利用再開は別の手続きです。")
    return state


def claim_parent_lifecycle(session, account):
    """Serialize transitions with an optimistic update, held until the caller commits."""
    now = utc_now()
    claimed = session.execute(update(ParentAccount).where(
        ParentAccount.id == account.id, ParentAccount.updated_at == account.updated_at,
        ParentAccount.status == account.status,
    ).values(updated_at=now).execution_options(synchronize_session=False))
    if claimed.rowcount != 1:
        raise StaleParentLifecycle("状態が更新されています。最新の内容を確認してください。")
    account.updated_at = now
    return now


def change_parent_lifecycle(session: Session, account: ParentAccount, actor: User, *, action: str, reason: str, revision: str):
    from parent_auth import (
        _credential_for_parent, _event, disable_parent_push_subscriptions,
        issue_parent_password_code, revoke_parent_recovery_artifacts,
        revoke_parent_sessions, suspend_parent_authentication,
    )
    if not actor.is_active or actor.staff_role != "admin":
        raise ValueError("利用停止・再開は管理者のみ操作できます。")
    validate_parent_lifecycle(session, account, action=action, reason=reason, revision=revision)
    now = claim_parent_lifecycle(session, account)
    credential = _credential_for_parent(session, account.id)
    if action in {"stop", "cancel_pending", "reset_resume"}:
        credential = suspend_parent_authentication(session, account, reason=reason.strip(), now=now)
        account.status = ParentAccountStatus.inactive
    if action == "resume":
        revoke_parent_sessions(session, account.id, "account_resumed", now)
        disable_parent_push_subscriptions(session, account.id, "account_resumed", now)
        revoke_parent_recovery_artifacts(session, account.id, now)
        credential.disabled_at = None
        credential.disabled_reason = None
        credential.credential_version += 1
        credential.updated_at = now
        account.status = ParentAccountStatus.active
        session.add(credential)
    if action == "reset_resume":
        # Same transaction as the suspension; a mail validation failure rolls it all back.
        issue_parent_password_code(session, account=account, actor_user=actor, reason=reason,
                                   action="parent_resume", send_email=True, commit=False)
    session.add(account)
    session.add(ParentCredentialProvisioningAudit(
        parent_account_id=account.id, credential_id=credential.id if credential else None,
        operation=action, actor_user_id=actor.id, reason=reason.strip(),
    ))
    _event(session, event_type="parent_lifecycle_changed", result="success", reason_code=action,
           credential=credential, parent_account_id=account.id)
    session.commit()
