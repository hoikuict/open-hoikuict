from __future__ import annotations

from datetime import date
import time
from uuid import UUID

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.exc import IntegrityError
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
    ParentEnrollment,
    ParentMailDelivery,
    ParentPublicRegistration,
    ParentPublicRegistrationSettings,
    ParentRegistrationRequest,
    PasswordCredential,
    User,
)
from parent_auth import (
    MAX_VERIFICATION_ATTEMPTS,
    PARENT_LOGIN_FAILURE_MESSAGE,
    authenticate_parent,
    change_parent_login_id_by_admin,
    change_parent_password,
    complete_parent_action_password,
    complete_parent_registration,
    disable_parent_authentication,
    exchange_completion_token,
    exchange_invitation_token,
    exchange_parent_action_code,
    issue_parent_invitation,
    issue_parent_password_code,
    parent_invitation_requirements,
    review_parent_registration,
    registration_token_from_input,
    submit_parent_identity,
)
from security_config import secure_cookie_enabled
from template_utils import create_templates
from url_utils import safe_internal_redirect
from parent_enrollment import (
    CHILD_FIELDS, GUARDIAN_FIELDS, FIELD_LABELS, enrollment_state, enrollment_target,
    latest_enrollment, prepare_enrollment, submit_enrollment,
)
from family_support import validate_parent_contact_email
from parent_public_registration import (
    InvalidRegistrationEmail, RegistrationLimited, limit_public_network, public_registration_enabled,
    public_registration_targets, public_registration_url, request_public_registration,
)


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


def _set_registration_cookie(response, raw_state: str, *, max_age: int = 15 * 60) -> None:
    response.set_cookie(
        REGISTRATION_COOKIE,
        raw_state,
        max_age=max_age,
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
    return _registration_exchange_page(request, "invite")


@router.get("/parent-portal/register/apply", response_class=HTMLResponse)
def public_registration_page(request: Request, session: Session = Depends(get_session)):
    return _render(request, "parent_auth/public_registration.html", {
        "accepting": public_registration_enabled(session), "email": "", "form_error": "",
    })


@router.post("/parent-portal/register/apply")
def public_registration_request(request: Request, email: str = Form(""),
                                session: Session = Depends(get_session)):
    if not public_registration_enabled(session):
        return _render(request, "parent_auth/public_registration.html", {
            "accepting": False, "email": "", "form_error": "",
        }, 403)
    try:
        limit_public_network(session, request)
    except RegistrationLimited as exc:
        response = _render(request, "parent_auth/public_registration.html", {
            "accepting": True, "email": "", "form_error": "この接続からの申請が続いたため、一時的に受付を制限しています。15分ほどあけてお試しください。",
        }, 429)
        response.headers["Retry-After"] = str(exc.retry_after)
        return response
    started = time.monotonic()
    try:
        request_public_registration(session, email)
    except InvalidRegistrationEmail:
        session.rollback()
        return _render(request, "parent_auth/public_registration.html", {
            "accepting": True, "email": email[:255], "form_error": "受信できるメールアドレスを入力してください",
        }, 400)
    except (IntegrityError, ValueError):
        # A simultaneous request or an existing login ID gets the same response.
        session.rollback()
    finally:
        time.sleep(max(0, 0.25 - (time.monotonic() - started)))
    return _render(request, "parent_auth/public_registration_sent.html", {})


def _registration_exchange_page(request: Request, purpose: str, *, error="", status_code=200):
    return _render(
        request,
        "parent_auth/token_exchange.html",
        {
            "verify_url": f"/parent-portal/register/{purpose}/verify",
            "heading": "初回登録" if purpose == "invite" else "パスワード設定",
            "form_error": error,
        },
        status_code,
    )


def _registration_exchange_error(request: Request, purpose: str):
    return _registration_exchange_page(
        request, purpose, status_code=400,
        error="登録コードを確認できませんでした。最新のメールのコードまたはリンクを貼り付けてください。"
              "24時間を過ぎた場合や、既に使用した場合は、施設へ再送をご依頼ください。",
    )


@router.post("/parent-portal/register/invite/verify")
def invitation_verify(
    request: Request,
    token: str = Form(""),
    session: Session = Depends(get_session),
):
    try:
        state = exchange_invitation_token(session, registration_token_from_input(token, "invite"))
    except AuthenticationFailed:
        return _registration_exchange_error(request, "invite")
    response = RedirectResponse("/parent-portal/register/identity", status_code=303)
    from parent_auth import token_hash
    from models import ParentRegistrationSession
    registration_state = session.get(ParentRegistrationSession, token_hash(state))
    is_enrollment = session.get(ParentEnrollment, registration_state.registration_request_id) is not None
    _set_registration_cookie(response, state, max_age=2 * 60 * 60 if is_enrollment else 15 * 60)
    return _no_store(response)


@router.get("/parent-portal/register/identity", response_class=HTMLResponse)
def identity_page(request: Request, session: Session = Depends(get_session)):
    if not request.cookies.get(REGISTRATION_COOKIE):
        return _no_store(
            RedirectResponse(
                "/parent-portal/register/status?state=invalid", status_code=303
            )
        )
    from parent_auth import _get_registration_session
    try:
        state = _get_registration_session(session, request.cookies[REGISTRATION_COOKIE], "identity")
        if session.get(ParentEnrollment, state.registration_request_id):
            _, _, enrollment, _ = enrollment_state(session, request.cookies[REGISTRATION_COOKIE])
            parts = enrollment.child_name.split(maxsplit=1)
            values = {"last_name": parts[0], "first_name": parts[1]} if len(parts) == 2 else {}
            is_public = session.get(ParentPublicRegistration, state.registration_request_id) is not None
            if is_public:
                values = {}
            return _enrollment_form(request, enrollment, values, public_application=is_public)
    except AuthenticationFailed:
        return _no_store(RedirectResponse("/parent-portal/register/status?state=invalid", status_code=303))
    return _render(request, "parent_auth/identity.html", {"form_error": ""})


def _enrollment_form(request, enrollment, values, error="", status_code=200, *, public_application=False):
    return _render(request, "parent_auth/enrollment.html", {
        "enrollment": enrollment, "values": values, "form_error": error,
        "child_fields": CHILD_FIELDS, "guardian_fields": GUARDIAN_FIELDS,
        "public_application": public_application,
    }, status_code)


@router.post("/parent-portal/register/enrollment")
async def enrollment_submit(request: Request, session: Session = Depends(get_session)):
    raw_state = request.cookies.get(REGISTRATION_COOKIE, "")
    try:
        _, _, enrollment, _ = enrollment_state(session, raw_state)
        form = await request.form()
        values = {key: str(form.get(key, "")) for key in FIELD_LABELS}
        submit_enrollment(session, raw_state, values)
    except AuthenticationFailed:
        return _no_store(RedirectResponse("/parent-portal/register/status?state=invalid", status_code=303))
    except ValueError as exc:
        return _enrollment_form(request, enrollment, values, str(exc), 400, public_application=
                                session.get(ParentPublicRegistration, enrollment.registration_request_id) is not None)
    response = _render(request, "parent_auth/enrollment_submitted.html", {})
    _clear_registration_cookie(response)
    return response


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
def completion_page(request: Request, session: Session = Depends(get_session)):
    from parent_auth import _get_registration_session

    has_state = False
    try:
        state = _get_registration_session(session, request.cookies.get(REGISTRATION_COOKIE, ""), "complete")
        registration = session.get(ParentRegistrationRequest, state.registration_request_id)
        has_state = registration is not None and registration.status == "approved"
    except AuthenticationFailed:
        pass
    if not has_state:
        return _registration_exchange_page(request, "complete")
    return _render(
        request,
        "parent_auth/complete.html",
        {
            "verify_url": "/parent-portal/register/complete/verify",
            "heading": "パスワード設定",
            "form_error": "",
        },
    )


@router.post("/parent-portal/register/complete/verify")
def completion_verify(request: Request, token: str = Form(""), session: Session = Depends(get_session)):
    try:
        state = exchange_completion_token(session, registration_token_from_input(token, "complete"))
    except AuthenticationFailed:
        return _registration_exchange_error(request, "complete")
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


@router.get("/parent-accounts/registration-qr", response_class=HTMLResponse)
def common_registration_qr_page(request: Request, session: Session = Depends(get_session),
                                current_user=Depends(get_current_staff_user)):
    _admin_actor(session, current_user)
    return _render_staff(request, "parent_auth/registration_qr.html", {
        "current_user": current_user, "accepting": public_registration_enabled(session),
        "registration_url": public_registration_url(),
    })


@router.post("/parent-accounts/registration-qr")
def common_registration_settings(enabled: str = Form(...), session: Session = Depends(get_session),
                                 current_user=Depends(get_current_staff_user)):
    actor = _admin_actor(session, current_user)
    if enabled not in {"yes", "no"}:
        raise HTTPException(400, "受付状態を選択してください")
    from models import AuthenticationEvent
    from time_utils import utc_now
    settings = session.get(ParentPublicRegistrationSettings, 1) or ParentPublicRegistrationSettings()
    settings.enabled = enabled == "yes"
    settings.updated_by_user_id = actor.id
    settings.updated_at = utc_now()
    session.add(settings)
    session.add(AuthenticationEvent(
        event_type="parent_public_registration_setting", principal_type="staff", staff_user_id=actor.id,
        result="success", reason_code="enabled" if settings.enabled else "disabled",
    ))
    session.commit()
    return RedirectResponse("/parent-accounts/registration-qr", status_code=303)


@router.get("/parent-accounts/registration-qr.svg")
def common_registration_qr_image(session: Session = Depends(get_session),
                                current_user=Depends(get_current_staff_user)):
    _admin_actor(session, current_user)
    import qrcode
    from qrcode.image.svg import SvgPathFillImage
    qr = qrcode.make(public_registration_url(), image_factory=SvgPathFillImage, border=4)
    response = Response(qr.to_string(), media_type="image/svg+xml")
    response.headers["Content-Disposition"] = 'inline; filename="parent-registration-qr.svg"'
    return _no_store(response)


@router.get("/parent-accounts/enrollment/new", response_class=HTMLResponse)
def enrollment_invite_page(request: Request, child_id: int | None = None, guardian_order: int | None = None,
                           session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    _admin_actor(session, current_user)
    try:
        child, order = enrollment_target(session, child_id, guardian_order)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _render_staff(request, "parent_auth/enrollment_invite.html", {
        "current_user": current_user, "child_id": child_id, "guardian_order": order,
        "child_name": child.full_name if child else "", "email": "", "form_error": "",
    })


@router.post("/parent-accounts/enrollment/invite")
def enrollment_invite(request: Request, child_name: str = Form(...), email: str = Form(...),
                      child_id: int | None = Form(None), guardian_order: int | None = Form(None),
                      session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor = _admin_actor(session, current_user)
    try:
        email = validate_parent_contact_email(session, email)
        account = ParentAccount(display_name="初回入力待ちの保護者", email=email)
        session.add(account)
        session.flush()
        enrollment = prepare_enrollment(session, account, child_name, child_id, guardian_order)
        account.display_name = f"{enrollment.child_name}さんの保護者（初回入力待ち）"
        session.add(account)
        issue_parent_invitation(session, account=account, actor_user=actor,
                                reason="入園時の初回情報登録", enrollment=enrollment)
    except (ValueError, HTTPException) as exc:
        session.rollback()
        return _render_staff(request, "parent_auth/enrollment_invite.html", {
            "current_user": current_user, "child_id": child_id, "guardian_order": guardian_order,
            "child_name": child_name, "email": email,
            "form_error": str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
        }, 400)
    return RedirectResponse(f"/parent-accounts/{account.id}/authentication", status_code=303)


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
            send_email=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _render_staff(
        request,
        "parent_auth/action_code_display.html",
        {
            "current_user": current_user, "account": account, "action_code": code,
        },
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
    mail_deliveries = session.exec(
        select(ParentMailDelivery.message_type, ParentMailDelivery.recipient,
               ParentMailDelivery.status, ParentMailDelivery.created_at,
               ParentMailDelivery.sent_at, ParentMailDelivery.next_retry_at)
        .where(ParentMailDelivery.parent_account_id == account_id)
        .order_by(ParentMailDelivery.created_at.desc()).limit(20)
    ).all()
    return _render_staff(
        request,
        "parent_auth/admin.html",
        {
            "current_user": current_user,
            "actor": actor,
            "account": account,
            "credential": credential,
            "registrations": registrations,
            "enrollments": {str(item.id): session.get(ParentEnrollment, item.id) for item in registrations},
            "public_registrations": {str(item.id) for item in registrations if session.get(ParentPublicRegistration, item.id)},
            "public_registration_targets": public_registration_targets(session) if any(
                item.status == "pending_review" and session.get(ParentPublicRegistration, item.id) for item in registrations
            ) else [],
            "enrollment_pending": bool(latest_enrollment(session, account_id) and not latest_enrollment(session, account_id).applied_at),
            "latest_enrollment": latest_enrollment(session, account_id),
            "enrollment_field_labels": FIELD_LABELS,
            "active_session_count": active_session_count,
            "mail_deliveries": mail_deliveries,
            "invitation_issues": parent_invitation_requirements(session, account),
            "invitation_children": [link.child for link in account.child_links if link.child],
            "registration_status_labels": REGISTRATION_STATUS_LABELS,
            "action_code": "",
            "form_error": "",
            "proposed_email": request.query_params.get("proposed_email")
            or account.email,
            "notice": request.query_params.get("notice", ""),
        },
    )


@router.post("/parent-accounts/{account_id}/authentication/login-id")
def admin_change_parent_login_id(
    account_id: int,
    new_email: str = Form(...),
    reason: str = Form(...),
    confirmed: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = _admin_actor(session, current_user)
    account = _load_admin_account(session, account_id)
    if confirmed != "yes":
        raise HTTPException(status_code=400, detail="変更内容の確認が必要です")
    try:
        change_parent_login_id_by_admin(
            session,
            account=account,
            actor_user=actor,
            new_email=new_email,
            reason=reason,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return RedirectResponse(
        f"/parent-accounts/{account_id}/authentication?notice=login_id_changed",
        status_code=303,
    )


@router.post("/parent-accounts/{account_id}/authentication/invite")
def admin_invite(
    account_id: int,
    reason: str = Form(...),
    enrollment_child_name: str | None = Form(None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    actor = _admin_actor(session, current_user)
    account = _load_admin_account(session, account_id)
    try:
        enrollment = latest_enrollment(session, account_id)
        updated_enrollment = None
        if enrollment_child_name is not None and enrollment and not enrollment.applied_at and enrollment.child_id is None:
            updated_enrollment = prepare_enrollment(session, account, enrollment_child_name)
            account.display_name = f"{updated_enrollment.child_name}さんの保護者（初回入力待ち）"
            session.add(account)
        issue_parent_invitation(
            session, account=account, actor_user=actor, reason=reason, enrollment=updated_enrollment
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
    enrollment_confirmed: str = Form(""),
    public_child_target: str = Form(""),
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
            enrollment_confirmed=enrollment_confirmed == "yes",
            public_child_target=public_child_target,
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
