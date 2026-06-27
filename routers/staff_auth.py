from dataclasses import dataclass
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import (
    ROLE_LABELS,
    Role,
    clear_mock_staff_session,
    get_current_staff_user,
    set_mock_staff_session,
    set_staff_cookies,
)
from database import get_session
from models import Staff, StaffStatus, User


router = APIRouter(prefix="/staff", tags=["staff-auth"])
templates = Jinja2Templates(directory="templates")

DEFAULT_STAFF_REDIRECT = "/children"
DEFAULT_LOGOUT_REDIRECT = "/staff/login"


@dataclass(slots=True)
class StaffLoginOption:
    id: int | UUID
    display_name: str
    role: Role
    employment_type_label: str = "-"
    primary_classroom_name: str = ""
    login_field: str = "staff_id"
    can_manage_child_records: bool = False

    @property
    def can_manage_child_records_effective(self) -> bool:
        return self.role == Role.ADMIN or self.can_manage_child_records


def _normalize_redirect(redirect_to: str | None, fallback: str) -> str:
    if redirect_to and redirect_to.startswith("/") and not redirect_to.startswith("//"):
        return redirect_to
    return fallback


def _parse_optional_int(raw_value: str | None) -> int | None:
    if raw_value in (None, ""):
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return None


def _parse_optional_uuid(raw_value: str | None) -> UUID | None:
    if raw_value in (None, ""):
        return None
    try:
        return UUID(str(raw_value))
    except (TypeError, ValueError):
        return None


def _role_from_calendar_user(user: User) -> Role:
    if user.staff_role == "admin":
        return Role.ADMIN
    if user.staff_role == "can_edit":
        return Role.CAN_EDIT
    return Role.VIEW_ONLY


def _active_staff_members(session: Session) -> list[StaffLoginOption]:
    staff_members = session.exec(
        select(Staff)
        .where(Staff.status == StaffStatus.active)
        .order_by(Staff.id)
    ).all()
    if staff_members:
        return [
            StaffLoginOption(
                id=staff.id or 0,
                display_name=staff.display_name,
                role=staff.role,
                employment_type_label=staff.employment_type.label,
                primary_classroom_name=staff.primary_classroom_name,
                can_manage_child_records=staff.can_manage_child_records_effective,
            )
            for staff in staff_members
        ]

    calendar_users = session.exec(
        select(User)
        .where(
            User.is_active.is_(True),
            User.staff_sort_order < 200,
        )
        .order_by(User.staff_sort_order, User.display_name, User.id)
    ).all()
    seen_names: set[str] = set()
    options: list[StaffLoginOption] = []
    for user in calendar_users:
        name_key = user.display_name.strip()
        if not name_key or name_key in seen_names:
            continue
        seen_names.add(name_key)
        options.append(
            StaffLoginOption(
                id=user.id,
                display_name=user.display_name,
                role=_role_from_calendar_user(user),
                login_field="user_id",
                can_manage_child_records=user.can_manage_child_records_effective,
            )
        )
    return options


@router.get("/login", response_class=HTMLResponse)
def staff_login_page(
    request: Request,
    redirect: str = DEFAULT_STAFF_REDIRECT,
    current_user=Depends(get_current_staff_user),
    session: Session = Depends(get_session),
):
    return templates.TemplateResponse(
        request,
        "staff_auth/login.html",
        {
            "request": request,
            "current_user": current_user,
            "redirect_to": _normalize_redirect(redirect, DEFAULT_STAFF_REDIRECT),
            "users": _active_staff_members(session),
            "role_labels": ROLE_LABELS,
        },
    )


@router.post("/login")
def staff_login(
    staff_id: str = Form(""),
    user_id: str = Form(""),
    role: str = Form(""),
    redirect_to: str = Form(DEFAULT_STAFF_REDIRECT),
    session: Session = Depends(get_session),
):
    target = _normalize_redirect(redirect_to, DEFAULT_STAFF_REDIRECT)

    parsed_user_id = _parse_optional_uuid(user_id)
    if parsed_user_id is not None:
        calendar_user = session.get(User, parsed_user_id)
        if calendar_user is None or not calendar_user.is_active or calendar_user.staff_sort_order >= 200:
            return RedirectResponse(url=f"/staff/login?redirect={target}", status_code=303)

        selected_staff = session.exec(
            select(Staff).where(
                Staff.display_name == calendar_user.display_name,
                Staff.status == StaffStatus.active,
            ).order_by(Staff.id)
        ).first()
        response = RedirectResponse(url=target, status_code=303)
        resolved_role = (
            Role.ADMIN
            if calendar_user.staff_role == "admin"
            else Role.CAN_EDIT
            if calendar_user.staff_role == "can_edit"
            else Role.VIEW_ONLY
        )
        if selected_staff is not None:
            set_mock_staff_session(
                response,
                staff_id=selected_staff.id,
                name=selected_staff.display_name,
                role=selected_staff.role,
                primary_classroom_id=selected_staff.primary_classroom_id,
                employment_type=selected_staff.employment_type.value,
                calendar_user_id=str(calendar_user.id),
                can_manage_child_records=selected_staff.can_manage_child_records_effective,
            )
        else:
            set_staff_cookies(
                response,
                role=resolved_role,
                name=calendar_user.display_name,
                user_id=str(calendar_user.id),
                can_manage_child_records=calendar_user.can_manage_child_records_effective,
            )
        return response

    selected_staff = None
    parsed_staff_id = _parse_optional_int(staff_id)
    if parsed_staff_id is not None:
        selected_staff = session.exec(
            select(Staff).where(
                Staff.id == parsed_staff_id,
                Staff.status == StaffStatus.active,
            )
        ).first()

    if selected_staff is None and role in {item.value for item in Role}:
        selected_staff = session.exec(
            select(Staff).where(
                Staff.role == Role(role),
                Staff.status == StaffStatus.active,
            ).order_by(Staff.id)
        ).first()

    if selected_staff is None:
        return RedirectResponse(url=f"/staff/login?redirect={target}", status_code=303)

    calendar_user = session.exec(
        select(User).where(
            User.display_name == selected_staff.display_name,
            User.is_active.is_(True),
        )
    ).first()

    response = RedirectResponse(url=target, status_code=303)
    set_mock_staff_session(
        response,
        staff_id=selected_staff.id,
        name=selected_staff.display_name,
        role=selected_staff.role,
        primary_classroom_id=selected_staff.primary_classroom_id,
        employment_type=selected_staff.employment_type.value,
        calendar_user_id=str(calendar_user.id) if calendar_user else None,
        can_manage_child_records=selected_staff.can_manage_child_records_effective,
    )
    return response


@router.post("/logout")
def staff_logout(redirect_to: str = Form(DEFAULT_LOGOUT_REDIRECT)):
    target = _normalize_redirect(redirect_to, DEFAULT_LOGOUT_REDIRECT)
    response = RedirectResponse(url=target, status_code=303)
    clear_mock_staff_session(response)
    return response
