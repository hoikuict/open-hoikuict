from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlalchemy import update
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit
from database import get_session
from models import DocumentReviewRequest
from template_utils import create_templates
from time_utils import utc_now

router = APIRouter(prefix="/document-reviews", tags=["document_reviews"])
templates = create_templates()
UPLOAD_ROOT = Path("storage/document_reviews")
ALLOWED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".doc",
    ".xlsx",
    ".xls",
    ".odt",
    ".txt",
    ".png",
    ".jpg",
    ".jpeg",
}


def _load(session, review_id, user):
    item = session.get(DocumentReviewRequest, review_id)
    if not item or not (
        user.is_admin
        or (user.user_id is not None and item.requested_by_user_id == user.user_id)
    ):
        raise HTTPException(404, "確認依頼が見つかりません。")
    return item


@router.get("/", response_class=HTMLResponse)
def review_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    stmt = select(DocumentReviewRequest).order_by(
        DocumentReviewRequest.created_at.desc()
    )
    if not current_user.is_admin:
        stmt = (
            stmt.where(
                DocumentReviewRequest.requested_by_user_id == current_user.user_id
            )
            if current_user.user_id
            else stmt.where(False)
        )
    return templates.TemplateResponse(
        request,
        "document_reviews/list.html",
        {
            "current_user": current_user,
            "items": session.exec(stmt).all(),
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.post("/", response_class=HTMLResponse)
def create_review(
    request: Request,
    title: str = Form(...),
    body: str = Form(""),
    attachments: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    if current_user.user_id is None:
        raise HTTPException(403, "職員を選択してから依頼してください。")
    if not title.strip() or len(title.strip()) > 200 or len(body) > 20000:
        raise HTTPException(
            400, "件名は200文字以内、本文は20000文字以内で入力してください。"
        )
    files = [f for f in attachments if f.filename]
    if len(files) > 5:
        raise HTTPException(400, "添付ファイルは5件までです。")
    stored, created = [], []
    total = 0
    try:
        for file in files:
            name = Path(file.filename.replace("\\", "/")).name
            suffix = Path(name).suffix.lower()
            if suffix not in ALLOWED_SUFFIXES:
                raise HTTPException(
                    400, "添付にはWord・PDF・Excel・画像・テキストを使用してください。"
                )
            content = file.file.read(10 * 1024 * 1024 + 1)
            total += len(content)
            if (
                not content
                or len(content) > 10 * 1024 * 1024
                or total > 20 * 1024 * 1024
            ):
                raise HTTPException(
                    400,
                    "添付は1件10MB、合計20MBまでです。空のファイルは添付できません。",
                )
            UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
            storage_name = uuid4().hex + suffix
            path = UPLOAD_ROOT / storage_name
            path.write_bytes(content)
            created.append(path)
            stored.append(
                {"name": name[:200], "path": storage_name, "size": len(content)}
            )
        item = DocumentReviewRequest(
            title=title.strip(),
            body=body.strip(),
            attachments=stored,
            requested_by_user_id=current_user.user_id,
            requested_by_name=current_user.name,
        )
        session.add(item)
        session.commit()
        session.refresh(item)
    except Exception:
        session.rollback()
        for path in created:
            path.unlink(missing_ok=True)
        raise
    return RedirectResponse(f"/document-reviews/{item.id}", status_code=303)


@router.get("/{review_id}", response_class=HTMLResponse)
def review_detail(
    request: Request,
    review_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    return templates.TemplateResponse(
        request,
        "document_reviews/detail.html",
        {
            "current_user": current_user,
            "item": _load(session, review_id, current_user),
        },
        headers={"Cache-Control": "private, no-store"},
    )


@router.get("/{review_id}/attachments/{index}")
def review_attachment(
    review_id: int,
    index: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    item = _load(session, review_id, current_user)
    if index < 0 or index >= len(item.attachments):
        raise HTTPException(404, "添付が見つかりません。")
    attachment = item.attachments[index]
    path = (UPLOAD_ROOT / attachment["path"]).resolve()
    if path.parent != UPLOAD_ROOT.resolve() or not path.is_file():
        raise HTTPException(404, "添付が見つかりません。")
    return FileResponse(
        path,
        filename=attachment["name"],
        media_type="application/octet-stream",
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


@router.post("/{review_id}/decision")
def review_decision(
    review_id: int,
    decision: str = Form(...),
    note: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    item = _load(session, review_id, current_user)
    if not current_user.is_admin:
        raise HTTPException(403, "管理者が確認結果を登録してください。")
    if (
        decision not in {"approved", "returned"}
        or len(note) > 5000
        or (decision == "returned" and not note.strip())
    ):
        raise HTTPException(
            400, "確認結果とコメントを入力してください。差戻し時はコメントが必要です。"
        )
    result = session.execute(
        update(DocumentReviewRequest)
        .where(
            DocumentReviewRequest.id == item.id,
            DocumentReviewRequest.status == "pending",
        )
        .values(
            status=decision,
            decision_note=note.strip(),
            decided_by_user_id=current_user.user_id,
            decided_by_name=current_user.name,
            decided_at=utc_now(),
        )
    )
    if result.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "この依頼は確認済みです。画面を開き直してください。")
    session.commit()
    return RedirectResponse(f"/document-reviews/{review_id}", status_code=303)
