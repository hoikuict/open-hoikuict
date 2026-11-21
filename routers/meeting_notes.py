import base64
import asyncio
import binascii
import hashlib
import json
import logging
from collections import defaultdict
from typing import DefaultDict, Literal

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import or_, update, func
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit, resolve_staff_principal
from database import get_session
from institutional_record_service import (
    fiscal_year_for_datetime,
    highlights_for_source,
    list_event_series,
)
from models import HighlightSourceType, InstitutionalRecordOrigin, MeetingNote, MeetingNoteAction
from meeting_note_lifecycle import load_note, relations, LABELS, ACTION_LABELS, TRANSITIONS
from time_utils import utc_now
from security_config import websocket_origin_allowed

router = APIRouter(prefix="/meeting-notes", tags=["meeting_notes"])
from template_utils import create_templates

templates = create_templates()
logger = logging.getLogger(__name__)


class SaveMeetingNotePayload(BaseModel):
    title: str
    content_base64: str
    plain_text: str = ""
    base_revision: str | None = None
    editor_version: int = 1


def _note_content(note: MeetingNote) -> dict:
    content = base64.b64encode(note.content).decode("ascii") if note.content else None
    revision = hashlib.sha256(json.dumps(
        [note.title, content, note.search_text, note.updated_at.isoformat(), note.lifecycle_version], ensure_ascii=False,
    ).encode("utf-8")).hexdigest()
    return {"content_base64": content, "title": note.title, "revision": revision,
            "lifecycle_status": note.lifecycle_status, "lifecycle_version": note.lifecycle_version}


class ExportMeetingNotePayload(BaseModel):
    title: str = Field(max_length=300)
    ops: list[dict] = Field(max_length=10000)


@router.post("/{note_id}/export/{format_name}")
async def export_meeting_note(
    request: Request, note_id: int, format_name: str,
    session: Session = Depends(get_session), current_user=Depends(get_current_staff_user),
):
    from meeting_note_export import export_note

    load_note(session, note_id, current_user)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 24 * 1024 * 1024:
            raise HTTPException(413, "出力する内容は24MB以内にしてください。")
    try:
        payload = ExportMeetingNotePayload.model_validate_json(content)
        data, media_type, extension = export_note(payload.title.strip() or "無題の議事録", payload.ops, format_name)
    except (ValueError, ValidationError, TypeError) as exc:
        raise HTTPException(400, str(exc) if not isinstance(exc, ValidationError) else "出力内容を確認してください。") from exc
    return Response(data, media_type=media_type, headers={
        "Content-Disposition": f'attachment; filename="meeting-{note_id}.{extension}"',
        "Cache-Control": "no-store",
    })


class MeetingNoteConnectionManager:
    def __init__(self) -> None:
        self._connections: DefaultDict[int, list[WebSocket]] = defaultdict(list)

    async def connect(self, note_id: int, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections[note_id].append(websocket)

    def disconnect(self, note_id: int, websocket: WebSocket) -> None:
        connections = self._connections.get(note_id)
        if not connections:
            return
        if websocket in connections:
            connections.remove(websocket)
        if not connections and note_id in self._connections:
            del self._connections[note_id]

    async def broadcast(self, note_id: int, message: bytes, exclude: WebSocket | None = None) -> None:
        stale_connections: list[WebSocket] = []
        for connection in list(self._connections.get(note_id, [])):
            if connection is exclude:
                continue
            try:
                await connection.send_bytes(message)
            except Exception:
                stale_connections.append(connection)
        for connection in stale_connections:
            self.disconnect(note_id, connection)

    async def invalidate(self, note_id: int, note: MeetingNote) -> None:
        for connection in list(self._connections.get(note_id, [])):
            try:
                await connection.send_json({"type": "lifecycle", "lifecycle_status": note.lifecycle_status,
                                            "lifecycle_version": note.lifecycle_version})
                await connection.close(code=4009)
            except Exception:
                pass
            self.disconnect(note_id, connection)


manager = MeetingNoteConnectionManager()


def _display_name(current_user) -> str:
    name = getattr(current_user, "name", "") or ""
    if name.strip():
        return name.strip()
    role_label = getattr(current_user, "role_label", "") or ""
    if role_label.strip():
        return role_label.strip()
    return "スタッフ"


def _load_meeting_note(session: Session, note_id: int) -> MeetingNote:
    note = session.get(MeetingNote, note_id)
    if not note:
        raise HTTPException(status_code=404, detail="議事録が見つかりません")
    return note


@router.get("/", response_class=HTMLResponse)
def meeting_note_list(
    request: Request,
    q: str = Query(default="", max_length=100),
    state: Literal["active", "archived", "trashed"] = "active",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    current_query = q.strip()
    if state == "trashed" and not current_user.is_admin:
        raise HTTPException(403, "ごみ箱は管理者だけが利用できます")
    counts = {value: session.exec(select(func.count()).select_from(MeetingNote).where(MeetingNote.lifecycle_status == value)).one()
              for value in LABELS if value != "trashed" or current_user.is_admin}
    statement = select(MeetingNote).where(MeetingNote.lifecycle_status == state)
    if current_query:
        filters = [
            MeetingNote.title.contains(current_query, autoescape=True),
            MeetingNote.search_text.contains(current_query, autoescape=True),
            MeetingNote.created_by.contains(current_query, autoescape=True),
            MeetingNote.updated_by.contains(current_query, autoescape=True),
        ]
        if current_query.isdigit():
            filters.append(MeetingNote.id == int(current_query))
        statement = statement.where(or_(*filters))
    notes = session.exec(statement.order_by(MeetingNote.updated_at.desc(), MeetingNote.id.desc())).all()
    return templates.TemplateResponse(
        request,
        "meeting_notes/list.html",
        {
            "notes": notes,
            "current_user": current_user,
            "current_query": current_query,
            "current_state": state, "state_labels": LABELS, "state_counts": counts,
        },
    )


@router.post("/")
def create_meeting_note(
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
    title: str = Form("無題の議事録"),
):
    require_can_edit(current_user)
    display_name = _display_name(current_user)
    note = MeetingNote(
        title=(title or "").strip() or "無題の議事録",
        created_by=display_name,
        updated_by=display_name,
    )
    session.add(note)
    session.commit()
    session.refresh(note)
    return RedirectResponse(url=f"/meeting-notes/{note.id}", status_code=303)


@router.get("/{note_id}", response_class=HTMLResponse)
def meeting_note_detail(
    request: Request,
    note_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    note = load_note(session, note_id, current_user)
    highlights = highlights_for_source(
        session,
        current_user,
        HighlightSourceType.meeting_note,
        note_id,
    )
    event_series_list = list_event_series(session)
    return templates.TemplateResponse(
        request,
        "meeting_notes/detail.html",
        {
            "note": note,
            "note_can_edit": current_user.can_edit and note.lifecycle_status == "active",
            "lifecycle": _lifecycle_info(session, note, current_user),
            "current_user": current_user,
            "editor_user_name": _display_name(current_user),
            "highlights": highlights,
            "event_series_list": event_series_list,
            "event_series_by_id": {item.id: item for item in event_series_list},
            "record_origin_options": list(InstitutionalRecordOrigin),
            "suggested_fiscal_year": fiscal_year_for_datetime(note.created_at),
        },
    )


@router.get("/api/{note_id}/content")
def meeting_note_content(
    note_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    _ = current_user
    note = load_note(session, note_id, current_user)
    return _note_content(note)


@router.post("/api/{note_id}/save")
def save_meeting_note(
    note_id: int,
    payload: SaveMeetingNotePayload,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    note = load_note(session, note_id, current_user)
    if note.lifecycle_status != "active":
        return JSONResponse({"status": "state_changed", "detail": "議事録の状態が変わりました。未保存の入力を保持して編集を停止しました。",
                             **_note_content(note)}, status_code=409)
    if payload.editor_version != 2:
        return JSONResponse({"status": "upgrade_required", "detail": "議事録の編集機能が更新されました。未保存の入力を控えてから画面を開き直してください。"}, status_code=426)
    if payload.base_revision is not None and payload.base_revision != _note_content(note)["revision"]:
        return JSONResponse({"status": "conflict", **_note_content(note)}, status_code=409)
    try:
        decoded_content = base64.b64decode(payload.content_base64 or "", validate=True)
    except binascii.Error as exc:
        raise HTTPException(status_code=400, detail="content_base64 が不正です") from exc

    result = session.execute(update(MeetingNote).where(
        MeetingNote.id == note_id, MeetingNote.updated_at == note.updated_at,
        MeetingNote.content == note.content, MeetingNote.title == note.title,
        MeetingNote.lifecycle_status == "active", MeetingNote.lifecycle_version == note.lifecycle_version,
    ).values(
        title=(payload.title or "").strip() or "無題の議事録", content=decoded_content,
        search_text=payload.plain_text.strip() or None,
        updated_at=utc_now(), updated_by=_display_name(current_user),
    ).execution_options(synchronize_session=False))
    if result.rowcount != 1:
        session.rollback()
        note = load_note(session, note_id, current_user)
        if note.lifecycle_status != "active":
            return JSONResponse({"status": "state_changed", **_note_content(note)}, status_code=409)
        return JSONResponse({"status": "conflict", **_note_content(note)}, status_code=409)
    session.commit()
    session.refresh(note)
    return {"status": "ok", "revision": _note_content(note)["revision"]}


def _lifecycle_info(session: Session, note: MeetingNote, principal) -> dict:
    actions = session.exec(select(MeetingNoteAction).where(MeetingNoteAction.note_id == note.id)
                           .order_by(MeetingNoteAction.id.desc())).all()
    allowed = [name for name, (before, _) in TRANSITIONS.items()
               if before == note.lifecycle_status and principal.can_edit
               and (name not in ("trash", "untrash") or principal.is_admin)]
    return {"status": note.lifecycle_status, "label": LABELS[note.lifecycle_status],
            "version": note.lifecycle_version, "revision": _note_content(note)["revision"],
            "allowed_actions": allowed, "related": relations(session, note.id, principal),
            "history": [{"action": ACTION_LABELS[a.action], "actor": a.actor_name,
                         "at": a.created_at.isoformat() + ("Z" if a.created_at.tzinfo is None else ""),
                         "reason": a.reason} for a in actions]}


@router.get("/api/{note_id}/lifecycle")
def meeting_note_state(note_id: int, session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    note = load_note(session, note_id, current_user)
    return JSONResponse(_lifecycle_info(session, note, current_user), headers={"Cache-Control": "no-store"})


class LifecyclePayload(BaseModel):
    expected_version: int = Field(ge=0)
    expected_revision: str
    reason: str = Field(default="", max_length=500)


@router.post("/api/{note_id}/lifecycle/{action}")
async def change_meeting_note_state(note_id: int, action: str, payload: LifecyclePayload,
                                   session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_can_edit(current_user)
    if action not in TRANSITIONS:
        raise HTTPException(404, "操作が見つかりません")
    if action in ("trash", "untrash") and not current_user.is_admin:
        raise HTTPException(403, "ごみ箱の操作には管理者権限が必要です")
    before, after = TRANSITIONS[action]
    # Lock before inspecting source relations, including on SQLite. Reference
    # writes acquire the same row via lock_for_edit in the shared service.
    result = session.execute(update(MeetingNote).where(
        MeetingNote.id == note_id, MeetingNote.lifecycle_status == before,
        MeetingNote.lifecycle_version == payload.expected_version,
    ).values(lifecycle_version=MeetingNote.lifecycle_version).execution_options(synchronize_session=False))
    note = load_note(session, note_id, current_user)
    if result.rowcount != 1 or _note_content(note)["revision"] != payload.expected_revision:
        session.rollback()
        raise HTTPException(409, "ほかの職員が内容または状態を更新しました。再表示して確認してください。")
    if action == "trash" and relations(session, note_id, current_user):
        session.rollback()
        raise HTTPException(409, "関連する記録があるため、ごみ箱へ移動できません。")
    note.lifecycle_status = after
    note.lifecycle_version += 1
    session.add(note)
    session.add(MeetingNoteAction(note_id=note_id, action=action, from_status=before, to_status=after,
                                 actor_user_id=str(current_user.user_id) if current_user.user_id else None,
                                 actor_name=_display_name(current_user), reason=payload.reason.strip() or None if action == "trash" else None))
    session.commit()
    session.refresh(note)
    await manager.invalidate(note_id, note)
    return _lifecycle_info(session, note, current_user)


@router.websocket("/ws/{note_id}")
async def meeting_note_websocket(
    websocket: WebSocket,
    note_id: int,
    session: Session = Depends(get_session),
):
    principal = resolve_staff_principal(websocket)
    if principal is None:
        logger.warning("Meeting note WebSocket rejected: unauthenticated note_id=%s", note_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not principal.can_edit:
        logger.warning("Meeting note WebSocket rejected: insufficient permission note_id=%s", note_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    if not websocket_origin_allowed(websocket):
        logger.warning("Meeting note WebSocket rejected: origin policy note_id=%s", note_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    # Old Quill clients do not know table embeds and must not relay destructive edits.
    if websocket.query_params.get("editor_version") != "2":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    try:
        initial_note = session.get(MeetingNote, note_id)
        note_exists = initial_note is not None and initial_note.lifecycle_status == "active"
        initial_version = initial_note.lifecycle_version if initial_note else None
        bind = session.get_bind()
    finally:
        # Release the DB connection before entering the long-lived receive loop.
        session.close()
    if not note_exists:
        logger.warning("Meeting note WebSocket rejected: unknown note_id=%s", note_id)
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await manager.connect(note_id, websocket)
    try:
        while True:
            try:
                data = await asyncio.wait_for(websocket.receive_bytes(), timeout=1)
            except asyncio.TimeoutError:
                data = None
            with Session(bind) as check:
                current = check.get(MeetingNote, note_id)
                if current is None or current.lifecycle_status != "active" or current.lifecycle_version != initial_version:
                    await websocket.send_json({"type": "lifecycle"})
                    await websocket.close(code=4009)
                    break
            if data is None:
                continue
            await manager.broadcast(note_id, data, exclude=websocket)
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        manager.disconnect(note_id, websocket)
