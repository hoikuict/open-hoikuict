from __future__ import annotations

from collections.abc import Iterable

from sqlmodel import Session, select

from models import User

from ..contracts import DocumentStatus
from ..db_models import PlanDocumentAction, PlanDocumentHeadRow, PlanRevisionRow
from ..models import PlanDocument
from ..serializers import document_to_dict
from .review_notifications import user_id_from_actor_ref


def reopened_daily_ids(session: Session, document_ids: Iterable[int]) -> set[int]:
    ids = list(document_ids)
    if not ids:
        return set()
    return set(session.exec(
        select(PlanDocumentAction.document_id).where(
            PlanDocumentAction.document_id.in_(ids),
            PlanDocumentAction.action == "reopened",
        ).distinct()
    ).all())


def _fields(snapshot: dict) -> dict[tuple, dict]:
    fields = {}

    def add(key, label, value):
        fields[key] = {"label": label, "value": value or ""}

    add(("title",), "タイトル", snapshot.get("title"))
    add(("owner_name",), "作成者", snapshot.get("owner_name"))
    add(("confirmation_items",), "確認が必要な入力", "\n".join(snapshot.get("confirmation_items") or []))
    for section in snapshot.get("sections") or []:
        key = section["section_key"]
        if key == "daily_reflection_viewpoint":
            continue
        title = section.get("title") or key
        add(("body", key), title, section.get("body"))
        add(("editor_note", key), title + "の編集メモ", section.get("editor_note"))
        add(("needs_confirmation", key), title + "の確認", "要確認" if section.get("needs_confirmation") else "確認不要")
    schedule = snapshot.get("schedule") or {}
    for i, row in enumerate(sorted(schedule.get("rows") or [], key=lambda r: r.get("order", 0)), start=1):
        key = row["row_key"]
        row_label = f"{i}行目"
        add(("time", key), row_label + "・時間", row.get("start_time"))
        add(("label", key), row_label + "・活動名", row.get("label"))
        for column in schedule.get("columns") or []:
            cell = (row.get("cells") or {}).get(column["key"]) or {}
            add(("cell", key, column["key"]), row_label + "・" + column["title"], cell.get("body"))
    return fields


def _changes(before: dict, after: dict) -> list[dict]:
    changes = []
    for key in dict.fromkeys((*after, *before)):
        field = after.get(key) or before[key]
        old = before[key]["value"] if key in before else ""
        new = after[key]["value"] if key in after else ""
        if old != new:
            changes.append({"label": field["label"], "before": old, "after": new})
    return changes


def review_context(session: Session, document: PlanDocument) -> dict:
    actions = session.exec(select(PlanDocumentAction).where(
        PlanDocumentAction.document_id == document.id
    ).order_by(PlanDocumentAction.id)).all()
    missing_names = {a.actor_ref: user_id_from_actor_ref(a.actor_ref) for a in actions if not a.actor_name}
    user_ids = {uid for uid in missing_names.values() if uid is not None}
    names = dict(session.exec(select(User.id, User.display_name).where(User.id.in_(user_ids))).all()) if user_ids else {}

    def actor(action):
        return action.actor_name or names.get(missing_names.get(action.actor_ref)) or "記録なし"

    head = session.exec(select(PlanDocumentHeadRow).where(
        PlanDocumentHeadRow.document_id == document.id
    )).first()
    approved_id = head.approved_revision_id if head else None
    revision_ids = {a.revision_id for a in actions if a.revision_id}
    if approved_id:
        revision_ids.add(approved_id)
    versions = {
        v.id: _fields(v.snapshot) for v in session.exec(select(PlanRevisionRow).where(
            PlanRevisionRow.document_id == document.id, PlanRevisionRow.id.in_(revision_ids)
        )).all()
    }
    history = []
    reopened = False
    correction = None
    previous_approval = None
    labels = {
        "approved": "承認", "in_review": "レビュー依頼", "rejected": "差戻し",
        "draft": "レビュー依頼の取下げ", "reopened": "承認取消・修正依頼",
        "repair_saved": "修正保存", "archived": "アーカイブ",
    }
    for action in actions:
        label = labels.get(action.action, action.action)
        if reopened:
            label = {"approved": "再承認", "in_review": "再承認依頼", "draft": "再承認依頼の取下げ"}.get(action.action, label)
        if action.action == "reopened":
            # Older installations may have an approved version without decision metadata.
            if previous_approval is None and action.revision_id in versions:
                history.append(_legacy_approval(versions[action.revision_id]))
            reopened = True
            correction = action
        if action.action == "rejected" and reopened:
            correction = action
        entry = {"label": label, "actor": actor(action), "at": action.created_at,
                 "comment": action.comment, "fields": list(versions.get(action.revision_id, {}).values())}
        history.append(entry)
        if action.action == "approved":
            previous_approval = entry
    approval_fields = versions.get(approved_id)
    if approval_fields is None and document.status == DocumentStatus.APPROVED:
        approval_fields = _fields(document_to_dict(document))
    if approval_fields is not None:
        if previous_approval is None and not reopened:
            history.append(_legacy_approval(approval_fields))
        elif previous_approval is not None and not previous_approval["fields"]:
            previous_approval["fields"] = list(approval_fields.values())
    phase = document.daily_revision_phase
    changes = []
    if phase in {"editing", "pending"} and approval_fields is not None:
        changes = _changes(approval_fields, _fields(document_to_dict(document)))
    return {
        "phase": phase, "status_label": document.status_label, "history": history, "changes": changes,
        "reopen_reason": correction.comment if correction else None,
        "reopen_actor": actor(correction) if correction else None,
        "reopen_at": correction.created_at if correction else None,
    }


def _legacy_approval(fields: dict) -> dict:
    return {"label": "承認済みの保存内容", "actor": "記録なし", "at": None, "comment": None,
            "fields": list(fields.values())}
