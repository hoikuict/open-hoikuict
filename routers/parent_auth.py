from __future__ import annotations

from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import (
    clear_parent_account_cookie,
    get_current_parent_account_id,
    get_current_staff_user,
    require_local_parent_auth,
    set_local_parent_session_cookie,
)
from database import get_session
from local_auth import AuthenticationFailed, LoginThrottled, PasswordPolicyError
from models import (
    AuthSession,
    ParentAccount,
    ParentRegistrationRequest,
    PasswordCredential,
    User,
)
from parent_auth import (
    MAX_VERIFICATION_ATTEMPTS,
    PARENT_LOGIN_FAILURE_MESSAGE,
    authenticate_parent,
    change_parent_password,
    complete_parent_action_password,
    complete_parent_registration,
    disable_parent_authentication,
    exchange_completion_token,
    exchange_invitation_token,
    exchange_parent_action_code,
    issue_parent_invitation,
    issue_parent_password_code,
    review_parent_registration,
    submit_parent_identity,
)
from security_config import secure_cookie_enabled
from template_utils import create_templates
from url_utils import safe_internal_redirect


router = APIRouter(
    tags=["parent-auth-local"], dependencies=[Depends(require_local_parent_auth)]
)
templates = create_templates()
REGISTRATION_COOKIE = "hoikuict_parent_registration"
REGISTRATION_STATUS_LABELS = {
    "invited": "招待済み",
    "pending_review": "確認待ち",
    "approved": "承認済み",
    "rejected": "却下",
    "completed": "登録完了",
    "expired": "期限切れ",
    "cancelled": "取消済み",
}


def _no_store(response):
    response.headers["Cache-Control"] = "private, no-store"
    response.headers["Referrer-Policy"] = "no-referrer"
    return response


def _render(request: Request, template: str, context: dict, status_code: int = 200):
    return _no_store(
        templates.TemplateResponse(
            request,
            template,
            {"request": request, "parent_portal_mode": True, **context},
            status_code=status_code,
        )
    )


def _render_staff(
    request: Request, template: str, context: dict, status_code: int = 200
):
    return _no_store(
        templates.TemplateResponse(
            request,
            template,
            {"request": request, "parent_portal_mode": False, **context},
            status_code=status_code,
        )
    )


def _set_registration_cookie(response, raw_state: str) -> None:
    response.set_cookie(
        REGISTRATION_COOKIE,
        raw_state,
        max_age=15 * 60,
        httponly=True,
        secure=secure_cookie_enabled(),
        samesite="lax",
        path="/parent-portal",
    )


def _clear_registration_cookie(response) -> None:
    response.delete_cookie(
        REGISTRATION_COOKIE,
        path="/parent-portal",
        secure=secure_cookie_enabled(),
        httponly=True,
        samesite="lax",
    )


@router.get("/parent-portal/login", response_class=HTMLResponse)
def parent_login_page(request: Request):
    requested_redirect = safe_internal_redirect(
        request.query_params.get("redirect", "/parent-portal/"),
        "/parent-portal/",
    )
    if not requested_redirect.startswith("/parent-portal/"):
        requested_redirect = "/parent-portal/"
    return _render(
        request,
        "parent_auth/login.html",
        {
            "login_id": "",
            "form_error": "",
            "password_changed": request.query_params.get("password_changed") == "1",
            "redirect_to": requested_redirect,
        },
    )


@router.post("/parent-portal/login")
def parent_login(
    request: Request,
    login_id: str = Form(...),
    password: str = Form(...),
    redirect_to: str = Form("/parent-portal/"),
    session: Session = Depends(get_session),
):
    try:
        result = authenticate_parent(
            session, login_id=login_id, password=password, request=request
        )
    except (AuthenticationFailed, LoginThrottled):
        return _render(
            request,
            "parent_auth/login.html",
            {
                "login_id": login_id,
                "form_error": PARENT_LOGIN_FAILURE_MESSAGE,
                "password_changed": False,
                "redirect_to": redirect_to,
            },
            400,
        )
    target = safe_internal_redirect(redirect_to, "/parent-portal/")
    if not target.startswith("/parent-portal/"):
        target = "/parent-portal/"
    response = RedirectResponse(target, status_code=303)
    set_local_parent_session_cookie(response, result.session_token)
    return _no_store(response)


@router.get("/parent-portal/register/invite", response_class=HTMLResponse)
def invitation_landing(request: Request):
    return _render(
        request,
        "parent_auth/token_exchange.html",
        {"verify_url": "/parent-portal/register/invite/verify", "heading": "初回登録"},
    )


@router.post("/parent-portal/register/invite/verify")
def invitation_verify(
    token: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        state = exchange_invitation_token(session, token)
    except AuthenticationFailed:
        return _no_store(
            RedirectResponse(
                "/parent-portal/register/status?state=invalid", status_code=303
            )
        )
    response = RedirectResponse("/parent-portal/register/identity", status_code=303)
    _set_registration_cookie(response, state)
    return _no_store(response)


@router.get("/parent-portal/register/identity", response_class=HTMLResponse)
def identity_page(request: Request):
    if not request.cookies.get(REGISTRATION_COOKIE):
        return _no_store(
            RedirectResponse(
                "/parent-portal/register/status?state=invalid", status_code=303
            )
        )
    return _render(request, "parent_auth/identity.html", {"form_error": ""})


@router.post("/parent-portal/register/identity")
def identity_submit(
    request: Request,
    guardian_name: str = Form(...),
    child_name: str = Form(...),
    child_birth_date: date = Form(...),
    session: Session = Depends(get_session),
):
    try:
        registration = submit_parent_identity(
            session,
            raw_state=request.cookies.get(REGISTRATION_COOKIE, ""),
            guardian_name=guardian_name,
            child_name=child_name,
            child_birth_date=child_birth_date,
        )
    except (AuthenticationFailed, ValueError):
        return _no_store(
            RedirectResponse(
                "/parent-portal/register/status?state=invalid", status_code=303
            )
        )
    if registration.status == "expired":
        response = RedirectResponse(
            "/parent-portal/register/status?state=attempts_exhausted", status_code=303
        )
        _clear_registration_cookie(response)
        return _no_store(response)
    if registration.matched_child_id is None:
        remaining = max(
            0, MAX_VERIFICATION_ATTEMPTS - registration.verification_attempt_count
        )
        return _render(
            request,
            "parent_auth/identity.html",
            {
                "form_error": f"入力内容を確認してください。あと{remaining}回入力できます。"
            },
            400,
        )
    response = RedirectResponse(
        "/parent-portal/register/status?state=submitted", status_code=303
    )
    _clear_registration_cookie(response)
    return _no_store(response)


@router.get("/parent-portal/register/status", response_class=HTMLResponse)
def registration_status(request: Request):
    state = request.query_params.get("state", "submitted")
    if state == "submitted":
        message = "園に確認を依頼しました"
    elif state == "attempts_exhausted":
        message = "入力回数の上限に達しました。施設へ再招待をご依頼ください。"
    else:
        message = "リンクの有効期限が切れているか、既に使用されています。施設へご連絡ください。"
    return _render(request, "parent_auth/status.html", {"message": message})


@router.get("/parent-portal/register/complete", response_class=HTMLResponse)
def completion_page(request: Request):
    has_state = bool(request.cookies.get(REGISTRATION_COOKIE))
    return _render(
        request,
        "parent_auth/complete.html" if has_state else "parent_auth/token_exchange.html",
        {
            "verify_url": "/parent-portal/register/complete/verify",
            "heading": "パスワード設定",
            "form_error": "",
        },
    )


@router.post("/parent-portal/register/complete/verify")
def completion_verify(token: str = Form(...), session: Session = Depends(get_session)):
    try:
        state = exchange_completion_token(session, token)
    except AuthenticationFailed:
        return _no_store(
            RedirectResponse(
                "/parent-portal/register/status?state=invalid", status_code=303
            )
        )
    response = RedirectResponse("/parent-portal/register/complete", status_code=303)
    _set_registration_cookie(response, state)
    return _no_store(response)


@router.post("/parent-portal/register/complete")
def completion_submit(
    request: Request,
    password: str = Form(...),
    password_confirmation: str = Form(...),
    session: Session = Depends(get_session),
):
    try:
        complete_parent_registration(
            session,
            raw_state=request.cookies.get(REGISTRATION_COOKIE, ""),
            password=password,
            password_confirmation=password_confirmation,
        )
    except (AuthenticationFailed, PasswordPolicyError, ValueError) as exc:
        return _render(
            request,
            "parent_auth/complete.html",
            {"form_error": str(exc), "verify_url": "", "heading": "パスワード設定"},
            400,
        )
    response = RedirectResponse(
        "/parent-portal/login?password_changed=1", status_code=303
    )
    _clear_registration_cookie(response)
    return _no_store(response)


def _action_page(
    request: Request, purpose: str, form_error: str = "", status_code: int = 200
):
    return _render(
        request,
        "parent_auth/action_code.html",
        {"purpose": purpose, "form_error": form_error},
        status_code,
    )


def _action_path(purpose: str) -> str:
    return "reset" if purpose == "parent_reset" else "activate"


def _verify_action_code(
    request: Request, session: Session, raw_code: str, purpose: str
):
    try:
        state = exchange_parent_action_code(session, raw_code, purpose, request)
    except AuthenticationFailed as exc:
        return _action_page(request, purpose, str(exc), 400)
    response = RedirectResponse(
        f"/parent-portal/{_action_path(purpose)}?verified=1", status_code=303
    )
    _set_registration_cookie(response, state)
    return _no_store(response)


def _complete_action_password(
    request: Request,
    session: Session,
    *,
    purpose: str,
    password: str,
    password_confirmation: str,
):
    try:
        complete_parent_action_password(
            session,
            raw_state=request.cookies.get(REGISTRATION_COOKIE, ""),
            purpose=purpose,
            password=password,
            password_confirmation=password_confirmation,
        )
    except AuthenticationFailed:
        response = RedirectResponse(
            "/parent-portal/register/status?state=invalid", status_code=303
        )
        _clear_registration_cookie(response)
        return _no_store(response)
    except (PasswordPolicyError, ValueError) as exc:
        return _render(
            request,
            "parent_auth/action_password.html",
            {"purpose": purpose, "form_error": str(exc)},
            400,
        )
    response = RedirectResponse(
        "/parent-portal/login?password_changed=1", status_code=303
    )
    _clear_registration_cookie(response)
    if purpose == "parent_reset":
        clear_parent_account_cookie(response, request)
    return _no_store(response)


@router.get("/parent-portal/reset", response_class=HTMLResponse)
def reset_page(request: Request):
    return _action_page(request, "parent_reset")


@router.get("/parent-portal/activate", response_class=HTMLResponse)
def activate_page(request: Request):
    return _action_page(request, "parent_activate")


@router.post("/parent-portal/reset/verify")
def reset_verify(
    request: Request,
    reset_code: str = Form(...),
    session: Session = Depends(get_session),
):
    return _verify_action_code(request, session, reset_code, "parent_reset")


@router.post("/parent-portal/activate/verify")
def activate_verify(
    request: Request,
    activation_code: str = Form(...),
    session: Session = Depends(get_session),
):
    return _verify_action_code(request, session, activation_code, "parent_activate")


@router.post("/parent-portal/reset/complete")
def reset_complete(
    request: Request,
    password: str = Form(...),
    password_confirmation: str = Form(...),
    session: Session = Depends(get_session),
):
    return _complete_action_password(
        request,
        session,
        purpose="parent_reset",
        password=password,
        password_confirmation=password_confirmation,
    )


@router.post("/parent-portal/activate/complete")
def activate_complete(
    request: Request,
    password: str = Form(...),
    password_confirmation: str = Form(...),
    session: Session = Depends(get_session),
):
    return _complete_action_password(
        request,
        session,
        purpose="parent_activate",
        password=password,
        password_confirmation=password_confirmation,
    )


@router.get("/parent-portal/account/password", response_class=HTMLResponse)
def password_page(request: Request):
    if not get_current_parent_account_id(request):
        return RedirectResponse("/parent-portal/login", status_code=303)
    return _render(
        request,
        "parent_auth/change_password.html",
        {"current_parent_user": True, "form_error": ""},
    )


@router.post("/parent-portal/account/password")
def password_change(
    request: Request,
    current_password: str = Form(...),
    new_password: str = Form(...),
    password_confirmation: str = Form(...),
    session: Session = Depends(get_session),
):
    account_id = get_current_parent_account_id(request)
    account = session.get(ParentAccount, account_id) if account_id else None
    if not account:
        return RedirectResponse("/parent-portal/login", status_code=303)
    try:
        raw_token = change_parent_password(
            session,
            account=account,
            current_password=current_password,
            new_password=new_password,
            password_confirmation=password_confirmation,
        )
    except (AuthenticationFailed, PasswordPolicyError, ValueError) as exc:
        return _render(
            request,
            "parent_auth/change_password.html",
            {"current_parent_user": account, "form_error": str(exc)},
            400,
        )
    response = RedirectResponse(
        "/parent-portal/?notice=password_changed", status_code=303
    )
    set_local_parent_session_cookie(response, raw_token)
    return _no_store(response)


def _admin_actor(session: Session, current_user) -> User:
    if not current_user.is_admin or current_user.user_id is None:
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    actor = session.get(User, current_user.user_id)
    if actor is None or not actor.is_active or actor.staff_role != "admin":
        raise HTTPException(status_code=403, detail="管理者権限が必要です")
    return actor


def _load_admin_account(session: Session, account_id: int) -> ParentAccount:
    account = session.get(ParentAccount, account_id)
    if not account:
        raise HTTPException(status_code=404, detail="保護者アカウントが見つかりません")
    return account


def _issue_admin_action_code(
    request: Request,
    session: Session,
    current_user,
    *,
    account_id: int,
    reason: str,
    action: str,
):
    actor = _admin_actor(session, current_user)
    account = _load_admin_account(session, account_id)
    try:
        code = issue_parent_password_code(
            session,
            account=account,
            actor_user=actor,
            reason=reason,
            action=action,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _render_staff(
        request,
        "parent_auth/action_code_display.html",
        {"current_user": current_user, "account": account, "action_code": code},
    )


@router.get("/parent-accounts/{account_id}/authentication", response_class=HTMLResponse)
def admin_parent_auth_page(
    request: Request,
    account_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = _admin_actor(session, current_user)
    account = _load_admin_account(session, account_id)
    credential = session.exec(
        select(PasswordCredential).where(
            PasswordCredential.parent_account_id == account_id
        )
    ).first()
    registrations = session.exec(
        select(ParentRegistrationRequest)
        .where(ParentRegistrationRequest.parent_account_id == account_id)
        .order_by(ParentRegistrationRequest.created_at.desc())
    ).all()
    active_session_count = len(
        session.exec(
            select(AuthSession).where(
                AuthSession.parent_account_id == account_id,
                AuthSession.revoked_at.is_(None),
            )
        ).all()
    )
    return _render_staff(
        request,
        "parent_auth/admin.html",
        {
            "current_user": current_user,
            "actor": actor,
            "account": account,
            "credential": credential,
            "registrations": registrations,
            "active_session_count": active_session_count,
            "registration_status_labels": REGISTRATION_STATUS_LABELS,
            "action_code": "",
            "form_error": "",
        },
    )


@router.post("/parent-accounts/{account_id}/authentication/invite")
def admin_invite(
    account_id: int,
    reason: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = _admin_actor(session, current_user)
    account = _load_admin_account(session, account_id)
    try:
        issue_parent_invitation(
            session, account=account, actor_user=actor, reason=reason
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(
        f"/parent-accounts/{account_id}/authentication", status_code=303
    )


@router.post(
    "/parent-accounts/{account_id}/authentication/registrations/{registration_id}/review"
)
def admin_review(
    account_id: int,
    registration_id: UUID,
    decision: str = Form(...),
    reason: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = _admin_actor(session, current_user)
    registration = session.get(ParentRegistrationRequest, registration_id)
    if not registration or registration.parent_account_id != account_id:
        raise HTTPException(status_code=404, detail="登録申請が見つかりません")
    try:
        review_parent_registration(
            session,
            registration=registration,
            actor_user=actor,
            approve=decision == "approve",
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(
        f"/parent-accounts/{account_id}/authentication", status_code=303
    )


@router.post("/parent-accounts/{account_id}/authentication/reset")
def admin_reset_code(
    request: Request,
    account_id: int,
    reason: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    return _issue_admin_action_code(
        request,
        session,
        current_user,
        account_id=account_id,
        reason=reason,
        action="parent_reset",
    )


@router.post("/parent-accounts/{account_id}/authentication/activate")
def admin_activation_code(
    request: Request,
    account_id: int,
    reason: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    return _issue_admin_action_code(
        request,
        session,
        current_user,
        account_id=account_id,
        reason=reason,
        action="parent_activate",
    )


@router.post("/parent-accounts/{account_id}/authentication/disable")
def admin_disable(
    account_id: int,
    reason: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = _admin_actor(session, current_user)
    account = _load_admin_account(session, account_id)
    try:
        disable_parent_authentication(session, account, actor, reason)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(
        f"/parent-accounts/{account_id}/authentication", status_code=303
    )
