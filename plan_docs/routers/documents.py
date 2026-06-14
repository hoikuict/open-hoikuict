from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from ..auth_adapter import CurrentUser, StaffUser, require_admin, require_can_edit, require_classroom_access
from ..contracts import DocumentStatus, normalize_status
from ..serializers import document_to_dict
from ..store import document_store
from ..templating import render_template


router = APIRouter(tags=["documents"])


def _visible_document(document_id: int, user: StaffUser):
    document = document_store.get(document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    if document.nursery_ref != user.nursery_ref:
        raise HTTPException(status_code=403, detail="この園の文書にアクセスできません")
    require_classroom_access(user, document.classroom_ref)
    return document


@router.get("/documents/")
def list_documents(request: Request, user: CurrentUser):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = document_store.list(nursery_ref=user.nursery_ref, classroom_refs=classroom_refs)
    return render_template(
        request,
        "documents/list.html",
        user=user,
        documents=documents,
    )


@router.get("/documents/{document_id}")
def document_detail(document_id: int, request: Request, user: CurrentUser):
    document = _visible_document(document_id, user)
    return render_template(
        request,
        "documents/detail.html",
        user=user,
        document=document,
        status_options=list(DocumentStatus),
    )


@router.get("/documents/{document_id}/edit")
def edit_document_form(document_id: int, request: Request, user: CurrentUser):
    document = _visible_document(document_id, user)
    require_can_edit(user, request)
    if not document.can_edit_body:
        raise HTTPException(status_code=409, detail="この状態の文書は修正できません")
    return render_template(
        request,
        "documents/edit.html",
        user=user,
        document=document,
        confirmation_items_text="\n".join(document.confirmation_items),
    )


@router.post("/documents/{document_id}")
async def update_document(document_id: int, request: Request, user: CurrentUser):
    document = _visible_document(document_id, user)
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

    updated = document_store.update_document(
        document.id,
        title=title,
        owner_name=owner_name,
        confirmation_items=confirmation_items,
        section_updates=section_updates,
        schedule_form=form_values,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.post("/documents/{document_id}/status")
def update_document_status(
    document_id: int,
    request: Request,
    user: CurrentUser,
    status: Annotated[str, Form()],
):
    document = _visible_document(document_id, user)
    target_status = normalize_status(status)
    if target_status in {DocumentStatus.APPROVED, DocumentStatus.REJECTED, DocumentStatus.ARCHIVED}:
        require_admin(user, request)
    else:
        require_can_edit(user, request)
    updated = document_store.update_status(document.id, target_status)
    if updated is None:
        raise HTTPException(status_code=404, detail="文書が見つかりません")
    return RedirectResponse(url=f"/plans/documents/{document_id}", status_code=303)


@router.get("/api/documents/{document_id}")
def document_json(document_id: int, user: CurrentUser):
    document = _visible_document(document_id, user)
    return document_to_dict(document)
