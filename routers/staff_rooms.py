from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit
from database import get_session
from models import Classroom, Message, MessageAttachment
from time_utils import utc_now

router = APIRouter(prefix="/staff-rooms", tags=["staff_rooms"])
templates = Jinja2Templates(directory="templates")
MESSAGE_UPLOAD_ROOT = Path("storage") / "message_attachments"


@dataclass(slots=True)
class StoredAttachment:
    original_filename: str
    storage_path: str
    content_type: str | None
    file_size: int
    is_image: bool


def _all_rooms(session: Session) -> list[Classroom]:
    return session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()


def _default_room(session: Session) -> Classroom | None:
    return session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).first()


def _load_room(session: Session, room_id: int) -> Classroom:
    room = session.get(Classroom, room_id)
    if not room:
        raise HTTPException(status_code=404, detail="ルームが見つかりません。")
    return room


def _timeline_parent_messages(session: Session) -> list[Message]:
    return session.exec(
        select(Message)
        .options(selectinload(Message.attachments), selectinload(Message.room))
        .where(Message.parent_message_id.is_(None))
        .order_by(Message.created_at.desc(), Message.id.desc())
    ).all()


def _load_parent_message(session: Session, parent_message_id: int) -> Message:
    parent_message = session.exec(
        select(Message)
        .options(selectinload(Message.attachments), selectinload(Message.room))
        .where(Message.id == parent_message_id)
    ).first()
    if not parent_message or parent_message.parent_message_id is not None:
        raise HTTPException(status_code=404, detail="親メッセージが見つかりません。")
    return parent_message


def _load_reply_target(
    session: Session,
    *,
    parent_message: Message,
    reply_to_message_id: int | None,
) -> Message | None:
    if not reply_to_message_id:
        return None

    target_message = session.exec(
        select(Message)
        .options(selectinload(Message.attachments), selectinload(Message.room))
        .where(Message.id == reply_to_message_id)
    ).first()
    if not target_message:
        raise HTTPException(status_code=404, detail="返信先メッセージが見つかりません。")

    if target_message.room_id != parent_message.room_id:
        raise HTTPException(status_code=400, detail="返信先メッセージが別ルームに属しています。")

    target_parent_id = target_message.parent_message_id or target_message.id
    if target_parent_id != parent_message.id:
        raise HTTPException(status_code=400, detail="返信先メッセージが別スレッドに属しています。")
    return target_message


def _thread_replies(session: Session, parent_message_id: int) -> list[Message]:
    return session.exec(
        select(Message)
        .options(selectinload(Message.attachments), selectinload(Message.room))
        .where(Message.parent_message_id == parent_message_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).all()


def _reply_counts(session: Session) -> dict[int, int]:
    rows = session.exec(
        select(Message.parent_message_id, func.count(Message.id))
        .where(Message.parent_message_id.is_not(None))
        .group_by(Message.parent_message_id)
    ).all()
    return {parent_id: reply_count for parent_id, reply_count in rows if parent_id is not None}


def _author_name(current_user) -> str:
    name = (getattr(current_user, "name", "") or "").strip()
    if name:
        return name
    role_label = (getattr(current_user, "role_label", "") or "").strip()
    if role_label:
        return role_label
    return "スタッフ"


def _safe_filename(filename: str) -> str:
    base_name = Path(filename or "attachment").name.strip() or "attachment"
    sanitized = "".join(character if character.isalnum() or character in "._-" else "_" for character in base_name)
    return sanitized[:120] or "attachment"


def _store_attachments(uploaded_files: list[UploadFile]) -> list[StoredAttachment]:
    MESSAGE_UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    stored_attachments: list[StoredAttachment] = []
    created_paths: list[Path] = []

    try:
        for uploaded_file in uploaded_files:
            original_filename = (uploaded_file.filename or "").strip()
            if not original_filename:
                continue

            content = uploaded_file.file.read()
            if not content:
                continue

            safe_filename = _safe_filename(original_filename)
            storage_name = f"{uuid4().hex}{Path(safe_filename).suffix}"
            absolute_path = MESSAGE_UPLOAD_ROOT / storage_name
            absolute_path.write_bytes(content)
            created_paths.append(absolute_path)

            stored_attachments.append(
                StoredAttachment(
                    original_filename=safe_filename,
                    storage_path=storage_name,
                    content_type=uploaded_file.content_type,
                    file_size=len(content),
                    is_image=(uploaded_file.content_type or "").startswith("image/"),
                )
            )
    except Exception:
        for created_path in created_paths:
            created_path.unlink(missing_ok=True)
        raise

    return stored_attachments


def _create_message(
    session: Session,
    *,
    room_id: int,
    author_name: str,
    body: str,
    parent_message_id: int | None,
    uploaded_files: list[UploadFile],
) -> Message:
    normalized_body = (body or "").strip()
    stored_attachments = _store_attachments(uploaded_files)
    if not normalized_body and not stored_attachments:
        raise ValueError("本文または添付ファイルを入力してください。")

    try:
        message = Message(
            room_id=room_id,
            parent_message_id=parent_message_id,
            author_name=author_name,
            body=normalized_body,
            created_at=utc_now(),
            updated_at=utc_now(),
        )
        session.add(message)
        session.flush()

        for stored_attachment in stored_attachments:
            session.add(
                MessageAttachment(
                    message_id=message.id,
                    original_filename=stored_attachment.original_filename,
                    storage_path=stored_attachment.storage_path,
                    content_type=stored_attachment.content_type,
                    file_size=stored_attachment.file_size,
                    is_image=stored_attachment.is_image,
                )
            )

        session.commit()
        session.refresh(message)
    except Exception:
        session.rollback()
        for stored_attachment in stored_attachments:
            (MESSAGE_UPLOAD_ROOT / stored_attachment.storage_path).unlink(missing_ok=True)
        raise

    return session.exec(
        select(Message)
        .options(selectinload(Message.attachments), selectinload(Message.room))
        .where(Message.id == message.id)
    ).first()


def _render_timeline_page(
    request: Request,
    *,
    session: Session,
    current_user,
    form_error: str = "",
    form_body: str = "",
):
    default_room = _default_room(session)

    return templates.TemplateResponse(
        request,
        "staff_rooms/list.html",
        {
            "request": request,
            "messages": _timeline_parent_messages(session),
            "reply_counts": _reply_counts(session),
            "current_user": current_user,
            "form_error": form_error,
            "form_body": form_body,
            "can_post_messages": default_room is not None,
        },
    )


def _render_thread_panel(
    request: Request,
    *,
    session: Session,
    parent_message: Message,
    current_user,
    reply_to_message: Message | None = None,
    form_error: str = "",
    form_body: str = "",
):
    replies = _thread_replies(session, parent_message.id)
    return templates.TemplateResponse(
        request,
        "staff_rooms/_thread_panel.html",
        {
            "request": request,
            "parent_message": parent_message,
            "replies": replies,
            "reply_count": len(replies),
            "reply_to_message": reply_to_message,
            "current_user": current_user,
            "form_error": form_error,
            "form_body": form_body,
            "oob_reply_count": True,
        },
    )


def _render_message_list(request: Request, *, session: Session):
    return templates.TemplateResponse(
        request,
        "staff_rooms/_message_list.html",
        {
            "request": request,
            "messages": _timeline_parent_messages(session),
            "reply_counts": _reply_counts(session),
        },
    )


@router.get("/", response_class=HTMLResponse)
def timeline(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    return _render_timeline_page(
        request,
        session=session,
        current_user=current_user,
    )


@router.get("/partials/timeline", response_class=HTMLResponse)
def timeline_partial(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    _ = current_user
    return _render_message_list(request, session=session)


@router.post("/messages")
def create_parent_message(
    request: Request,
    body: str = Form(""),
    attachments: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    default_room = _default_room(session)
    if not default_room:
        raise HTTPException(status_code=404, detail="投稿先ルームが見つかりません。")

    try:
        _create_message(
            session,
            room_id=default_room.id,
            author_name=_author_name(current_user),
            body=body,
            parent_message_id=None,
            uploaded_files=attachments,
        )
    except ValueError as exc:
        return _render_timeline_page(
            request,
            session=session,
            current_user=current_user,
            form_error=str(exc),
            form_body=body,
        )

    return RedirectResponse(url="/staff-rooms/", status_code=303)


@router.get("/threads/{parent_message_id}", response_class=HTMLResponse)
def thread_detail(
    request: Request,
    parent_message_id: int,
    reply_to_message_id: int | None = None,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    parent_message = _load_parent_message(session, parent_message_id)
    reply_to_message = _load_reply_target(
        session,
        parent_message=parent_message,
        reply_to_message_id=reply_to_message_id,
    )
    return _render_thread_panel(
        request,
        session=session,
        parent_message=parent_message,
        current_user=current_user,
        reply_to_message=reply_to_message,
    )


@router.post("/threads/{parent_message_id}/replies")
def create_thread_reply(
    request: Request,
    parent_message_id: int,
    body: str = Form(""),
    reply_to_message_id: int | None = Form(default=None),
    attachments: list[UploadFile] = File(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    parent_message = _load_parent_message(session, parent_message_id)
    reply_to_message = _load_reply_target(
        session,
        parent_message=parent_message,
        reply_to_message_id=reply_to_message_id,
    )

    try:
        _create_message(
            session,
            room_id=parent_message.room_id,
            author_name=_author_name(current_user),
            body=body,
            parent_message_id=parent_message.id,
            uploaded_files=attachments,
        )
    except ValueError as exc:
        return _render_thread_panel(
            request,
            session=session,
            parent_message=parent_message,
            current_user=current_user,
            reply_to_message=reply_to_message,
            form_error=str(exc),
            form_body=body,
        )

    refreshed_parent_message = _load_parent_message(session, parent_message.id)
    return _render_thread_panel(
        request,
        session=session,
        parent_message=refreshed_parent_message,
        current_user=current_user,
    )


@router.get("/attachments/{attachment_id}")
def download_attachment(
    attachment_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    _ = current_user
    attachment = session.get(MessageAttachment, attachment_id)
    if not attachment:
        raise HTTPException(status_code=404, detail="添付ファイルが見つかりません。")

    absolute_path = MESSAGE_UPLOAD_ROOT / attachment.storage_path
    if not absolute_path.exists():
        raise HTTPException(status_code=404, detail="添付ファイルの保存先が見つかりません。")

    return FileResponse(
        absolute_path,
        media_type=attachment.content_type or "application/octet-stream",
        filename=attachment.original_filename,
        content_disposition_type="inline" if attachment.is_image else "attachment",
    )


@router.get("/{room_id}", response_class=HTMLResponse)
def legacy_room_redirect(
    room_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    _ = current_user
    _load_room(session, room_id)
    return RedirectResponse(url="/staff-rooms/", status_code=303)
