from datetime import date
from urllib.parse import urlencode
from uuid import UUID

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import (
    Role,
    clear_staff_cookies,
    get_current_staff_user,
    get_optional_current_staff_user,
    require_admin,
    require_mock_staff_auth,
    set_staff_cookies,
)
from database import get_session
from models import (
    USER_SOURCE_EXTERNAL,
    USER_SOURCE_IMPORT,
    USER_SOURCE_LOCAL_SAMPLE,
    USER_SOURCE_MANUAL,
    USER_SOURCE_SYSTEM,
    USER_SOURCE_WEB_DEMO,
    Classroom,
    StaffClassroomAssignment,
    StaffClassroomAssignmentRole,
    StaffPermissionChangeLog,
    User,
)
from staff_permissions import (
    STAFF_PERMISSION_DEFINITIONS,
    add_permission_change_logs,
    require_live_admin,
)
from staff_user_service import list_active_staff_users
from time_utils import local_today, utc_now
from url_utils import safe_internal_redirect


router = APIRouter(prefix="/staff", tags=["staff-auth"])
mock_login_router = APIRouter(prefix="/staff", tags=["staff-auth-mock"])
from template_utils import create_templates

templates = create_templates()

DEFAULT_STAFF_REDIRECT = "/"
DEFAULT_LOGOUT_REDIRECT = "/"
STAFF_ROLE_OPTIONS = [
    ("admin", "管理者"),
    ("can_edit", "編集可"),
    ("view_only", "閲覧のみ"),
]
STAFF_SOURCE_FILTER_OPTIONS = [
    ("all", "すべて"),
    (USER_SOURCE_MANUAL, "手動追加"),
    (USER_SOURCE_LOCAL_SAMPLE, "ローカルサンプル"),
    (USER_SOURCE_WEB_DEMO, "WEB公開デモ"),
    (USER_SOURCE_IMPORT, "インポート"),
    (USER_SOURCE_EXTERNAL, "外部連携"),
    (USER_SOURCE_SYSTEM, "システム"),
]
STAFF_SOURCE_FILTER_VALUES = {value for value, _label in STAFF_SOURCE_FILTER_OPTIONS}


def _role_from_user(user: User) -> Role:
    if user.staff_role == "admin":
        return Role.ADMIN
    if user.staff_role == "view_only":
        return Role.VIEW_ONLY
    return Role.CAN_EDIT


def _login_redirect_for_user(user: User, requested_redirect: str) -> str:
    """Return a page the selected staff member is allowed to open."""
    target = safe_internal_redirect(requested_redirect, DEFAULT_STAFF_REDIRECT)
    if user.staff_role != "admin" and target.startswith("/staff/users"):
        return DEFAULT_STAFF_REDIRECT
    return target


def _normalize_staff_role(raw_role: str) -> str:
    allowed_roles = {role for role, _label in STAFF_ROLE_OPTIONS}
    return raw_role if raw_role in allowed_roles else "can_edit"


def _checked(raw_value: str | None) -> bool:
    return raw_value in {"1", "true", "on", "yes"}


def _normalize_source_filter(raw_source: str) -> str:
    return raw_source if raw_source in STAFF_SOURCE_FILTER_VALUES else "all"


def _permissions_redirect(**params: str) -> RedirectResponse:
    query = urlencode({key: value for key, value in params.items() if value})
    suffix = f"?{query}" if query else ""
    return RedirectResponse(url=f"/staff/permissions{suffix}", status_code=303)


def _staff_source_counts(session: Session) -> dict[str, int]:
    counts = {"all": 0}
    for source in session.exec(select(User.provisioning_source)).all():
        key = source or USER_SOURCE_MANUAL
        counts[key] = counts.get(key, 0) + 1
        counts["all"] += 1
    return counts


def _default_staff_source_filter(session: Session) -> str:
    has_web_demo = session.exec(
        select(User.id).where(User.provisioning_source == USER_SOURCE_WEB_DEMO)
    ).first()
    return USER_SOURCE_WEB_DEMO if has_web_demo else "all"


def _staff_form_data(
    user: User | None = None,
    *,
    display_name: str = "",
    email: str = "",
    staff_role: str = "can_edit",
    can_manage_child_records: bool = False,
    staff_sort_order: int = 100,
    is_active: bool = True,
) -> dict[str, object]:
    if user:
        return {
            "user_id": str(user.id),
            "display_name": user.display_name,
            "email": user.email,
            "staff_role": user.staff_role,
            "can_manage_child_records": user.can_manage_child_records_effective,
            "staff_sort_order": user.staff_sort_order,
            "is_active": user.is_active,
        }
    return {
        "user_id": "",
        "display_name": display_name,
        "email": email,
        "staff_role": staff_role,
        "can_manage_child_records": can_manage_child_records,
        "staff_sort_order": staff_sort_order,
        "is_active": is_active,
    }


def _active_admin_count(session: Session) -> int:
    admins = session.exec(
        select(User).where(User.is_active.is_(True), User.staff_role == "admin")
    ).all()
    return len(admins)


def _role_change_error(
    *,
    session: Session,
    target_user: User | None,
    current_user,
    next_role: str,
    next_is_active: bool,
) -> str:
    if target_user is None:
        return ""

    changing_self = (
        current_user
        and current_user.user_id is not None
        and target_user.id == current_user.user_id
    )
    removes_admin = target_user.staff_role == "admin" and (
        next_role != "admin" or not next_is_active
    )
    if changing_self and removes_admin:
        return "自分自身の管理者権限はこの画面では外せません。"
    if target_user.is_active and removes_admin and _active_admin_count(session) <= 1:
        return "最後の管理者は無効化または権限変更できません。"
    return ""


def _render_staff_user_form(
    request: Request,
    *,
    current_user,
    action_url: str,
    submit_label: str,
    form_data: dict[str, object],
    form_error: str = "",
):
    return templates.TemplateResponse(
        request,
        "staff_auth/user_form.html",
        {
            "request": request,
            "current_user": current_user,
            "action_url": action_url,
            "submit_label": submit_label,
            "form_data": form_data,
            "form_error": form_error,
            "staff_role_options": STAFF_ROLE_OPTIONS,
            "is_new": action_url == "/staff/users",
        },
    )


@mock_login_router.get(
    "/login",
    response_class=HTMLResponse,
    dependencies=[Depends(require_mock_staff_auth)],
)
def staff_login_page(
    request: Request,
    redirect: str = DEFAULT_STAFF_REDIRECT,
    current_user=Depends(get_optional_current_staff_user),
    session: Session = Depends(get_session),
):
    target = safe_internal_redirect(redirect, DEFAULT_STAFF_REDIRECT)
    users = list_active_staff_users(session)
    return templates.TemplateResponse(
        request,
        "staff_auth/login.html",
        {
            "request": request,
            "current_user": current_user,
            "redirect_to": target,
            "users": users,
        },
    )


@mock_login_router.post("/login", dependencies=[Depends(require_mock_staff_auth)])
def staff_login(
    user_id: str = Form(""),
    redirect_to: str = Form(DEFAULT_STAFF_REDIRECT),
    session: Session = Depends(get_session),
):
    try:
        user_uuid = UUID(str(user_id).strip())
    except (TypeError, ValueError):
        user_uuid = UUID(int=0)
    user = session.get(User, user_uuid)
    if user is None or not user.is_active:
        return RedirectResponse(url="/staff/login", status_code=303)

    target = _login_redirect_for_user(user, redirect_to)
    response = RedirectResponse(url=target, status_code=303)
    set_staff_cookies(
        response,
        role=_role_from_user(user),
        name=user.display_name,
        user_id=str(user.id),
        can_manage_child_records=user.can_manage_child_records_effective,
    )
    return response


@router.post("/logout")
def staff_logout(redirect_to: str = Form(DEFAULT_LOGOUT_REDIRECT)):
    target = safe_internal_redirect(redirect_to, DEFAULT_LOGOUT_REDIRECT)
    response = RedirectResponse(url=target, status_code=303)
    clear_staff_cookies(response)
    return response


@router.get("/users", response_class=HTMLResponse)
def staff_user_list(
    request: Request,
    source: str = "",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    selected_source = _normalize_source_filter(source) if source else _default_staff_source_filter(session)
    statement = select(User)
    if selected_source != "all":
        statement = statement.where(User.provisioning_source == selected_source)
    users = session.exec(
        statement.order_by(User.staff_sort_order, User.display_name, User.email)
    ).all()
    return templates.TemplateResponse(
        request,
        "staff_auth/users.html",
        {
            "request": request,
            "current_user": current_user,
            "users": users,
            "source_filter": selected_source,
            "source_filter_options": STAFF_SOURCE_FILTER_OPTIONS,
            "source_counts": _staff_source_counts(session),
        },
    )


@router.get("/permissions", response_class=HTMLResponse)
def staff_permissions_page(
    request: Request,
    q: str = "",
    role: str = "",
    status: str = "active",
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_live_admin(session, current_user)
    selected_role = role if role in {value for value, _label in STAFF_ROLE_OPTIONS} else ""
    selected_status = status if status in {"all", "active", "inactive"} else "active"
    query = q.strip().casefold()

    users = session.exec(
        select(User).order_by(User.staff_sort_order, User.display_name, User.email)
    ).all()
    if selected_status == "active":
        users = [user for user in users if user.is_active]
    elif selected_status == "inactive":
        users = [user for user in users if not user.is_active]
    if selected_role:
        users = [user for user in users if user.staff_role == selected_role]
    if query:
        users = [
            user
            for user in users
            if query in user.display_name.casefold() or query in user.email.casefold()
        ]

    latest_log_by_user: dict[UUID, StaffPermissionChangeLog] = {}
    logs = session.exec(
        select(StaffPermissionChangeLog).order_by(
            StaffPermissionChangeLog.changed_at.desc(),
            StaffPermissionChangeLog.id.desc(),
        )
    ).all()
    for log in logs:
        latest_log_by_user.setdefault(log.target_user_id, log)

    rows = [
        {"user": user, "latest_log": latest_log_by_user.get(user.id)}
        for user in users
    ]
    return templates.TemplateResponse(
        request,
        "staff_auth/permissions.html",
        {
            "request": request,
            "current_user": current_user,
            "rows": rows,
            "permission_definitions": STAFF_PERMISSION_DEFINITIONS,
            "staff_role_options": STAFF_ROLE_OPTIONS,
            "filters": {"q": q.strip(), "role": selected_role, "status": selected_status},
            "message": request.query_params.get("message", ""),
            "error": request.query_params.get("error", ""),
        },
    )


@router.post("/permissions/{user_id}")
def update_staff_permissions(
    user_id: UUID,
    staff_role: str = Form("can_edit"),
    can_manage_child_records: str = Form(""),
    can_manage_billing_accounts: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = require_live_admin(session, current_user)
    target_user = session.get(User, user_id)
    if target_user is None:
        return _permissions_redirect(error="対象の職員が見つかりません。")

    next_role = _normalize_staff_role(staff_role)
    role_error = _role_change_error(
        session=session,
        target_user=target_user,
        current_user=current_user,
        next_role=next_role,
        next_is_active=target_user.is_active,
    )
    if role_error:
        return _permissions_redirect(error=role_error)

    if next_role == "admin":
        next_can_manage_child_records = target_user.can_manage_child_records
        next_can_manage_billing_accounts = target_user.can_manage_billing_accounts
    elif next_role == "can_edit" and target_user.staff_role != "admin":
        next_can_manage_child_records = _checked(can_manage_child_records)
        next_can_manage_billing_accounts = _checked(can_manage_billing_accounts)
    else:
        next_can_manage_child_records = False
        next_can_manage_billing_accounts = False

    changes = [
        ("staff_role", target_user.staff_role, next_role),
        (
            "can_manage_child_records",
            target_user.can_manage_child_records,
            next_can_manage_child_records,
        ),
        (
            "can_manage_billing_accounts",
            target_user.can_manage_billing_accounts,
            next_can_manage_billing_accounts,
        ),
    ]
    add_permission_change_logs(
        session,
        target_user=target_user,
        actor=actor,
        changes=changes,
    )
    target_user.staff_role = next_role
    target_user.is_calendar_admin = next_role == "admin"
    target_user.can_manage_child_records = next_can_manage_child_records
    target_user.can_manage_billing_accounts = next_can_manage_billing_accounts
    target_user.updated_at = utc_now()
    session.add(target_user)
    session.commit()
    return _permissions_redirect(message=f"{target_user.display_name}さんの権限を更新しました。")


@router.get("/users/new", response_class=HTMLResponse)
def new_staff_user_form(
    request: Request,
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    return _render_staff_user_form(
        request,
        current_user=current_user,
        action_url="/staff/users",
        submit_label="職員を追加",
        form_data=_staff_form_data(),
    )


@router.post("/users")
def create_staff_user(
    request: Request,
    display_name: str = Form(...),
    email: str = Form(...),
    staff_role: str = Form("can_edit"),
    can_manage_child_records: str = Form(""),
    staff_sort_order: int = Form(100),
    is_active: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    next_role = _normalize_staff_role(staff_role)
    next_can_manage_child_records = False
    next_is_active = _checked(is_active)
    form_data = _staff_form_data(
        display_name=display_name,
        email=email,
        staff_role=next_role,
        can_manage_child_records=next_can_manage_child_records,
        staff_sort_order=staff_sort_order,
        is_active=next_is_active,
    )
    if session.exec(select(User).where(User.email == email.strip())).first():
        return _render_staff_user_form(
            request,
            current_user=current_user,
            action_url="/staff/users",
            submit_label="職員を追加",
            form_data=form_data,
            form_error="このメールアドレスはすでに登録されています。",
        )

    user = User(
        display_name=display_name.strip(),
        email=email.strip(),
        staff_role=next_role,
        can_manage_child_records=next_can_manage_child_records,
        provisioning_source=USER_SOURCE_MANUAL,
        staff_sort_order=staff_sort_order,
        is_calendar_admin=next_role == "admin",
        is_active=next_is_active,
    )
    session.add(user)
    session.commit()
    return RedirectResponse(url="/staff/users", status_code=303)


@router.get("/users/{user_id}/edit", response_class=HTMLResponse)
def edit_staff_user_form(
    request: Request,
    user_id: UUID,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/staff/users", status_code=303)
    return _render_staff_user_form(
        request,
        current_user=current_user,
        action_url=f"/staff/users/{user_id}/edit",
        submit_label="職員を更新",
        form_data=_staff_form_data(user),
    )


@router.post("/users/{user_id}/edit")
def update_staff_user(
    request: Request,
    user_id: UUID,
    display_name: str = Form(...),
    email: str = Form(...),
    staff_sort_order: int = Form(100),
    is_active: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/staff/users", status_code=303)

    next_role = user.staff_role
    next_can_manage_child_records = user.can_manage_child_records
    next_is_active = _checked(is_active)
    form_data = _staff_form_data(
        display_name=display_name,
        email=email,
        staff_role=next_role,
        can_manage_child_records=next_can_manage_child_records,
        staff_sort_order=staff_sort_order,
        is_active=next_is_active,
    )

    duplicate = session.exec(
        select(User).where(User.email == email.strip(), User.id != user_id)
    ).first()
    if duplicate:
        return _render_staff_user_form(
            request,
            current_user=current_user,
            action_url=f"/staff/users/{user_id}/edit",
            submit_label="職員を更新",
            form_data=form_data,
            form_error="このメールアドレスは別の職員で登録されています。",
        )

    role_error = _role_change_error(
        session=session,
        target_user=user,
        current_user=current_user,
        next_role=next_role,
        next_is_active=next_is_active,
    )
    if role_error:
        return _render_staff_user_form(
            request,
            current_user=current_user,
            action_url=f"/staff/users/{user_id}/edit",
            submit_label="職員を更新",
            form_data=form_data,
            form_error=role_error,
        )

    user.display_name = display_name.strip()
    user.email = email.strip()
    user.staff_role = next_role
    user.can_manage_child_records = next_can_manage_child_records
    user.staff_sort_order = staff_sort_order
    user.is_calendar_admin = next_role == "admin"
    user.is_active = next_is_active
    user.updated_at = utc_now()
    session.add(user)
    session.commit()
    return RedirectResponse(url="/staff/users", status_code=303)


def _parse_assignment_date(raw: str, *, required: bool) -> date | None:
    value = raw.strip()
    if not value:
        if required:
            raise ValueError("日付を入力してください。")
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("日付は YYYY-MM-DD 形式で入力してください。") from exc


def _assignment_form_context(
    request: Request,
    *,
    current_user,
    user: User,
    session: Session,
    form_error: str = "",
    form_data: dict[str, object] | None = None,
):
    assignments = session.exec(
        select(StaffClassroomAssignment)
        .where(StaffClassroomAssignment.staff_user_id == user.id)
        .order_by(
            StaffClassroomAssignment.starts_on.desc(),
            StaffClassroomAssignment.display_order,
            StaffClassroomAssignment.id.desc(),
        )
    ).all()
    classrooms = session.exec(
        select(Classroom).order_by(Classroom.display_order, Classroom.id)
    ).all()
    classroom_by_id = {item.id: item for item in classrooms}
    assignment_rows = [
        {"assignment": item, "classroom": classroom_by_id.get(item.classroom_id)}
        for item in assignments
    ]
    default_data = {
        "classroom_id": "",
        "assignment_role": StaffClassroomAssignmentRole.primary.value,
        "starts_on": local_today().isoformat(),
        "ends_on": "",
        "is_primary": False,
        "display_order": 100,
    }
    return templates.TemplateResponse(
        request,
        "staff_auth/classroom_assignments.html",
        {
            "request": request,
            "current_user": current_user,
            "user": user,
            "classrooms": classrooms,
            "assignment_rows": assignment_rows,
            "assignment_role_options": [
                (item.value, item.label) for item in StaffClassroomAssignmentRole
            ],
            "today": local_today(),
            "form_error": form_error,
            "form_data": {**default_data, **(form_data or {})},
        },
        status_code=400 if form_error else 200,
    )


@router.get("/users/{user_id}/classrooms", response_class=HTMLResponse)
def staff_classroom_assignments(
    request: Request,
    user_id: UUID,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    user = session.get(User, user_id)
    if user is None:
        return RedirectResponse(url="/staff/users", status_code=303)
    return _assignment_form_context(
        request,
        current_user=current_user,
        user=user,
        session=session,
    )


@router.post("/users/{user_id}/classrooms")
def add_staff_classroom_assignment(
    request: Request,
    user_id: UUID,
    classroom_id: int = Form(...),
    assignment_role: str = Form(StaffClassroomAssignmentRole.primary.value),
    starts_on: str = Form(...),
    ends_on: str = Form(""),
    is_primary: str = Form(""),
    display_order: int = Form(100),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    user = session.get(User, user_id)
    classroom = session.get(Classroom, classroom_id)
    if user is None or classroom is None:
        return RedirectResponse(url="/staff/users", status_code=303)

    form_data = {
        "classroom_id": str(classroom_id),
        "assignment_role": assignment_role,
        "starts_on": starts_on,
        "ends_on": ends_on,
        "is_primary": _checked(is_primary),
        "display_order": display_order,
    }
    try:
        start_date = _parse_assignment_date(starts_on, required=True)
        end_date = _parse_assignment_date(ends_on, required=False)
        role = StaffClassroomAssignmentRole(assignment_role)
        if end_date is not None and start_date is not None and end_date < start_date:
            raise ValueError("終了日は開始日以降にしてください。")
    except (ValueError, TypeError) as exc:
        message = str(exc) if str(exc) else "担当区分が不正です。"
        return _assignment_form_context(
            request,
            current_user=current_user,
            user=user,
            session=session,
            form_error=message,
            form_data=form_data,
        )

    existing_items = session.exec(
        select(StaffClassroomAssignment).where(
            StaffClassroomAssignment.staff_user_id == user.id,
            StaffClassroomAssignment.classroom_id == classroom_id,
        )
    ).all()
    for item in existing_items:
        existing_end = item.ends_on or date.max
        new_end = end_date or date.max
        if start_date <= existing_end and item.starts_on <= new_end:
            return _assignment_form_context(
                request,
                current_user=current_user,
                user=user,
                session=session,
                form_error=(
                    "この職員には、同じクラスで担当期間が重複しています。"
                    "同じクラスへ複数の職員を置く場合は、職員一覧から別の職員を選んで追加してください。"
                ),
                form_data=form_data,
            )

    assignment = StaffClassroomAssignment(
        staff_user_id=user.id,
        classroom_id=classroom_id,
        assignment_role=role,
        starts_on=start_date,
        ends_on=end_date,
        is_primary=_checked(is_primary),
        display_order=display_order,
    )
    session.add(assignment)
    session.commit()
    return RedirectResponse(url=f"/staff/users/{user.id}/classrooms", status_code=303)


@router.post("/users/{user_id}/classrooms/{assignment_id}/end")
def end_staff_classroom_assignment(
    request: Request,
    user_id: UUID,
    assignment_id: int,
    ends_on: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    user = session.get(User, user_id)
    assignment = session.get(StaffClassroomAssignment, assignment_id)
    if user is None or assignment is None or assignment.staff_user_id != user.id:
        return RedirectResponse(url="/staff/users", status_code=303)
    try:
        end_date = _parse_assignment_date(ends_on, required=True)
        if end_date is None or end_date < assignment.starts_on:
            raise ValueError("終了日は開始日以降にしてください。")
    except ValueError as exc:
        return _assignment_form_context(
            request,
            current_user=current_user,
            user=user,
            session=session,
            form_error=str(exc),
        )
    assignment.ends_on = end_date
    assignment.updated_at = utc_now()
    session.add(assignment)
    session.commit()
    return RedirectResponse(url=f"/staff/users/{user.id}/classrooms", status_code=303)
