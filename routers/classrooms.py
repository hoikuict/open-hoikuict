from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit
from database import get_session
from models import Classroom
from time_utils import utc_now

router = APIRouter(prefix="/classrooms", tags=["classrooms"])
templates = Jinja2Templates(directory="templates")


def _all_classrooms(session: Session) -> list[Classroom]:
    return session.exec(
        select(Classroom)
        .options(selectinload(Classroom.children))
        .order_by(Classroom.display_order, Classroom.id)
    ).all()


def _load_classroom(session: Session, classroom_id: int) -> Classroom:
    classroom = session.exec(
        select(Classroom)
        .options(selectinload(Classroom.children))
        .where(Classroom.id == classroom_id)
    ).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="クラスが見つかりません")
    return classroom


def _render_form(
    request: Request,
    *,
    current_user,
    classroom: Classroom | None,
    action_url: str,
    submit_label: str,
    page_title: str,
    form_error: str = "",
    form_data: dict[str, object] | None = None,
):
    data = form_data or {
        "name": classroom.name if classroom else "",
        "display_order": classroom.display_order if classroom else 1,
    }
    return templates.TemplateResponse(
        "classrooms/form.html",
        {
            "request": request,
            "current_user": current_user,
            "classroom": classroom,
            "action_url": action_url,
            "submit_label": submit_label,
            "page_title": page_title,
            "form_error": form_error,
            "form_data": data,
        },
    )


def _validate_classroom_input(
    session: Session,
    *,
    name: str,
    display_order: int,
    classroom_id: int | None = None,
) -> str | None:
    normalized_name = name.strip()
    if not normalized_name:
        return "クラス名は必須です。"
    if display_order < 1:
        return "表示順は 1 以上で入力してください。"

    existing = session.exec(select(Classroom).where(Classroom.name == normalized_name)).first()
    if existing and existing.id != classroom_id:
        return "同じクラス名がすでに登録されています。"
    return None


@router.get("/", response_class=HTMLResponse)
def classroom_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    return templates.TemplateResponse(
        "classrooms/list.html",
        {
            "request": request,
            "current_user": current_user,
            "classrooms": _all_classrooms(session),
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_classroom_form(
    request: Request,
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    return _render_form(
        request,
        current_user=current_user,
        classroom=None,
        action_url="/classrooms/",
        submit_label="登録する",
        page_title="クラスを追加",
    )


@router.post("/")
def create_classroom(
    request: Request,
    name: str = Form(...),
    display_order: int = Form(1),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)

    validation_error = _validate_classroom_input(session, name=name, display_order=display_order)
    if validation_error:
        return _render_form(
            request,
            current_user=current_user,
            classroom=None,
            action_url="/classrooms/",
            submit_label="登録する",
            page_title="クラスを追加",
            form_error=validation_error,
            form_data={"name": name, "display_order": display_order},
        )

    classroom = Classroom(
        name=name.strip(),
        display_order=display_order,
        updated_at=utc_now(),
    )
    session.add(classroom)
    session.commit()
    return RedirectResponse(url="/classrooms/", status_code=303)


@router.get("/{classroom_id}/edit", response_class=HTMLResponse)
def edit_classroom_form(
    request: Request,
    classroom_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    classroom = _load_classroom(session, classroom_id)
    return _render_form(
        request,
        current_user=current_user,
        classroom=classroom,
        action_url=f"/classrooms/{classroom_id}/edit",
        submit_label="更新する",
        page_title=f"{classroom.name} を編集",
    )


@router.post("/{classroom_id}/edit")
def update_classroom(
    request: Request,
    classroom_id: int,
    name: str = Form(...),
    display_order: int = Form(1),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    classroom = _load_classroom(session, classroom_id)

    validation_error = _validate_classroom_input(
        session,
        name=name,
        display_order=display_order,
        classroom_id=classroom_id,
    )
    if validation_error:
        return _render_form(
            request,
            current_user=current_user,
            classroom=classroom,
            action_url=f"/classrooms/{classroom_id}/edit",
            submit_label="更新する",
            page_title=f"{classroom.name} を編集",
            form_error=validation_error,
            form_data={"name": name, "display_order": display_order},
        )

    classroom.name = name.strip()
    classroom.display_order = display_order
    classroom.updated_at = utc_now()
    session.add(classroom)
    session.commit()
    return RedirectResponse(url="/classrooms/", status_code=303)
