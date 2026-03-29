from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Session, select

from auth import clear_mock_staff_session, get_current_staff_user, MOCK_ROLE_COOKIE, Role, set_mock_staff_session
from database import get_session
from models import Staff, StaffStatus


router = APIRouter(prefix="/staff", tags=["staff-auth"])
templates = Jinja2Templates(directory="templates")

DEFAULT_STAFF_REDIRECT = "/children"
DEFAULT_LOGOUT_REDIRECT = "/staff/login"
COOKIE_MAX_AGE = 60 * 60 * 24


def _normalize_redirect(redirect_to: str | None, fallback: str) -> str:
    if redirect_to and redirect_to.startswith("/") and not redirect_to.startswith("//"):
        return redirect_to
    return fallback


@router.get("/login", response_class=HTMLResponse)
def staff_login_page(
    request: Request,
    redirect: str = DEFAULT_STAFF_REDIRECT,
    current_user=Depends(get_current_staff_user),
):
    return templates.TemplateResponse(
        request,
        "staff_auth/login.html",
        {
            "current_user": current_user,
            "redirect_to": _normalize_redirect(redirect, DEFAULT_STAFF_REDIRECT),
            "available_roles": [Role.CAN_EDIT, Role.ADMIN, Role.VIEW_ONLY],
        },
    )


@router.post("/login")
def staff_login(
    role: str = Form(Role.CAN_EDIT.value),
    redirect_to: str = Form(DEFAULT_STAFF_REDIRECT),
    session: Session = Depends(get_session),
):
    target = _normalize_redirect(redirect_to, DEFAULT_STAFF_REDIRECT)
    selected_role = Role(role) if role in {item.value for item in Role} else Role.CAN_EDIT
    staff = session.exec(
        select(Staff)
        .where(
            Staff.role == selected_role,
            Staff.status == StaffStatus.active,
        )
        .order_by(Staff.id)
    ).first()

    response = RedirectResponse(url=target, status_code=303)
    if staff:
        set_mock_staff_session(
            response,
            staff_id=staff.id,
            name=staff.display_name,
            role=staff.role,
            primary_classroom_id=staff.primary_classroom_id,
            employment_type=staff.employment_type.value,
        )
    else:
        response.set_cookie(MOCK_ROLE_COOKIE, selected_role.value, max_age=COOKIE_MAX_AGE)
    return response


@router.post("/logout")
def staff_logout(redirect_to: str = Form(DEFAULT_LOGOUT_REDIRECT)):
    target = _normalize_redirect(redirect_to, DEFAULT_LOGOUT_REDIRECT)
    response = RedirectResponse(url=target, status_code=303)
    clear_mock_staff_session(response)
    return response
