"""Separate reflection drafts and immutable review snapshots; never change plan approval."""
from types import SimpleNamespace
from uuid import UUID

from fastapi import HTTPException
from sqlmodel import select

from models import User
from time_utils import utc_now
from ..contracts import DocumentType, DocumentStatus
from ..db_models import PlanReflectionDraftRow as Draft, PlanReflectionReviewRow as Review
from ..db_models import PlanReflectionNotificationRow as Notification, PlanDailyReflectionRow
from .daily_reflections import reflection_for_document

LABELS = {"draft": "下書き", "pending": "承認待ち", "approved": "承認済み",
          "returned": "差戻し", "withdrawn": "取下げ"}


def begin(session):
    conn = session.connection()
    if conn.dialect.name == "sqlite" and not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql("BEGIN IMMEDIATE")


def layout(document):
    if document.document_type == DocumentType.DAILY_PLAN:
        return ["その日の振り返り"], ["振り返り"]
    return annual_layout(document.annual_sheet["age"])


def annual_layout(age):
    months = ["4月〜5月", "6月〜8月", "9月〜12月", "1月〜3月"] if age < 2 else ["4月〜6月", "7月〜9月", "10月〜12月", "1月〜3月"]
    if age == 5:
        months[2] = "月〜月"  # Retain the supplied form's unspecified months.
    return [f"{roman}期（{month}）" for roman, month in zip("ⅠⅡⅢⅣ", months)], ["生活", "遊び"] if age < 3 else ["基本的事項", "五領域"]


def validate_period(document, period):
    valid = (document.document_type == DocumentType.DAILY_PLAN and period == -1) or (
        document.document_type == DocumentType.ANNUAL_PLAN and document.annual_sheet and period in range(4))
    if not valid:
        raise HTTPException(404, "反省欄が見つかりません")


def draft_for(session, document_id, period):
    return session.exec(select(Draft).where(Draft.document_id == document_id, Draft.period == period).with_for_update()).first()


def latest_review(session, draft):
    return session.exec(select(Review).where(Review.draft_id == draft.id).order_by(Review.id.desc())).first() if draft else None


def state(session, document, period):
    validate_period(document, period)
    draft = draft_for(session, document.id, period)
    review = latest_review(session, draft)
    columns = layout(document)[1]
    legacy = reflection_for_document(session, document.id) if period == -1 else None
    return {"values": list(draft.values) if draft else [legacy.body] if legacy else [""] * len(columns),
            "version": draft.version if draft else 0, "status": draft.status if draft else "draft",
            "label": LABELS[draft.status] if draft else "下書き", "review_id": review.id if review else None,
            "updated_at": draft.updated_at.isoformat() if draft else None,
            "locked": bool(draft and draft.status in ("pending", "approved"))}


def sync_daily(session, draft, actor_ref):
    if draft.period != -1:
        return
    row = reflection_for_document(session, draft.document_id)
    if row is None:
        row = PlanDailyReflectionRow(document_id=draft.document_id, updated_by=actor_ref)
    row.body, row.updated_by, row.updated_at = draft.values[0], actor_ref, utc_now()
    submitted = draft.status in ("pending", "approved")
    row.status = "submitted" if submitted else "draft"
    row.submitted_by = (row.submitted_by or actor_ref) if submitted else None
    row.submitted_at = (row.submitted_at or row.updated_at) if submitted else None
    session.add(row)


def save_draft(session, document, period, values, version, actor_ref):
    validate_period(document, period)
    if document.status == DocumentStatus.ARCHIVED:
        raise HTTPException(409, "保管済みの文書は編集できません")
    if len(values) != len(layout(document)[1]) or any(not isinstance(v, str) or len(v) > 20000 for v in values):
        raise HTTPException(422, "反省の入力内容を確認してください")
    row = draft_for(session, document.id, period)
    if (row.version if row else 0) != version:
        raise HTTPException(409, "他の保存と競合しました。入力を保持したまま、別画面で最新版を確認してください")
    if row and row.status in ("pending", "approved"):
        if row.values == values:
            return row
        raise HTTPException(409, "承認依頼中・承認済みの反省は、取下げまたは修正操作をしてから編集してください")
    if row is None:
        row = Draft(document_id=document.id, period=period, values=list(values), updated_by=actor_ref)
    elif row.values != values:
        row.values, row.version = list(values), row.version + 1
    row.updated_by, row.updated_at = actor_ref, utc_now()
    session.add(row)
    session.flush()
    sync_daily(session, row, actor_ref)
    return row


def snapshot(document, period, values):
    periods, columns = layout(document)
    name = "日案の振り返り" if period == -1 else "年間指導計画反省"
    scope = document.target_date if period == -1 else f"{document.school_year}年度・{periods[period]}"
    return {"title": f"{name}（{document.classroom_ref}・{scope}）", "classroom": document.classroom_ref,
            "owner": document.owner_name, "columns": columns, "values": list(values), "period": period}


def request_review(session, document, period, version, user):
    row = draft_for(session, document.id, period)
    last = latest_review(session, row)
    if last and row.status == "pending" and last.status == "pending" and last.draft_version == version:
        return last  # Double-click/retry of the same confirmed version.
    if not row or row.version != version or row.status in ("pending", "approved"):
        raise HTTPException(409, "反省が更新されました。確認画面を開き直してください")
    if not any(value.strip() for value in row.values):
        raise HTTPException(422, "承認を依頼する反省を入力してください")
    review = Review(draft_id=row.id, document_id=document.id, nursery_ref=document.nursery_ref,
                    draft_version=version, snapshot=snapshot(document, period, row.values),
                    requested_by=user.actor_ref, requested_by_name=user.name)
    session.add(review)
    session.flush()
    row.status, row.version = "pending", row.version + 1
    session.add(row)
    sync_daily(session, row, user.actor_ref)
    for admin in session.exec(select(User).where(User.is_active.is_(True), User.staff_role == "admin")).all():
        session.add(Notification(review_id=review.id, recipient_user_id=admin.id))
    session.flush()
    return review


def transition(session, review, action, user, comment=""):
    row = session.get(Draft, review.draft_id)
    last = latest_review(session, row)
    if last.id != review.id:
        raise HTTPException(409, "新しい承認依頼があります。最新版を開いてください")
    if action in ("approve", "return"):
        if not user.is_admin:
            raise HTTPException(403, "管理者権限が必要です")
        if action == "return" and not comment.strip():
            raise HTTPException(422, "差戻し理由を入力してください")
    elif action == "withdraw":
        if not user.is_admin and review.requested_by != user.actor_ref:
            raise HTTPException(403, "依頼した職員または管理者が取り下げてください")
    elif action != "revise":
        raise HTTPException(422, "操作を確認してください")
    if action == "revise":
        if row.status != "approved" or review.status != "approved":
            raise HTTPException(409, "この反省は修正を開始できません")
        row.status = "draft"  # Keep the earlier approval and its snapshot unchanged.
    else:
        if row.status != "pending" or review.status != "pending":
            raise HTTPException(409, "この依頼は既に処理されています")
        review.status = {"approve": "approved", "return": "returned", "withdraw": "withdrawn"}[action]
        review.decided_by, review.decided_by_name = user.actor_ref, user.name
        review.decision_comment, review.decided_at = comment.strip(), utc_now()
        row.status = review.status
        session.add(review)
        for notification in session.exec(select(Notification).where(Notification.review_id == review.id, Notification.resolved_at.is_(None))).all():
            notification.resolved_at = utc_now()
            session.add(notification)
        if action in ("approve", "return"):
            try:
                recipient = session.get(User, UUID(review.requested_by.removeprefix("staff:")))
            except ValueError:
                recipient = None
            if recipient and recipient.is_active:
                session.add(Notification(review_id=review.id, recipient_user_id=recipient.id, kind="review_outcome"))
    row.version, row.updated_by, row.updated_at = row.version + 1, user.actor_ref, utc_now()
    session.add(row)
    sync_daily(session, row, user.actor_ref)


def input_url(document_id, period):
    return f"/plans/documents/{document_id}#daily-reflection-heading" if period == -1 else f"/plans/annual-library?document_id={document_id}#annual-reflection-editor"


def portal_items(session, user_id, nursery_ref, admin=False):
    queue = []
    if admin:
        for review in session.exec(select(Review).where(Review.nursery_ref == nursery_ref, Review.status == "pending")).all():
            queue.append({"kind": "reflection", "kind_label": "反省の承認", "title": review.snapshot["title"],
                          "requester_name": review.requested_by_name, "requested_at": review.created_at,
                          "url": f"/plans/reflection-reviews/{review.id}"})
    notifications = []
    rows = session.exec(select(Notification, Review).join(Review, Review.id == Notification.review_id).where(
        Notification.recipient_user_id == user_id, Notification.resolved_at.is_(None), Review.nursery_ref == nursery_ref)).all()
    for n, r in rows:
        if n.kind == "review_request" and not admin:
            continue
        notifications.append(SimpleNamespace(id=n.id, document_title=r.snapshot["title"],
            notification_kind=n.kind, decision_status="rejected" if r.status == "returned" else r.status,
            decided_by_name=r.decided_by_name, decision_comment=r.decision_comment, requested_by_name=r.requested_by_name,
            created_at=n.created_at, read_at=n.read_at, open_url=f"/plans/reflection-notifications/{n.id}/open",
            dismiss_url=f"/plans/reflection-notifications/{n.id}/dismiss"))
    return queue, notifications
