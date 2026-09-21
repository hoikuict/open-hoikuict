"""Reversible family visibility with explicit, auditable state transitions."""

from time import time

from sqlalchemy import or_, text
from sqlalchemy.exc import SQLAlchemyError
from sqlmodel import select

from family_deletion import (
    FamilyDeletionError,
    _binding,
    _pack,
    _unpack,
    family_revision,
    require_family_deletion_manager,
)
from models import (
    Child,
    ChildStatus,
    Family,
    FamilyArchiveLog,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentEnrollment,
    ParentRegistrationRequest,
)
from time_utils import utc_now

REASONS = ("整理中・判断を保留", "テスト登録", "使用終了", "重複の確認中", "その他")
require_archive_manager = require_family_deletion_manager


class FamilyArchiveError(Exception):
    def __init__(self, message, status=409):
        super().__init__(message)
        self.status = status


def archive_blockers(session, family):
    """Historical dependency counts are deliberately not archive blockers."""
    children = session.exec(select(Child).where(Child.family_id == family.id)).all()
    child_ids = [child.id for child in children]
    issues = []
    if any(child.status == ChildStatus.enrolled for child in children):
        issues.append("在園中の園児がいます。")
    account_ids = {
        int(p["parent_account_id"])
        for p in family.guardian_profiles()
        if str(p.get("parent_account_id", "")).isdigit()
    }
    if child_ids:
        account_ids.update(
            session.exec(
                select(ParentChildLink.parent_account_id).where(
                    ParentChildLink.child_id.in_(child_ids)
                )
            ).all()
        )
    accounts = session.exec(
        select(ParentAccount).where(
            or_(ParentAccount.family_id == family.id, ParentAccount.id.in_(account_ids))
        )
    ).all()
    if any(account.status == ParentAccountStatus.active for account in accounts):
        issues.append("有効な保護者アカウントがあります。")
    pending = session.exec(
        select(ParentEnrollment, ParentRegistrationRequest)
        .join(
            ParentRegistrationRequest,
            ParentRegistrationRequest.id == ParentEnrollment.registration_request_id,
        )
        .where(
            ParentEnrollment.applied_at.is_(None),
            ParentRegistrationRequest.status.in_(
                ["invited", "pending_review", "approved"]
            ),
        )
    ).all()
    if any(
        str((enrollment.source_snapshot or {}).get("family_id")) == str(family.id)
        or enrollment.child_id in child_ids
        or request.parent_account_id in {a.id for a in accounts}
        for enrollment, request in pending
    ):
        issues.append("保護者の初回入力依頼が進行中です。")
    return issues


def issue_archive_review(request, actor, family, action):
    return _pack(
        {
            "id": family.id,
            "action": action,
            "revision": family_revision(family),
            "issued": time(),
            "binding": _binding(request, actor),
        },
        "archive-review",
    )


def transition_family(
    session, *, request, actor, family_id, action, review_token, reason="", note=""
):
    session.rollback()
    if action not in {"archive", "restore"}:
        raise FamilyArchiveError("操作が不正です。", 400)
    reason, note = reason.strip(), note.strip()
    if (reason and reason not in REASONS) or len(note) > 500:
        raise FamilyArchiveError(
            "理由を選択し、メモは500文字以内で入力してください。", 400
        )
    try:
        if session.get_bind().dialect.name != "sqlite":
            raise FamilyArchiveError("この環境ではアーカイブに対応していません。", 503)
        session.execute(text("BEGIN IMMEDIATE"))
        require_archive_manager(session, actor)
        family = session.get(Family, family_id)
        if family is None:
            raise FamilyArchiveError("家族が見つかりません。", 404)
        try:
            review = _unpack(review_token, "archive-review", request, actor, 900)
        except FamilyDeletionError as exc:
            raise FamilyArchiveError(
                "確認が無効か期限切れです。内容をもう一度確認してください。"
            ) from exc
        if (
            review.get("id") != family.id
            or review.get("action") != action
            or review.get("revision") != family_revision(family)
        ):
            raise FamilyArchiveError(
                "確認後に家族の情報が変更されました。内容をもう一度確認してください。"
            )
        if family.is_archived != (action == "restore"):
            raise FamilyArchiveError(
                "この家族の状態は変更済みです。一覧で確認してください。"
            )
        if action == "archive":
            blockers = archive_blockers(session, family)
            if blockers:
                raise FamilyArchiveError(" ".join(blockers))
        session.info["family_archive_transition"] = True
        family.archived_at = utc_now() if action == "archive" else None
        family.updated_at = utc_now()
        session.add(
            FamilyArchiveLog(
                family_id=family.id,
                action=action,
                reason=reason if action == "archive" else "",
                note=note,
                actor_id=str(actor.user_id) if actor.user_id else None,
                actor_name=actor.name,
            )
        )
        session.add(family)
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        raise FamilyArchiveError(
            "保存できませんでした。入力内容を確認して、もう一度保存してください。", 503
        ) from exc
    except Exception:
        session.rollback()
        raise
    finally:
        session.info.pop("family_archive_transition", None)
