from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import (
    get_current_staff_user,
    parent_auth_is_mock,
    require_child_record_manager,
)
from database import get_session
from family_support import (
    bind_parent_account_guardian,
    guardian_account_values,
    sync_parent_account_to_family,
    sync_parent_child_links,
    validate_parent_contact_email,
)
from models import (
    Child,
    Family,
    ParentAccount,
    ParentAccountStatus,
    ParentChildLink,
    ParentChildLinkAudit,
    ProfileChangeNotification,
)
from parent_auth import cancel_open_parent_registrations, suspend_parent_authentication
from time_utils import utc_now

router = APIRouter(prefix="/parent-accounts", tags=["parent_accounts"])
from template_utils import create_templates

templates = create_templates()


def _all_families(session: Session) -> list[Family]:
    return session.exec(
        select(Family)
        .options(selectinload(Family.children), selectinload(Family.parent_accounts))
        .order_by(Family.family_name, Family.id)
    ).all()


def _all_children(session: Session) -> list[Child]:
    return session.exec(
        select(Child).order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()


def _guardian_choices(families: list[Family], account_id: int | None = None) -> list[dict]:
    return [
        {"value": f"{family.id}:{profile['order']}", "family_id": family.id,
         "label": f"{family.family_name} / {profile['last_name']} {profile['first_name']}（{profile.get('relationship') or '保護者'}）",
         "fields": guardian_account_values(family, profile)}
        for family in families for profile in family.guardian_profiles()
        if profile.get("parent_account_id") in (None, account_id)
    ]


def _replace_child_links(
    session: Session, account: ParentAccount, child_ids: list[int], actor
) -> bool:
    existing = session.exec(
        select(ParentChildLink).where(ParentChildLink.parent_account_id == account.id)
    ).all()
    existing_by_child_id = {link.child_id: link for link in existing}
    old_ids = set(existing_by_child_id)
    new_ids = set(child_ids)
    if new_ids:
        valid_ids = set(
            session.exec(select(Child.id).where(Child.id.in_(new_ids))).all()
        )
        if valid_ids != new_ids:
            raise HTTPException(
                status_code=400, detail="存在しない園児が指定されています"
            )
    if old_ids == new_ids:
        return False
    for child_id in sorted(old_ids - new_ids):
        session.add(
            ParentChildLinkAudit(
                parent_account_id=account.id,
                child_id=child_id,
                operation="unlink",
                actor_user_id=actor.user_id,
                actor_name=actor.name,
            )
        )
    for child_id in sorted(new_ids - old_ids):
        session.add(
            ParentChildLinkAudit(
                parent_account_id=account.id,
                child_id=child_id,
                operation="link",
                actor_user_id=actor.user_id,
                actor_name=actor.name,
            )
        )
    for child_id in old_ids - new_ids:
        session.delete(existing_by_child_id[child_id])
    for child_id in sorted(new_ids - old_ids):
        session.add(ParentChildLink(parent_account_id=account.id, child_id=child_id))
    return True


def _load_account(session: Session, account_id: int) -> ParentAccount:
    account = session.exec(
        select(ParentAccount)
        .options(
            selectinload(ParentAccount.family).selectinload(Family.children),
            selectinload(ParentAccount.family).selectinload(Family.parent_accounts),
        )
        .where(ParentAccount.id == account_id)
    ).first()
    if not account:
        raise HTTPException(status_code=404, detail="保護者アカウントが見つかりません")
    return account


def _sync_related_families(session: Session, family_ids: set[int]) -> None:
    for family_id in sorted(family_ids):
        family = session.exec(
            select(Family)
            .options(
                selectinload(Family.children), selectinload(Family.parent_accounts)
            )
            .where(Family.id == family_id)
        ).first()
        if family:
            sync_parent_child_links(session, family)


@router.get("/", response_class=HTMLResponse)
def parent_account_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    accounts = session.exec(
        select(ParentAccount)
        .options(
            selectinload(ParentAccount.family).selectinload(Family.children),
            selectinload(ParentAccount.child_links).selectinload(ParentChildLink.child),
        )
        .order_by(ParentAccount.display_name)
    ).all()
    notifications = session.exec(
        select(ProfileChangeNotification)
        .options(selectinload(ProfileChangeNotification.parent_account))
        .where(ProfileChangeNotification.is_read == False)  # noqa: E712
        .order_by(ProfileChangeNotification.created_at.desc())
    ).all()
    return templates.TemplateResponse(
        request,
        "parent_accounts/list.html",
        {
            "request": request,
            "accounts": accounts,
            "notifications": notifications,
            "parent_mock_login_available": parent_auth_is_mock(),
            "current_user": current_user,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_parent_account_form(
    request: Request,
    family_id: int | None = Query(default=None),
    guardian_order: int | None = Query(default=None),
    child_id: int | None = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    families = _all_families(session)
    account = None
    selected_link = ""
    selected_children = set()
    if guardian_order is not None:
        family = session.get(Family, family_id) if family_id else None
        profiles = [item for item in family.guardian_profiles() if item.get("order") == guardian_order] if family else []
        if len(profiles) != 1:
            raise HTTPException(404, "家族の保護者情報が見つかりません")
        if profiles[0].get("parent_account_id"):
            return RedirectResponse(f"/parent-accounts/{profiles[0]['parent_account_id']}/edit", status_code=303)
        account = ParentAccount(**guardian_account_values(family, profiles[0]), status=ParentAccountStatus.active)
        selected_link = f"{family_id}:{guardian_order}"
        if child_id is not None:
            child = session.get(Child, child_id)
            if child is None or child.family_id != family_id:
                raise HTTPException(400, "対象園児の家族が一致していません")
            selected_children.add(child.id)
    return templates.TemplateResponse(
        request,
        "parent_accounts/form.html",
        {
            "request": request,
            "account": account,
            "families": families,
            "guardian_choices": _guardian_choices(families),
            "selected_guardian_link": selected_link,
            "children": _all_children(session),
            "selected_child_ids": selected_children,
            "selected_family_id": family_id or "",
            "action_url": "/parent-accounts/",
            "submit_label": "登録して招待へ" if selected_link and current_user.is_admin else "登録する",
            "current_user": current_user,
            "status_options": list(ParentAccountStatus),
        },
    )


@router.post("/")
def create_parent_account(
    display_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    home_address: str = Form(""),
    workplace: str = Form(""),
    workplace_address: str = Form(""),
    workplace_phone: str = Form(""),
    status: str = Form("active"),
    family_id: str = Form(""),
    guardian_link: str | None = Form(default=None),
    registration_verification_name: str = Form(""),
    registration_verification_name_type: str = Form(""),
    child_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    email = validate_parent_contact_email(session, email)
    try:
        normalized_status = ParentAccountStatus(status)
    except ValueError:
        normalized_status = ParentAccountStatus.active

    selected_family_id = int(family_id) if family_id and family_id.isdigit() else None
    account = ParentAccount(
        display_name=display_name.strip(),
        email=email.strip(),
        registration_verification_name=registration_verification_name.strip() or None,
        registration_verification_name_type=registration_verification_name_type
        if registration_verification_name_type in {"kana", "latin"}
        else None,
        phone=(phone or "").strip() or None,
        home_address=(home_address or "").strip() or None,
        workplace=(workplace or "").strip() or None,
        workplace_address=(workplace_address or "").strip() or None,
        workplace_phone=(workplace_phone or "").strip() or None,
        family_id=selected_family_id,
        status=normalized_status,
        invited_at=utc_now(),
    )
    session.add(account)
    session.flush()
    _replace_child_links(session, account, child_ids, current_user)
    bind_parent_account_guardian(session, account, guardian_link)
    sync_parent_account_to_family(session, account)

    if selected_family_id:
        _sync_related_families(session, {selected_family_id})

    session.commit()
    destination = f"/parent-accounts/{account.id}/authentication" if guardian_link and ":" in guardian_link and current_user.is_admin else "/parent-accounts/"
    return RedirectResponse(url=destination, status_code=303)


@router.get("/{account_id}/edit", response_class=HTMLResponse)
def edit_parent_account_form(
    request: Request,
    account_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    account = _load_account(session, account_id)
    families = _all_families(session)
    selected_link = next((f"{family.id}:{profile['order']}" for family in families
                          for profile in family.guardian_profiles()
                          if family.id == account.family_id and profile.get("parent_account_id") == account.id), "")
    return templates.TemplateResponse(
        request,
        "parent_accounts/form.html",
        {
            "request": request,
            "account": account,
            "families": families,
            "guardian_choices": _guardian_choices(families, account.id),
            "selected_guardian_link": selected_link,
            "children": _all_children(session),
            "selected_child_ids": {link.child_id for link in account.child_links},
            "selected_family_id": account.family_id if account.family_id else "",
            "action_url": f"/parent-accounts/{account_id}/edit",
            "submit_label": "更新する",
            "current_user": current_user,
            "status_options": list(ParentAccountStatus),
        },
    )


@router.post("/{account_id}/edit")
def update_parent_account(
    account_id: int,
    display_name: str = Form(...),
    email: str = Form(...),
    phone: str = Form(""),
    home_address: str = Form(""),
    workplace: str = Form(""),
    workplace_address: str = Form(""),
    workplace_phone: str = Form(""),
    status: str = Form("active"),
    family_id: str = Form(""),
    guardian_link: str | None = Form(default=None),
    registration_verification_name: str = Form(""),
    registration_verification_name_type: str = Form(""),
    child_ids: list[int] = Form(default=[]),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    account = _load_account(session, account_id)
    email = validate_parent_contact_email(session, email, account.id)
    previous_address = account.home_address
    old_family_id = account.family_id
    old_email = account.email
    old_verification = (
        account.registration_verification_name,
        account.registration_verification_name_type,
    )

    try:
        normalized_status = ParentAccountStatus(status)
    except ValueError:
        normalized_status = ParentAccountStatus.active

    account.display_name = display_name.strip()
    account.email = email.strip()
    account.registration_verification_name = (
        registration_verification_name.strip() or None
    )
    account.registration_verification_name_type = (
        registration_verification_name_type
        if registration_verification_name_type in {"kana", "latin"}
        else None
    )
    account.phone = (phone or "").strip() or None
    account.home_address = (home_address or "").strip() or None
    account.workplace = (workplace or "").strip() or None
    account.workplace_address = (workplace_address or "").strip() or None
    account.workplace_phone = (workplace_phone or "").strip() or None
    account.family_id = int(family_id) if family_id and family_id.isdigit() else None
    account.status = normalized_status
    account.updated_at = utc_now()
    session.add(account)
    session.flush()
    links_changed = _replace_child_links(session, account, child_ids, current_user)
    bind_parent_account_guardian(session, account, guardian_link, old_family_id=old_family_id)
    sync_parent_account_to_family(session, account, previous_address=previous_address)
    if (
        links_changed
        or old_email != account.email
        or old_verification
        != (
            account.registration_verification_name,
            account.registration_verification_name_type,
        )
    ):
        cancel_open_parent_registrations(session, account.id)
    if account.status == ParentAccountStatus.inactive:
        suspend_parent_authentication(
            session,
            account,
            reason="parent_account_inactive",
        )

    family_ids = {
        family_id
        for family_id in [old_family_id, account.family_id]
        if family_id is not None
    }
    _sync_related_families(session, family_ids)

    session.commit()
    return RedirectResponse(url="/parent-accounts/", status_code=303)


@router.post("/notifications/{notification_id}/read")
def mark_profile_notification_read(
    notification_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    notification = session.get(ProfileChangeNotification, notification_id)
    if not notification:
        raise HTTPException(status_code=404, detail="通知が見つかりません")

    notification.is_read = True
    notification.read_at = utc_now()
    session.add(notification)
    session.commit()
    return RedirectResponse(url="/parent-accounts/", status_code=303)
