from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from time_utils import ensure_utc_from_local, local_naive_now, parse_local_datetime_input

from ..auth_adapter import CurrentUser, StaffUser, require_admin, require_can_edit, require_classroom_access
from ..contracts import DocumentStatus, DocumentType, normalize_status
from ..serializers import document_to_dict
from ..store import (
    ConcurrentUpdateError,
    DocumentRepositoryDep,
    ExecutionChangeError,
    InvalidStatusTransitionError,
    SqlModelDocumentRepository,
)
from ..templating import render_template


router = APIRouter(tags=["documents"])

REASON_LABELS = {
    "weather": "天候",
    "child_state": "子どもの様子",
    "safety": "安全",
    "staffing": "職員体制",
    "facility": "施設・設備",
    "other": "その他",
}

IMPACT_LABELS = {
    "minor": "軽微（記録のみ）",
    "significant": "重要（事後確認）",
    "critical": "重大（即時共有・事後確認）",
}


class ExecutionChangePayload(BaseModel):
    affected_block_key: str | None = None
    reason_code: str
    reason_note: str | None = None
    impact_level: str
    changed_at: datetime
    after_heading: str
    after_time_label: str = ""
    after_details: str


class ExecutionChangeConfirmationPayload(BaseModel):
    comment: str | None = None


class ExecutionChangeCorrectionPayload(BaseModel):
    changed_at: datetime
    correction_note: str
    after_heading: str
    after_time_label: str = ""
    after_details: str


def _visible_document(
    document_id: int,
    user: StaffUser,
    repository: SqlModelDocumentRepository,
):
    document = repository.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    if document.nursery_ref != user.nursery_ref:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    try:
        require_classroom_access(user, document.classroom_ref)
    except HTTPException as exc:
        raise HTTPException(status_code=404, detail="文書が見つかりません") from exc
    return document


def _visible_document_reference(
    document_ref: str,
    user: StaffUser,
    repository: SqlModelDocumentRepository,
):
    document = (
        repository.get(int(document_ref))
        if document_ref.isdigit()
        else repository.get_by_public_id(document_ref)
    )
    if document is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    return _visible_document(document.id, user, repository)


def _lock_version(raw_value: str | int | None) -> int:
    try:
        value = int(raw_value or 0)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="画面を再読み込みしてください") from exc
    if value < 1:
        raise HTTPException(status_code=409, detail="画面を再読み込みしてください")
    return value


def _raise_repository_error(exc: Exception) -> None:
    if isinstance(exc, ConcurrentUpdateError):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if isinstance(exc, (InvalidStatusTransitionError, ExecutionChangeError)):
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    raise exc


def _change_to_dict(change) -> dict[str, object]:
    return {
        "id": change.id,
        "document_id": change.document_id,
        "base_revision_id": change.base_revision_id,
        "approval_state_at_change": change.approval_state_at_change,
        "affected_block_key": change.affected_block_key,
        "reason_code": change.reason_code,
        "reason_label": REASON_LABELS.get(change.reason_code, change.reason_code),
        "reason_note": change.reason_note,
        "impact_level": change.impact_level,
        "impact_label": IMPACT_LABELS.get(change.impact_level, change.impact_level),
        "before_snapshot": change.before_snapshot,
        "after_snapshot": change.after_snapshot,
        "changed_at": change.changed_at.isoformat(),
        "recorded_by": change.recorded_by,
        "recorded_at": change.recorded_at.isoformat(),
        "confirmation_status": change.confirmation_status,
        "confirmed_by": change.confirmed_by,
        "confirmed_at": change.confirmed_at.isoformat() if change.confirmed_at else None,
        "confirmation_comment": change.confirmation_comment,
        "corrects_change_id": change.corrects_change_id,
    }


@router.get("/documents/")
def list_documents(request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = repository.list(nursery_ref=user.nursery_ref, classroom_refs=classroom_refs)
    return render_template(
        request,
        "documents/list.html",
        user=user,
        documents=documents,
    )


@router.get("/documents/{document_id}")
def document_detail(
    document_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document(document_id, user, repository)
    head = repository.head(document_id)
    return render_template(
        request,
        "documents/detail.html",
        user=user,
        document=document,
        status_options=list(DocumentStatus),
        lock_version=head.lock_version if head else 0,
        revisions=repository.revisions(document_id),
        execution_changes=repository.list_execution_changes(document_id),
        reason_labels=REASON_LABELS,
        impact_labels=IMPACT_LABELS,
        changed_at_default=local_naive_now().strftime("%Y-%m-%dT%H:%M"),
    )


@router.get("/documents/{document_id}/edit")
def edit_document_form(
    document_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document(document_id, user, repository)
    require_can_edit(user, request)
    if not document.can_edit_body:
        raise HTTPException(status_code=409, detail="この状態の文書は修正できません")
    return render_template(
        request,
        "documents/edit.html",
        user=user,
        document=document,
        lock_version=repository.lock_version(document_id),
        confirmation_items_text="\n".join(document.confirmation_items),
    )


@router.post("/documents/{document_id}")
async def update_document(
    document_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document(document_id, user, repository)
    require_can_edit(user, request)
    if not document.can_edit_body:
        raise HTTPException(status_code=409, detail="この状態の文書は修正できません")

    form = await request.form()
    form_values = {str(key): str(value) for key, value in form.multi_items()}
    title = str(form.get("title") or document.title).strip() or document.title
    owner_name = str(form.get("owner_name") or document.owner_name).strip() or document.owner_name
    if "confirmation_items" in form:
        confirmation_items = [
            item.strip()
            for item in str(form.get("confirmation_items") or "").splitlines()
            if item.strip()
        ]
    else:
        confirmation_items = document.confirmation_items
    section_updates: dict[str, dict[str, object]] = {}
    for section in document.sections:
        body_field = f"body_{section.section_key}"
        editor_note_field = f"editor_note_{section.section_key}"
        confirmed = form.get(f"confirmed_{section.section_key}") == "yes"
        section_updates[section.section_key] = {
            "body": str(form.get(body_field) if body_field in form else section.body).strip(),
            "editor_note": str(
                form.get(editor_note_field) if editor_note_field in form else section.editor_note or ""
            ).strip(),
            "needs_confirmation": section.needs_confirmation and not confirmed,
        }

    try:
        updated = repository.update_document(
            document.id,
            title=title,
            owner_name=owner_name,
            confirmation_items=confirmation_items,
            section_updates=section_updates,
            schedule_form=form_values,
            expected_lock_version=_lock_version(form.get("lock_version")),
            actor_ref=user.actor_ref or "unknown",
        )
    except (ConcurrentUpdateError, InvalidStatusTransitionError) as exc:
        _raise_repository_error(exc)
    if updated is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/status")
def update_document_status(
    document_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    status: Annotated[str, Form()],
    lock_version: Annotated[str, Form()],
    comment: Annotated[str, Form()] = "",
):
    document = _visible_document(document_id, user, repository)
    target_status = normalize_status(status)
    if target_status in {DocumentStatus.APPROVED, DocumentStatus.REJECTED, DocumentStatus.ARCHIVED}:
        require_admin(user, request)
    else:
        require_can_edit(user, request)
    try:
        updated = repository.update_status(
            document.id,
            target_status,
            expected_lock_version=_lock_version(lock_version),
            actor_ref=user.actor_ref or "unknown",
            actor_name=user.name,
            comment=comment,
        )
    except (ConcurrentUpdateError, InvalidStatusTransitionError) as exc:
        _raise_repository_error(exc)
    if updated is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/execution-changes")
def create_execution_change(
    document_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    affected_block_key: Annotated[str, Form()] = "",
    reason_code: Annotated[str, Form()] = "weather",
    reason_note: Annotated[str, Form()] = "",
    impact_level: Annotated[str, Form()] = "minor",
    changed_at: Annotated[str, Form()] = "",
    after_heading: Annotated[str, Form()] = "",
    after_time_label: Annotated[str, Form()] = "",
    after_details: Annotated[str, Form()] = "",
):
    document = _visible_document(document_id, user, repository)
    require_can_edit(user, request)
    if document.document_type != DocumentType.DAILY_PLAN:
        raise HTTPException(status_code=409, detail="日案だけ実施変更を登録できます")
    parsed_changed_at = ensure_utc_from_local(parse_local_datetime_input(changed_at) or local_naive_now())
    try:
        repository.create_execution_change(
            document_id,
            affected_block_key=affected_block_key.strip() or None,
            reason_code=reason_code,
            reason_note=reason_note,
            impact_level=impact_level,
            after_snapshot={
                "heading": after_heading.strip(),
                "time_label": after_time_label.strip(),
                "details": after_details.strip(),
            },
            changed_at=parsed_changed_at,
            actor_ref=user.actor_ref or "unknown",
        )
    except ExecutionChangeError as exc:
        _raise_repository_error(exc)
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/execution-changes/{change_id}/confirm")
def confirm_execution_change(
    document_id: int,
    change_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    confirmation_comment: Annotated[str, Form()] = "",
):
    _visible_document(document_id, user, repository)
    require_admin(user, request)
    try:
        repository.confirm_execution_change(
            document_id,
            change_id,
            actor_ref=user.actor_ref or "unknown",
            comment=confirmation_comment,
        )
    except ExecutionChangeError as exc:
        _raise_repository_error(exc)
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/execution-changes/{change_id}/corrections")
def correct_execution_change(
    document_id: int,
    change_id: int,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    changed_at: Annotated[str, Form()] = "",
    after_heading: Annotated[str, Form()] = "",
    after_time_label: Annotated[str, Form()] = "",
    after_details: Annotated[str, Form()] = "",
    correction_note: Annotated[str, Form()] = "",
):
    _visible_document(document_id, user, repository)
    require_can_edit(user, request)
    original = next(
        (
            item
            for item in repository.list_execution_changes(document_id)
            if item.id == change_id
        ),
        None,
    )
    if original is None:
        raise HTTPException(status_code=404, detail="実施変更が見つかりません")
    if not correction_note.strip():
        raise HTTPException(status_code=422, detail="訂正理由を入力してください")
    parsed_changed_at = ensure_utc_from_local(parse_local_datetime_input(changed_at) or local_naive_now())
    try:
        repository.create_execution_change(
            document_id,
            affected_block_key=original.affected_block_key,
            reason_code=original.reason_code,
            reason_note=f"訂正: {correction_note.strip()}",
            impact_level=original.impact_level,
            after_snapshot={
                "heading": after_heading.strip(),
                "time_label": after_time_label.strip(),
                "details": after_details.strip(),
            },
            changed_at=parsed_changed_at,
            actor_ref=user.actor_ref or "unknown",
            corrects_change_id=change_id,
        )
    except ExecutionChangeError as exc:
        _raise_repository_error(exc)
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.get("/api/documents/{document_id}")
def document_json(
    document_id: int,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document(document_id, user, repository)
    payload = document_to_dict(document)
    head = repository.head(document_id)
    if head is not None:
        payload["public_id"] = head.public_id
        payload["lock_version"] = head.lock_version
        payload["current_revision_id"] = head.current_revision_id
        payload["review_revision_id"] = head.review_revision_id
        payload["approved_revision_id"] = head.approved_revision_id
    return payload


@router.get("/api/daily/{document_ref}/execution-changes")
def execution_changes_json(
    document_ref: str,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document_reference(document_ref, user, repository)
    if document.document_type != DocumentType.DAILY_PLAN:
        raise HTTPException(status_code=404, detail="日案が見つかりません")
    return {
        "items": [
            _change_to_dict(item)
            for item in repository.list_execution_changes(document.id)
        ]
    }


@router.post("/api/daily/{document_ref}/execution-changes", status_code=201)
def create_execution_change_json(
    document_ref: str,
    payload: ExecutionChangePayload,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document_reference(document_ref, user, repository)
    require_can_edit(user, request)
    if document.document_type != DocumentType.DAILY_PLAN:
        raise HTTPException(status_code=404, detail="日案が見つかりません")
    try:
        change = repository.create_execution_change(
            document.id,
            affected_block_key=payload.affected_block_key,
            reason_code=payload.reason_code,
            reason_note=payload.reason_note,
            impact_level=payload.impact_level,
            after_snapshot={
                "heading": payload.after_heading.strip(),
                "time_label": payload.after_time_label.strip(),
                "details": payload.after_details.strip(),
            },
            changed_at=ensure_utc_from_local(payload.changed_at),
            actor_ref=user.actor_ref or "unknown",
        )
    except ExecutionChangeError as exc:
        _raise_repository_error(exc)
    return _change_to_dict(change)


@router.post("/api/daily/{document_ref}/execution-changes/{change_id}/confirm")
def confirm_execution_change_json(
    document_ref: str,
    change_id: int,
    payload: ExecutionChangeConfirmationPayload,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document_reference(document_ref, user, repository)
    require_admin(user, request)
    try:
        change = repository.confirm_execution_change(
            document.id,
            change_id,
            actor_ref=user.actor_ref or "unknown",
            comment=payload.comment,
        )
    except ExecutionChangeError as exc:
        _raise_repository_error(exc)
    return _change_to_dict(change)


@router.post("/api/daily/{document_ref}/execution-changes/{change_id}/corrections", status_code=201)
def correct_execution_change_json(
    document_ref: str,
    change_id: int,
    payload: ExecutionChangeCorrectionPayload,
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
):
    document = _visible_document_reference(document_ref, user, repository)
    require_can_edit(user, request)
    original = next(
        (
            item
            for item in repository.list_execution_changes(document.id)
            if item.id == change_id
        ),
        None,
    )
    if original is None:
        raise HTTPException(status_code=404, detail="実施変更が見つかりません")
    if not payload.correction_note.strip():
        raise HTTPException(status_code=422, detail="訂正理由を入力してください")
    try:
        change = repository.create_execution_change(
            document.id,
            affected_block_key=original.affected_block_key,
            reason_code=original.reason_code,
            reason_note=f"訂正: {payload.correction_note.strip()}",
            impact_level=original.impact_level,
            after_snapshot={
                "heading": payload.after_heading.strip(),
                "time_label": payload.after_time_label.strip(),
                "details": payload.after_details.strip(),
            },
            changed_at=ensure_utc_from_local(payload.changed_at),
            actor_ref=user.actor_ref or "unknown",
            corrects_change_id=change_id,
        )
    except ExecutionChangeError as exc:
        _raise_repository_error(exc)
    return _change_to_dict(change)
