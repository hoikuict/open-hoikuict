"""Review and delete an unused family without cascading into nursery records."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import hmac
import json
import logging
from time import time

from fastapi import HTTPException
from sqlalchemy import column, delete, func, inspect, or_, table, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import Session, select

from auth import (
    LOCAL_STAFF_SESSION_COOKIE, PRODUCTION_STAFF_SESSION_COOKIE,
    require_child_record_manager,
)
from csrf import _secret_key
from models import Family, ParentEnrollment, ProfilePhoto
from security_config import is_production, is_public_demo, staff_auth_mode
from staff_permissions import get_live_staff_user
from time_utils import utc_now

# Uvicorn's configured application logger also captures successful audit events.
audit_logger = logging.getLogger("uvicorn.error.family_deletion")
NOTICE_COOKIE = "hoikuict_family_deleted"
REVIEW_SECONDS = 30 * 60
_GROUPS = (
    ("children", "園児（卒園・退園を含む）", "人", ("children",)),
    ("parents", "保護者アカウント（停止済みを含む）", "人", ("parent_accounts",)),
    ("billing", "請求設定", "件", ("family_billing_profiles",)),
    ("claims", "請求記録", "件", ("billing_claims",)),
    ("billing_history", "引落データ・請求設定変更履歴", "件", ("zengin_export_lines", "family_billing_profile_change_logs")),
    ("surveys", "アンケート回答", "件", ("survey_answers",)),
    ("photos", "家族に結びつく写真", "件", ("profile_photos",)),
    ("archive", "アーカイブ・復帰の履歴", "件", ("family_archive_logs",)),
)


@dataclass(frozen=True)
class DependencyCount:
    label: str
    count: int
    unit: str = "件"


class FamilyDeletionError(Exception):
    def __init__(self, code: str, message: str, status: int = 409):
        super().__init__(message)
        self.code, self.status = code, status


def require_family_deletion_manager(session: Session, current_user) -> None:
    require_child_record_manager(current_user)
    if not is_production() and staff_auth_mode() == "mock" and current_user.user_id is None:
        return
    actor = get_live_staff_user(session, current_user)
    if actor is None or not actor.can_manage_child_records_effective:
        raise HTTPException(403, "園児台帳管理権限が必要です")


def family_revision(family: Family) -> str:
    # Include creation time as SQLite can reuse a deleted row's numeric ID.
    data = family.model_dump(mode="json")
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()


def _binding(request, current_user) -> str:
    session_cookie = request.cookies.get(PRODUCTION_STAFF_SESSION_COOKIE) or request.cookies.get(LOCAL_STAFF_SESSION_COOKIE, "")
    actor = current_user.staff_id or ("mock:" + current_user.name)
    csrf = getattr(request.state, "csrf_token", "")
    binding = [actor, session_cookie, csrf]
    if is_public_demo():
        binding.append(getattr(request.state, "demo_session_id", ""))
    return hashlib.sha256(json.dumps(binding).encode()).hexdigest()


def _sign(payload: str, purpose: str) -> str:
    return hmac.new(_secret_key(), ("family-deletion-v1:" + purpose + ":" + payload).encode("ascii"), hashlib.sha256).hexdigest()


def _pack(data: dict, purpose: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()).decode()
    return payload + "." + _sign(payload, purpose)


def _unpack(token: str, purpose: str, request, current_user, max_age: int) -> dict:
    try:
        if not token or len(token) > 4096:
            raise ValueError
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature.encode("ascii"), _sign(payload, purpose).encode("ascii")):
            raise ValueError
        data = json.loads(base64.b64decode(payload, altchars=b"-_", validate=True))
        if not isinstance(data, dict) or data["binding"] != _binding(request, current_user):
            raise ValueError
        if not 0 <= time() - data["issued"] <= max_age:
            raise ValueError
        return data
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise FamilyDeletionError("invalid_confirmation", "削除の確認が無効か期限切れです。内容をもう一度確認してください。") from exc


def issue_review(request, current_user, family: Family) -> str:
    return _pack({"id": family.id, "revision": family_revision(family), "issued": time(),
                  "binding": _binding(request, current_user)}, "review")


def issue_notice(request, current_user, family_name: str, family_code: str) -> str:
    return _pack({"name": family_name[:200], "code": family_code, "issued": time(),
                  "binding": _binding(request, current_user)}, "notice")


def read_notice(request, current_user) -> str:
    try:
        data = _unpack(request.cookies.get(NOTICE_COOKIE, ""), "notice", request, current_user, 120)
        return f"{data['name']}（{data['code']}）を削除しました。"
    except (FamilyDeletionError, KeyError):
        return ""


def dependency_counts(session: Session, family: Family) -> list[DependencyCount]:
    """Inspect real FKs, including future tables, rather than only ORM relationships."""
    schema = inspect(session.connection())
    counts: dict[str, int] = {}
    known = {name for _, _, _, names in _GROUPS for name in names}
    for name in schema.get_table_names():
        columns = {
            col_name for fk in schema.get_foreign_keys(name)
            if fk.get("referred_table") == "families"
            for col_name in fk["constrained_columns"]
        }
        if name in known:
            columns.add("family_id")
        if columns:
            related = table(name, *(column(name) for name in columns))
            counts[name] = session.execute(select(func.count()).select_from(related).where(
                or_(*(related.c[name] == family.id for name in columns))
            )).scalar_one()

    # JSON guardian links can survive a move to another family. Do not silently
    # discard a stale account/photo association just because the FK count is zero.
    profiles = family.guardian_profiles()
    photo_ids = {str(p["photo_id"]) for p in profiles if p.get("photo_id")}
    linked_photo_ids = set(session.exec(select(ProfilePhoto.id).where(ProfilePhoto.family_id == family.id)).all())
    counts["profile_photos"] = len(photo_ids | linked_photo_ids)
    rows = [DependencyCount(label, sum(counts.get(name, 0) for name in names), unit)
            for _, label, unit, names in _GROUPS]
    account_links = {str(p["parent_account_id"]) for p in profiles if p.get("parent_account_id")}
    if account_links:
        rows.append(DependencyCount("保護者連絡先に保存されたアカウントの紐づけ", len(account_links)))
    extra = sum(count for name, count in counts.items() if name not in known)
    if extra:
        rows.append(DependencyCount("その他の関連記録", extra))
    enrollment_count = sum(
        isinstance(snapshot, dict) and str(snapshot.get("family_id")) == str(family.id)
        for snapshot in session.exec(select(ParentEnrollment.source_snapshot)).all()
    )
    if enrollment_count:
        rows.append(DependencyCount("保護者の初回入力依頼・記録", enrollment_count))
    return rows


def _audit(current_user, family_id: int, result: str) -> None:
    # IDs and outcome only; no family names, addresses, contact data or tokens.
    audit_logger.info("family_delete actor_id=%s family_id=%s result=%s occurred_at=%s",
                      current_user.staff_id or "mock", family_id, result, utc_now().isoformat())


def delete_unused_family(session: Session, *, request, current_user, family_id: int,
                         review_token: str, confirmed: str) -> tuple[str, str]:
    """Acquire the SQLite writer lock before rechecking permissions and all links."""
    session.rollback()
    try:
        if session.get_bind().dialect.name != "sqlite":
            raise FamilyDeletionError("unsupported_database", "この環境では家族の削除に対応していません。", 503)
        session.execute(text("BEGIN IMMEDIATE"))
        require_family_deletion_manager(session, current_user)
        family = session.get(Family, family_id)
        if family is None:
            raise FamilyDeletionError("missing", "この家族は既に削除されたか、見つかりません。", 404)
        if confirmed != "yes":
            raise FamilyDeletionError("unconfirmed", "内容を確認し、削除の確認欄にチェックしてください。", 400)
        review = _unpack(review_token, "review", request, current_user, REVIEW_SECONDS)
        if review.get("id") != family.id:
            raise FamilyDeletionError("wrong_family", "削除対象が確認時と異なります。内容をもう一度確認してください。")
        if any(row.count for row in dependency_counts(session, family)):
            raise FamilyDeletionError("related_records", "関連データが残っているため、この家族は削除できません。")
        if review.get("revision") != family_revision(family):
            raise FamilyDeletionError("changed", "確認後に家族情報が変更されました。内容をもう一度確認してください。")
        name, code = family.family_name, family.display_code
        # A Core DELETE cannot let SQLAlchemy clear member FKs as a side effect.
        session.execute(delete(Family).where(Family.id == family.id))
        session.commit()
    except FamilyDeletionError as exc:
        session.rollback()
        _audit(current_user, family_id, exc.code)
        raise
    except HTTPException:
        session.rollback()
        _audit(current_user, family_id, "forbidden")
        raise
    except SQLAlchemyError as exc:
        session.rollback()
        _audit(current_user, family_id, "database_error")
        raise FamilyDeletionError("database_error", "削除できませんでした。家族情報を再確認してから、時間をおいてお試しください。", 503) from exc
    _audit(current_user, family_id, "deleted")
    return name, code
