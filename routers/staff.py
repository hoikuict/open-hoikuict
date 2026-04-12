from __future__ import annotations

from sqlalchemy import or_
from sqlalchemy.orm import selectinload
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import (
    EMPLOYMENT_TYPE_LABELS,
    ROLE_LABELS,
    Role,
    clear_mock_staff_session,
    get_current_staff_user,
    require_admin,
    set_mock_staff_session,
)
from database import get_session
from models import Classroom, Staff, StaffEmploymentType, StaffStatus
from time_utils import utc_now

router = APIRouter(prefix="/staff", tags=["staff"])
templates = Jinja2Templates(directory="templates")


def _all_classrooms(session: Session) -> list[Classroom]:
    return session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()


def _list_staff(session: Session, *, q: str, status: str) -> list[Staff]:
    statement = select(Staff).options(selectinload(Staff.primary_classroom)).order_by(
        Staff.status,
        Staff.display_name,
        Staff.id,
    )
    if status == StaffStatus.active.value:
        statement = statement.where(Staff.status == StaffStatus.active)
    elif status == StaffStatus.retired.value:
        statement = statement.where(Staff.status == StaffStatus.retired)

    normalized_q = q.strip()
    if normalized_q:
        like_value = f"%{normalized_q}%"
        statement = statement.where(
            or_(
                Staff.full_name.ilike(like_value),
                Staff.display_name.ilike(like_value),
            )
        )
    return session.exec(statement).all()


def _active_staff(session: Session) -> list[Staff]:
    return session.exec(
        select(Staff)
        .options(selectinload(Staff.primary_classroom))
        .where(Staff.status == StaffStatus.active)
        .order_by(Staff.display_name, Staff.id)
    ).all()


def _load_staff(session: Session, staff_id: int) -> Staff:
    staff = session.exec(
        select(Staff)
        .options(selectinload(Staff.primary_classroom))
        .where(Staff.id == staff_id)
    ).first()
    if not staff:
        raise HTTPException(status_code=404, detail="職員が見つかりません")
    return staff


def _status_filter_options() -> list[dict[str, str]]:
    return [
        {"value": "active", "label": "在籍のみ"},
        {"value": "retired", "label": "退職のみ"},
        {"value": "all", "label": "すべて"},
    ]


def _staff_form_role_options() -> list[dict[str, str]]:
    return [{"value": role.value, "label": ROLE_LABELS.get(role, role.value)} for role in Role]


def _staff_form_status_options() -> list[dict[str, str]]:
    return [{"value": status.value, "label": status.label} for status in StaffStatus]


def _staff_form_employment_options() -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in EMPLOYMENT_TYPE_LABELS.items()]


def _parse_role(raw_role: str) -> Role | None:
    try:
        return Role(raw_role)
    except ValueError:
        return None


def _parse_status(raw_status: str) -> StaffStatus | None:
    try:
        return StaffStatus(raw_status)
    except ValueError:
        return None


def _parse_employment_type(raw_employment_type: str) -> StaffEmploymentType | None:
    try:
        return StaffEmploymentType(raw_employment_type)
    except ValueError:
        return None


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _resolve_classroom(session: Session, raw_primary_classroom_id: str) -> tuple[Classroom | None, str | None]:
    classroom_id = _parse_optional_int(raw_primary_classroom_id)
    if classroom_id is None:
        return None, None
    classroom = session.get(Classroom, classroom_id)
    if classroom is None:
        return None, "主担当クラスが見つかりません"
    return classroom, None


def _render_form(
    request: Request,
    *,
    current_user,
    classrooms: list[Classroom],
    staff: Staff | None,
    action_url: str,
    submit_label: str,
    page_title: str,
    form_error: str = "",
    form_data: dict[str, str] | None = None,
):
    data = form_data or {
        "full_name": staff.full_name if staff else "",
        "display_name": staff.display_name if staff else "",
        "role": staff.role.value if staff else Role.CAN_EDIT.value,
        "status": staff.status.value if staff else StaffStatus.active.value,
        "employment_type": staff.employment_type.value if staff else StaffEmploymentType.regular.value,
        "primary_classroom_id": str(staff.primary_classroom_id or "") if staff else "",
    }
    return templates.TemplateResponse(
        "staff/form.html",
        {
            "request": request,
            "current_user": current_user,
            "classrooms": classrooms,
            "staff": staff,
            "action_url": action_url,
            "submit_label": submit_label,
            "page_title": page_title,
            "form_error": form_error,
            "form_data": data,
            "role_options": _staff_form_role_options(),
            "status_options": _staff_form_status_options(),
            "employment_type_options": _staff_form_employment_options(),
        },
    )


def _render_mock_login(
    request: Request,
    *,
    current_user,
    staff_members: list[Staff],
    redirect_to: str,
    login_error: str = "",
):
    return templates.TemplateResponse(
        "staff/mock_login.html",
        {
            "request": request,
            "current_user": current_user,
            "staff_members": staff_members,
            "redirect_to": redirect_to or "/children",
            "login_error": login_error,
            "role_labels": ROLE_LABELS,
        },
    )


@router.get("/", response_class=HTMLResponse)
def staff_list(
    request: Request,
    q: str = "",
    status: str = "active",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    selected_status = status if status in {"active", "retired", "all"} else "active"
    return templates.TemplateResponse(
        "staff/list.html",
        {
            "request": request,
            "current_user": current_user,
            "staff_members": _list_staff(session, q=q, status=selected_status),
            "search_query": q,
            "selected_status": selected_status,
            "status_filter_options": _status_filter_options(),
            "role_labels": ROLE_LABELS,
            "employment_type_labels": EMPLOYMENT_TYPE_LABELS,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_staff_form(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    return _render_form(
        request,
        current_user=current_user,
        classrooms=_all_classrooms(session),
        staff=None,
        action_url="/staff/",
        submit_label="登録する",
        page_title="職員を登録",
    )


@router.post("/")
def create_staff(
    request: Request,
    full_name: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(Role.CAN_EDIT.value),
    status: str = Form(StaffStatus.active.value),
    employment_type: str = Form(StaffEmploymentType.regular.value),
    primary_classroom_id: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)

    normalized_full_name = full_name.strip()
    normalized_display_name = display_name.strip()
    selected_role = _parse_role(role)
    selected_status = _parse_status(status)
    selected_employment_type = _parse_employment_type(employment_type)
    selected_classroom, classroom_error = _resolve_classroom(session, primary_classroom_id)

    form_error = ""
    if not normalized_full_name:
        form_error = "氏名を入力してください"
    elif not normalized_display_name:
        form_error = "表示名を入力してください"
    elif selected_role is None:
        form_error = "権限を正しく選択してください"
    elif selected_status is None:
        form_error = "在籍状態を正しく選択してください"
    elif selected_employment_type is None:
        form_error = "雇用区分を正しく選択してください"
    elif classroom_error:
        form_error = classroom_error

    if form_error:
        return _render_form(
            request,
            current_user=current_user,
            classrooms=_all_classrooms(session),
            staff=None,
            action_url="/staff/",
            submit_label="登録する",
            page_title="職員を登録",
            form_error=form_error,
            form_data={
                "full_name": full_name,
                "display_name": display_name,
                "role": role,
                "status": status,
                "employment_type": employment_type,
                "primary_classroom_id": primary_classroom_id,
            },
        )

    staff = Staff(
        full_name=normalized_full_name,
        display_name=normalized_display_name,
        role=selected_role,
        status=selected_status,
        employment_type=selected_employment_type,
        primary_classroom_id=selected_classroom.id if selected_classroom else None,
        updated_at=utc_now(),
    )
    session.add(staff)
    session.commit()
    return RedirectResponse(url="/staff/", status_code=303)


@router.get("/{staff_id}/edit", response_class=HTMLResponse)
def edit_staff_form(
    request: Request,
    staff_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    staff = _load_staff(session, staff_id)
    return _render_form(
        request,
        current_user=current_user,
        classrooms=_all_classrooms(session),
        staff=staff,
        action_url=f"/staff/{staff_id}/edit",
        submit_label="更新する",
        page_title=f"{staff.display_name} を編集",
    )


@router.post("/{staff_id}/edit")
def update_staff(
    request: Request,
    staff_id: int,
    full_name: str = Form(...),
    display_name: str = Form(...),
    role: str = Form(Role.CAN_EDIT.value),
    status: str = Form(StaffStatus.active.value),
    employment_type: str = Form(StaffEmploymentType.regular.value),
    primary_classroom_id: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    staff = _load_staff(session, staff_id)

    normalized_full_name = full_name.strip()
    normalized_display_name = display_name.strip()
    selected_role = _parse_role(role)
    selected_status = _parse_status(status)
    selected_employment_type = _parse_employment_type(employment_type)
    selected_classroom, classroom_error = _resolve_classroom(session, primary_classroom_id)

    form_error = ""
    if not normalized_full_name:
        form_error = "氏名を入力してください"
    elif not normalized_display_name:
        form_error = "表示名を入力してください"
    elif selected_role is None:
        form_error = "権限を正しく選択してください"
    elif selected_status is None:
        form_error = "在籍状態を正しく選択してください"
    elif selected_employment_type is None:
        form_error = "雇用区分を正しく選択してください"
    elif classroom_error:
        form_error = classroom_error

    if form_error:
        return _render_form(
            request,
            current_user=current_user,
            classrooms=_all_classrooms(session),
            staff=staff,
            action_url=f"/staff/{staff_id}/edit",
            submit_label="更新する",
            page_title=f"{staff.display_name} を編集",
            form_error=form_error,
            form_data={
                "full_name": full_name,
                "display_name": display_name,
                "role": role,
                "status": status,
                "employment_type": employment_type,
                "primary_classroom_id": primary_classroom_id,
            },
        )

    staff.full_name = normalized_full_name
    staff.display_name = normalized_display_name
    staff.role = selected_role
    staff.status = selected_status
    staff.employment_type = selected_employment_type
    staff.primary_classroom_id = selected_classroom.id if selected_classroom else None
    staff.updated_at = utc_now()
    session.add(staff)
    session.commit()
    return RedirectResponse(url="/staff/", status_code=303)


@router.get("/mock-login", response_class=HTMLResponse)
def mock_login_form(
    request: Request,
    redirect: str = "/children",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    target = redirect if redirect.startswith("/") and not redirect.startswith("//") else "/children"
    return RedirectResponse(url=f"/staff/login?redirect={target}", status_code=303)


@router.post("/mock-login")
def mock_login(
    request: Request,
    staff_id: str = Form(""),
    redirect_to: str = Form("/children"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    selected_staff_id = _parse_optional_int(staff_id)
    if selected_staff_id is None:
        return _render_mock_login(
            request,
            current_user=current_user,
            staff_members=_active_staff(session),
            redirect_to=redirect_to,
            login_error="職員を選択してください",
        )

    staff = _load_staff(session, selected_staff_id)
    if staff.status != StaffStatus.active:
        return _render_mock_login(
            request,
            current_user=current_user,
            staff_members=_active_staff(session),
            redirect_to=redirect_to,
            login_error="在籍中の職員のみ選択できます",
        )

    response = RedirectResponse(url=redirect_to or "/children", status_code=303)
    set_mock_staff_session(
        response,
        staff_id=staff.id,
        name=staff.display_name,
        role=staff.role,
        primary_classroom_id=staff.primary_classroom_id,
        employment_type=staff.employment_type.value,
    )
    return response


@router.post("/mock-logout")
def mock_logout(redirect_to: str = Form("/children")):
    response = RedirectResponse(url=redirect_to or "/children", status_code=303)
    clear_mock_staff_session(response)
    return response
