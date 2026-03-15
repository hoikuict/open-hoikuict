from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_mock_current_user
from database import engine
from models import Child, ChildStatus, Classroom, DailyContactEntry, ParentAccount

router = APIRouter(prefix="/daily-contacts", tags=["daily_contacts"])
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
def daily_contact_list(
    request: Request,
    target_date: Optional[str] = Query(default=None, alias="date"),
    classroom_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    day = _parse_target_date(target_date)
    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
    children_query = (
        select(Child)
        .options(selectinload(Child.classroom))
        .where(Child.status == ChildStatus.enrolled)
        .order_by(Child.classroom_id, Child.last_name_kana, Child.first_name_kana)
    )
    if classroom_id:
        children_query = children_query.where(Child.classroom_id == classroom_id)
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

    return templates.TemplateResponse(
        request,
        "daily_contacts/list.html",
        {
            "request": request,
            "current_user": current_user,
            "target_date": day,
            "target_date_value": day.isoformat(),
            "classrooms": classrooms,
            "selected_classroom_id": classroom_id,
            "children": children,
            "entry_by_child_id": entry_by_child_id,
        },
    )


@router.get("/{child_id}", response_class=HTMLResponse)
def daily_contact_detail(
    request: Request,
    child_id: int,
    target_date: Optional[str] = Query(default=None, alias="date"),
    session: Session = Depends(get_session),
    current_user=Depends(get_mock_current_user),
):
    day = _parse_target_date(target_date)
    child = session.exec(
        select(Child)
        .options(selectinload(Child.classroom))
        .where(Child.id == child_id)
    ).first()
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")

    entry = session.exec(
        select(DailyContactEntry)
        .options(selectinload(DailyContactEntry.parent_account))
        .where(
            DailyContactEntry.child_id == child_id,
            DailyContactEntry.target_date == day,
        )
    ).first()

    return templates.TemplateResponse(
        request,
        "daily_contacts/detail.html",
        {
            "request": request,
            "current_user": current_user,
            "target_date": day,
            "target_date_value": day.isoformat(),
            "child": child,
            "entry": entry,
        },
    )
