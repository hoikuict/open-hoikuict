from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import get_mock_current_user, require_can_edit
from database import engine
from models import AttendanceRecord, Child, ChildStatus

router = APIRouter(prefix="/attendance", tags=["attendance"])
templates = Jinja2Templates(directory="templates")


def get_session():
    with Session(engine) as session:
        yield session


def _parse_target_date(raw: Optional[str]) -> date:
    if not raw:
        return date.today()
    try:
        return date.fromisoformat(raw)
    except ValueError:
        return date.today()


@router.get("/", response_class=HTMLResponse)
def attendance_list(
    request: Request,
    target_date: Optional[str] = Query(default=None, alias="date"),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    day = _parse_target_date(target_date)

    children_stmt = (
        select(Child)
        .where(Child.status == ChildStatus.enrolled)
        .order_by(Child.last_name_kana, Child.first_name_kana)
    )
    children = session.exec(children_stmt).all()
    child_ids = {child.id for child in children}

    records_stmt = select(AttendanceRecord).where(AttendanceRecord.attendance_date == day)
    records = session.exec(records_stmt).all()
    records_by_child = {record.child_id: record for record in records if record.child_id in child_ids}

    checked_in_count = sum(1 for record in records if record.child_id in child_ids and record.check_in_at is not None)
    checked_out_count = sum(1 for record in records if record.child_id in child_ids and record.check_out_at is not None)

    return templates.TemplateResponse(
        "attendance/list.html",
        {
            "request": request,
            "children": children,
            "records_by_child": records_by_child,
            "target_date": day,
            "target_date_value": day.isoformat(),
            "total_children": len(children),
            "checked_in_count": checked_in_count,
            "checked_out_count": checked_out_count,
            "not_checked_in_count": max(len(children) - checked_in_count, 0),
            "current_user": current_user,
        },
    )


@router.post("/{child_id}/check-in")
def check_in(
    child_id: int,
    target_date: str = Form(..., alias="date"),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    require_can_edit(current_user)

    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    if child.status != ChildStatus.enrolled:
        raise HTTPException(status_code=400, detail="在園児のみ打刻できます")

    day = _parse_target_date(target_date)
    record = session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.child_id == child_id,
            AttendanceRecord.attendance_date == day,
        )
    ).first()

    now = datetime.now()
    if not record:
        record = AttendanceRecord(child_id=child_id, attendance_date=day, check_in_at=now)
    elif record.check_in_at is None:
        record.check_in_at = now

    record.updated_at = now
    session.add(record)
    session.commit()

    return RedirectResponse(url=f"/attendance?date={day.isoformat()}", status_code=303)


@router.post("/{child_id}/check-out")
def check_out(
    child_id: int,
    target_date: str = Form(..., alias="date"),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    require_can_edit(current_user)

    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    if child.status != ChildStatus.enrolled:
        raise HTTPException(status_code=400, detail="在園児のみ打刻できます")

    day = _parse_target_date(target_date)
    record = session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.child_id == child_id,
            AttendanceRecord.attendance_date == day,
        )
    ).first()

    if not record or record.check_in_at is None:
        raise HTTPException(status_code=400, detail="先に登園打刻を行ってください")

    now = datetime.now()
    if record.check_out_at is None:
        record.check_out_at = now
    record.updated_at = now

    session.add(record)
    session.commit()

    return RedirectResponse(url=f"/attendance?date={day.isoformat()}", status_code=303)
