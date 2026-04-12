from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import ROLE_LABELS, Role, clear_mock_staff_session, get_current_staff_user, set_mock_staff_session
from database import get_session
from models import Staff, StaffStatus, User


router = APIRouter(prefix="/staff", tags=["staff-auth"])
templates = Jinja2Templates(directory="templates")

DEFAULT_STAFF_REDIRECT = "/children"
DEFAULT_LOGOUT_REDIRECT = "/staff/login"


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


def _active_staff_members(session: Session) -> list[Staff]:
    return session.exec(
        select(Staff)
        .where(Staff.status == StaffStatus.active)
        .order_by(Staff.id)
    ).all()


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
    role: str = Form(""),
    redirect_to: str = Form(DEFAULT_STAFF_REDIRECT),
    session: Session = Depends(get_session),
):
    target = _normalize_redirect(redirect_to, DEFAULT_STAFF_REDIRECT)

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
    )
    return response


@router.post("/logout")
def staff_logout(redirect_to: str = Form(DEFAULT_LOGOUT_REDIRECT)):
    target = _normalize_redirect(redirect_to, DEFAULT_LOGOUT_REDIRECT)
    response = RedirectResponse(url=target, status_code=303)
    clear_mock_staff_session(response)
    return response
