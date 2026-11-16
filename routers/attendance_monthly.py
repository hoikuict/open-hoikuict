import json
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, select

from attendance_monthly_service import AttendanceEditError, month_days, monthly_rows, save_times
from auth import get_current_staff_user, require_admin, require_can_edit
from database import get_session
from models import AttendanceRecord, Child, ChildStatus, Classroom
from template_utils import create_templates

router = APIRouter(prefix="/monthly")
templates = create_templates()


def page(request, session, actor, month, child_id=None, classroom_id=None, *, notice="",
         error="", draft=None, status_code=200):
    try:
        first, last = month_days(month)
    except AttendanceEditError as exc:
        raise HTTPException(exc.status_code, str(exc)) from exc
    month = first.strftime("%Y-%m")
    classroom_id = classroom_id or None
    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
    classroom_names = {item.id: item.name for item in classrooms}
    children = session.exec(select(Child).order_by(Child.last_name_kana, Child.first_name_kana, Child.id)).all()
    recorded_ids = set(session.exec(select(AttendanceRecord.child_id).where(
        AttendanceRecord.attendance_date >= first, AttendanceRecord.attendance_date <= last)).all())
    children = [child for child in children if
                (not classroom_id or child.classroom_id == classroom_id) and (
                    child.id in recorded_ids or (child.enrollment_date <= last and
                    ((child.withdrawal_date and child.withdrawal_date >= first)
                     or (not child.withdrawal_date and child.status == ChildStatus.enrolled)))) ]
    selected = next((child for child in children if child.id == child_id), None)
    if child_id and selected is None:
        raise HTTPException(404, "この月・クラスの園児が見つかりません。")
    selected = selected or (children[0] if children else None)
    rows = monthly_rows(session, selected, month) if selected else []
    query = urlencode({"month": month, "child_id": selected.id if selected else "",
                       "classroom_id": classroom_id or ""})
    data = {"rows": rows, "child_id": selected.id if selected else None,
            "child_name": selected.full_name if selected else "",
            "month": month, "can_edit": actor.can_edit, "is_admin": actor.is_admin,
            "actor": actor.name, "draft": draft, "return_query": query}
    return templates.TemplateResponse(request, "attendance_monthly.html", {
        "current_user": actor, "month": month, "classrooms": classrooms,
        "classroom_id": classroom_id, "classroom_names": classroom_names,
        "children": children, "child": selected, "rows": rows, "data": data,
        "notice": notice, "error": error, "return_query": query,
        "missing_count": sum(row["missing"] and row["allowed"] for row in rows),
        "unknown_count": sum(row["unknown"] and row["allowed"] for row in rows),
        "corrected_count": sum(bool(row["history"]) for row in rows),
    }, status_code=status_code, headers={"Cache-Control": "private, no-store"})


@router.get("")
def monthly_page(request: Request, month: str = "", child_id: int | None = None,
                 classroom_id: int | None = None, saved: int = Query(0, ge=0, le=31),
                 session: Session = Depends(get_session), actor=Depends(get_current_staff_user)):
    return page(request, session, actor, month, child_id, classroom_id,
                notice=f"{saved}日分の登降園時刻を保存しました。" if saved else "")


def save_response(request, session, actor, child_id, month, classroom_id, items, reason, mode):
    draft = {"mode": mode, "items": items, "reason": reason}
    try:
        count = save_times(session, child_id=child_id, month=month, items=items,
                           reason=reason, actor=actor, bulk=mode == "bulk")
    except (AttendanceEditError, ValueError, OperationalError) as exc:
        session.rollback()
        message = ("他の操作が処理中です。入力を残しています。しばらくして再度保存してください。"
                   if isinstance(exc, OperationalError) else str(exc))
        return page(request, session, actor, month, child_id, classroom_id, error=message,
                    draft=draft, status_code=getattr(exc, "status_code", 409 if isinstance(exc, OperationalError) else 400))
    query = {"month": month, "child_id": child_id, "saved": count}
    if classroom_id:
        query["classroom_id"] = classroom_id
    return RedirectResponse("/attendance/monthly?" + urlencode(query), status_code=303)


@router.post("/{child_id}/day")
def save_day(request: Request, child_id: int, month: str = Form(...), date: str = Form(...),
             revision: str = Form(...), arrival: str = Form(""), departure: str = Form(""),
             next_day: bool = Form(False), repair_dates: bool = Form(False),
             reason: str = Form(""), classroom_id: int = Form(0),
             session: Session = Depends(get_session), actor=Depends(get_current_staff_user)):
    require_can_edit(actor)
    item = dict(date=date, revision=revision, arrival=arrival, departure=departure,
                next_day=next_day, repair_dates=repair_dates)
    return save_response(request, session, actor, child_id, month, classroom_id, [item], reason, "day")


@router.post("/{child_id}/bulk")
def save_bulk(request: Request, child_id: int, month: str = Form(...), payload: str = Form(...),
              reason: str = Form(""), classroom_id: int = Form(0),
              session: Session = Depends(get_session), actor=Depends(get_current_staff_user)):
    require_admin(actor)
    if len(payload) > 30000:
        raise HTTPException(400, "入力件数が多すぎます。")
    try:
        items = json.loads(payload)
    except ValueError as exc:
        raise HTTPException(400, "入力内容を読み取れません。画面を開き直してください。") from exc
    if not isinstance(items, list) or len(items) > 31 or any(not isinstance(item, dict) for item in items):
        raise HTTPException(400, "一括補完は最大31日です。")
    return save_response(request, session, actor, child_id, month, classroom_id, items, reason, "bulk")
