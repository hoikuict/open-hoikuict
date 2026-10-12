from datetime import date, timedelta
import re
import unicodedata
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user
from daily_contact_reply_fields import (
    reply_field_definitions,
    reply_values_for_form,
    reply_values_from_mapping,
)
from database import get_session
from models import AttendanceRecord, Child, ChildStatus, Classroom, DailyContactEntry, DailyContactReply, DailyContactReplyStatus
from home_care_details import STOOL_LABELS
from time_utils import local_today, utc_now

router = APIRouter(prefix="/daily-contacts", tags=["daily_contacts"])
from template_utils import create_templates

templates = create_templates()

DAILY_CONTACT_SORT_OPTIONS = {
    "classroom": "クラス・園児順",
    "unsubmitted_first": "未提出を先頭",
    "submitted_first": "提出済みを先頭",
    "unsent_first": "園の未送信を先頭",
}

DAILY_CONTACT_REPLY_NOTICE_MESSAGES = {
    "reply_saved": "園からの返信を下書き保存しました。",
    "reply_published": "園からの返信を保護者に公開しました。",
}


def _parse_target_date(raw: Optional[str]) -> date:
    if not raw:
        return local_today()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(400, "日付を確認してください。") from exc


def _normalize_sort(raw: Optional[str]) -> str:
    return raw if raw in DAILY_CONTACT_SORT_OPTIONS else "classroom"


def _normalize_view(raw: Optional[str]) -> str:
    return "status" if raw == "status" else "content"


def _temperature_display(raw: Optional[str]) -> str:
    value = unicodedata.normalize("NFKC", str(raw or "")).strip()
    return value + "℃" if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) else value


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    cleaned = str(raw).strip() if raw is not None else ""
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def _child_sort_key(child: Child) -> tuple:
    classroom = child.classroom
    return (
        classroom.display_order if classroom else 999,
        child.classroom_id or 0,
        child.last_name_kana or "",
        child.first_name_kana or "",
        child.id or 0,
    )


def _sort_children_by_contact_status(
    children: list[Child],
    entry_by_child_id: dict[int, DailyContactEntry],
    sort: str,
) -> list[Child]:
    if sort == "unsubmitted_first":
        return sorted(
            children,
            key=lambda child: (
                1 if child.id in entry_by_child_id else 0,
                _child_sort_key(child),
            ),
        )
    if sort == "submitted_first":
        return sorted(
            children,
            key=lambda child: (
                0 if child.id in entry_by_child_id else 1,
                _child_sort_key(child),
            ),
        )
    return sorted(children, key=_child_sort_key)


def _daily_contact_query(day: date, classroom_id: Optional[int], sort: str, *, view: str = "content", **extra: str) -> str:
    params: dict[str, str] = {
        "date": day.isoformat(),
        "sort": _normalize_sort(sort),
    }
    if classroom_id is not None:
        params["classroom_id"] = str(classroom_id)
    if _normalize_view(view) == "status":
        params["view"] = "status"
    params.update({key: value for key, value in extra.items() if value})
    return urlencode(params)


def _load_daily_contact_reply(session: Session, child_id: int, day: date) -> DailyContactReply | None:
    return session.exec(
        select(DailyContactReply).where(
            DailyContactReply.child_id == child_id,
            DailyContactReply.target_date == day,
        )
    ).first()


@router.get("/", response_class=HTMLResponse)
def daily_contact_list(
    request: Request,
    target_date: Optional[str] = Query(default=None, alias="date"),
    classroom_id: Optional[str] = Query(default=None),
    sort: Optional[str] = Query(default="classroom"),
    view: Optional[str] = Query(default="content"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    day = _parse_target_date(target_date)
    selected_classroom_id = _parse_optional_int(classroom_id)
    selected_sort = _normalize_sort(sort)
    selected_view = _normalize_view(view)
    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
    children_query = (
        select(Child)
        .options(selectinload(Child.classroom))
        .where(Child.status == ChildStatus.enrolled)
    )
    if selected_classroom_id:
        children_query = children_query.where(Child.classroom_id == selected_classroom_id)
    children = session.exec(children_query).all()
    child_ids = [child.id for child in children if child.id is not None]
    entries = session.exec(
        select(DailyContactEntry)
        .options(selectinload(DailyContactEntry.parent_account), selectinload(DailyContactEntry.child))
        .where(
            DailyContactEntry.target_date == day,
            DailyContactEntry.child_id.in_(child_ids) if child_ids else False,
        )
    ).all() if child_ids else []
    entry_by_child_id = {entry.child_id: entry for entry in entries}
    replies = session.exec(
        select(DailyContactReply).where(
            DailyContactReply.target_date == day,
            DailyContactReply.child_id.in_(child_ids) if child_ids else False,
        )
    ).all() if child_ids else []
    reply_by_child_id = {reply.child_id: reply for reply in replies}
    pickup_by_child_id = {}
    if selected_view == "content" and child_ids:
        pickup_by_child_id = {record.child_id: record for record in session.exec(
            select(AttendanceRecord).where(
                AttendanceRecord.attendance_date == day,
                AttendanceRecord.child_id.in_(child_ids),
            )
        ).all()}
    children = _sort_children_by_contact_status(children, entry_by_child_id, selected_sort)
    if selected_sort == "unsent_first":
        children.sort(key=lambda child: bool(
            (reply := reply_by_child_id.get(child.id)) and reply.status == DailyContactReplyStatus.published
            and reply.pending_draft is None
        ))

    return templates.TemplateResponse(
        request,
        "daily_contacts/list.html",
        {
            "request": request,
            "current_user": current_user,
            "target_date": day,
            "target_date_value": day.isoformat(),
            "classrooms": classrooms,
            "selected_classroom_id": selected_classroom_id,
            "selected_sort": selected_sort,
            "selected_view": selected_view,
            "sort_options": DAILY_CONTACT_SORT_OPTIONS,
            "detail_query_string": _daily_contact_query(day, selected_classroom_id, selected_sort, view=selected_view),
            "view_urls": {mode: "/daily-contacts/?" + _daily_contact_query(day, selected_classroom_id, selected_sort, view=mode)
                          for mode in ("content", "status")},
            "children": children,
            "entry_by_child_id": entry_by_child_id,
            "reply_by_child_id": reply_by_child_id,
            "pickup_by_child_id": pickup_by_child_id,
            "stool_labels": STOOL_LABELS,
            "temperature_display": _temperature_display,
            "contact_counts": {"total": len(children), "submitted": len(entries),
                               "missing": len(children) - len(entries),
                               "absent": sum(entry.is_absent_contact for entry in entries)},
            "published_reply_status": DailyContactReplyStatus.published,
        }, headers={"Cache-Control": "private, no-store"},
    )


def _detail_response(request, session, current_user, child_id, day, classroom_id, sort,
                     *, notice="", attempted=None, error="", status_code=200, view="content"):
    child = session.exec(select(Child).options(selectinload(Child.classroom)).where(Child.id == child_id)).first()
    if not child:
        raise HTTPException(404, "園児が見つかりません")
    entry = session.exec(select(DailyContactEntry).options(selectinload(DailyContactEntry.parent_account)).where(
        DailyContactEntry.child_id == child_id, DailyContactEntry.target_date == day,
    )).first()
    reply = _load_daily_contact_reply(session, child_id, day)
    draft = reply.pending_draft if reply and reply.pending_draft is not None else None
    message = draft.get("message", "") if draft is not None else (reply.message or "" if reply else "")
    return templates.TemplateResponse(request, "daily_contacts/detail.html", {
        "current_user": current_user, "target_date": day, "target_date_value": day.isoformat(),
        "selected_classroom_id": classroom_id, "selected_sort": sort, "selected_view": _normalize_view(view),
        "list_url": f"/daily-contacts/?{_daily_contact_query(day, classroom_id, sort, view=view)}",
        "previous_url": f"/daily-contacts/{child_id}?{_daily_contact_query(day - timedelta(days=1), classroom_id, sort, view=view)}" if day > date.min else None,
        "next_url": f"/daily-contacts/{child_id}?{_daily_contact_query(day + timedelta(days=1), classroom_id, sort, view=view)}" if day < date.max else None,
        "history_url": f"/daily-contacts/{child_id}/history?{_daily_contact_query(day, classroom_id, sort, view=view)}",
        "child": child, "entry": entry, "reply": reply, "reply_fields": reply_field_definitions(),
        "reply_form_values": attempted if attempted is not None else reply_values_for_form(reply),
        "reply_message_value": attempted.get("message", "") if attempted is not None else message,
        "reply_items": [{"label": field.label, "value": reply_values_for_form(reply).get(field.key)}
                        for field in reply_field_definitions() if reply_values_for_form(reply).get(field.key)],
        "notice": notice, "error": error,
        "reply_revision": reply.updated_at.isoformat() if reply else "new",
    }, status_code=status_code, headers={"Cache-Control": "private, no-store"})


@router.get("/{child_id}", response_class=HTMLResponse)
def daily_contact_detail(request: Request, child_id: int,
                         target_date: Optional[str] = Query(None, alias="date"),
                         classroom_id: Optional[str] = Query(None), sort: Optional[str] = Query("classroom"),
                         view: Optional[str] = Query("content"),
                         notice: Optional[str] = Query(None), session: Session = Depends(get_session),
                         current_user=Depends(get_current_staff_user)):
    return _detail_response(request, session, current_user, child_id, _parse_target_date(target_date),
                            _parse_optional_int(classroom_id), _normalize_sort(sort),
                            notice=DAILY_CONTACT_REPLY_NOTICE_MESSAGES.get(notice or "", ""), view=_normalize_view(view))


@router.get("/{child_id}/history", response_class=HTMLResponse)
def daily_contact_history(request: Request, child_id: int,
                          target_date: Optional[str] = Query(None, alias="date"),
                          classroom_id: Optional[str] = Query(None), sort: Optional[str] = Query("classroom"),
                          view: Optional[str] = Query("content"),
                          session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(404, "園児が見つかりません")
    day = _parse_target_date(target_date)
    start = max(day - timedelta(days=min(30, day.toordinal() - 1)), child.enrollment_date) if day >= child.enrollment_date else day
    entries = {item.target_date: item for item in session.exec(select(DailyContactEntry).where(
        DailyContactEntry.child_id == child_id, DailyContactEntry.target_date >= start, DailyContactEntry.target_date <= day)).all()}
    replies = {item.target_date: item for item in session.exec(select(DailyContactReply).where(
        DailyContactReply.child_id == child_id, DailyContactReply.target_date >= start, DailyContactReply.target_date <= day)).all()}
    scope, ordering = _parse_optional_int(classroom_id), _normalize_sort(sort)
    rows = [{"date": day - timedelta(days=offset), "url": f"/daily-contacts/{child_id}?{_daily_contact_query(day - timedelta(days=offset), scope, ordering, view=view)}"}
            for offset in range((day - start).days + 1)]
    return templates.TemplateResponse(request, "daily_contacts/history.html", {
        "current_user": current_user, "child": child, "rows": rows, "entries": entries, "replies": replies,
        "target_date_value": day.isoformat(), "selected_classroom_id": scope, "selected_sort": ordering, "selected_view": _normalize_view(view),
        "back_url": f"/daily-contacts/{child_id}?{_daily_contact_query(day, scope, ordering, view=view)}",
        "older_url": f"/daily-contacts/{child_id}/history?{_daily_contact_query(start - timedelta(days=1), scope, ordering, view=view)}" if start > child.enrollment_date else None,
    }, headers={"Cache-Control": "private, no-store"})


@router.post("/{child_id}/reply")
def save_daily_contact_reply(request: Request, child_id: int,
    target_date: str = Form(..., alias="date"), reply_nap_time: str = Form(""),
    reply_temperature: str = Form(""), reply_bowel_movement: str = Form(""), reply_appetite: str = Form(""),
    reply_message: str = Form(""), classroom_id: str = Form(""), sort: str = Form("classroom"),
    view: str = Form("content"),
    action: str = Form("draft"), revision: Optional[str] = Form(None),
    session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    if not getattr(current_user, "can_edit", False):
        raise HTTPException(403, "編集権限がありません")
    day = _parse_target_date(target_date)
    scope, ordering = _parse_optional_int(classroom_id), _normalize_sort(sort)
    child = session.exec(select(Child).where(Child.id == child_id, Child.status == ChildStatus.enrolled)).first()
    if not child:
        raise HTTPException(404, "園児が見つかりません")
    attempted = {"nap_time": reply_nap_time, "temperature": reply_temperature,
                 "bowel_movement": reply_bowel_movement, "appetite": reply_appetite, "message": reply_message}
    error = ""
    if action not in {"draft", "publish"}:
        error = "保存方法が不正です。"
    elif reply_temperature.strip().startswith(".") or reply_temperature.strip().endswith("."):
        error = "体温の整数と小数を両方選ぶか、体温をクリアしてください。"
    elif action == "publish" and not any(value.strip() for value in attempted.values()):
        error = "公開する内容を1つ以上入力してください。"
    elif any(len(value) > 10000 for value in attempted.values()):
        error = "各項目は10,000文字以内で入力してください。"
    elif any(attempted[field.key] and attempted[field.key] not in field.options for field in reply_field_definitions() if field.options):
        error = "選択項目の内容を確認してください。"
    reply = _load_daily_contact_reply(session, child_id, day)
    expected = reply.updated_at.isoformat() if reply else "new"
    if revision is not None and revision != expected:
        error = "別の職員が更新しています。入力内容は残しています。最新の内容を別画面で確認してから保存してください。"
    if error:
        if request.headers.get("X-Reply-Request") == "1":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": error}, status_code=409 if revision is not None and revision != expected else 400)
        return _detail_response(request, session, current_user, child_id, day, scope, ordering,
                                attempted=attempted, error=error, status_code=400, view=view)
    values = reply_values_from_mapping({"reply_" + key: value for key, value in attempted.items()})
    entry = session.exec(select(DailyContactEntry).where(DailyContactEntry.child_id == child_id,
                                                       DailyContactEntry.target_date == day)).first()
    now = utc_now()
    changes = {"daily_contact_entry_id": entry.id if entry else None, "updated_at": now}
    if action == "draft" and reply and reply.status == DailyContactReplyStatus.published:
        changes["pending_draft"] = {"field_values": values, "message": reply_message.strip(),
                                    "staff_name": current_user.name, "saved_at": now.isoformat()}
    else:
        changes.update(status=DailyContactReplyStatus.published if action == "publish" else DailyContactReplyStatus.draft,
                       field_values=values, message=reply_message.strip() or None,
                       staff_user_id=getattr(current_user, "user_id", None), staff_name=current_user.name,
                       published_at=now if action == "publish" else None, pending_draft=None)
    try:
        if reply is None:
            reply = DailyContactReply(child_id=child_id, target_date=day, created_at=now, **changes)
            session.add(reply)
            session.flush()
        else:
            changed = session.execute(update(DailyContactReply).where(
                DailyContactReply.id == reply.id, DailyContactReply.updated_at == reply.updated_at,
            ).values(**changes).execution_options(synchronize_session=False))
            if changed.rowcount != 1:
                raise ValueError("concurrent update")
        session.commit()
    except (IntegrityError, ValueError):
        session.rollback()
        message = "別の職員が更新しています。入力を控えて画面を開き直し、最新の内容を確認してください。"
        if request.headers.get("X-Reply-Request") == "1":
            from fastapi.responses import JSONResponse
            return JSONResponse({"detail": message}, status_code=409)
        return _detail_response(request, session, current_user, child_id, day, scope, ordering,
                                attempted=attempted, error=message, status_code=409, view=view)
    session.refresh(reply)
    notice = "reply_published" if action == "publish" else "reply_saved"
    if request.headers.get("X-Reply-Request") == "1":
        return {"revision": reply.updated_at.isoformat(), "notice": DAILY_CONTACT_REPLY_NOTICE_MESSAGES[notice],
                "status": "未送信の変更あり" if reply.pending_draft is not None else "公開済み" if action == "publish" else "未送信"}
    return RedirectResponse(f"/daily-contacts/{child_id}?{_daily_contact_query(day, scope, ordering, view=view, notice=notice)}", status_code=303)
