from __future__ import annotations

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit
from database import get_session
from family_support import (
    apply_family_shared_data,
    build_family_payload,
    create_family_for_child,
    family_form_data_from_family,
    guardians_data_from_payload,
    sync_parent_child_links,
)
from models import Child, Family, ParentAccount
from time_utils import utc_now

router = APIRouter(prefix="/families", tags=["families"])
templates = Jinja2Templates(directory="templates")
def _parse_ids(raw_values: list[str]) -> list[int]:
    values: list[int] = []
    for raw in raw_values:
        try:
            values.append(int(raw))
        except (TypeError, ValueError):
            continue
    return values


def _all_children(session: Session) -> list[Child]:
    return session.exec(
        select(Child)
        .options(selectinload(Child.family))
        .order_by(Child.last_name_kana, Child.first_name_kana)
    ).all()


def _all_parent_accounts(session: Session) -> list[ParentAccount]:
    return session.exec(
        select(ParentAccount)
        .options(selectinload(ParentAccount.family))
        .order_by(ParentAccount.display_name)
    ).all()


def _load_family(session: Session, family_id: int) -> Family:
    family = session.exec(
        select(Family)
        .options(selectinload(Family.children), selectinload(Family.parent_accounts))
        .where(Family.id == family_id)
    ).first()
    if not family:
        raise HTTPException(status_code=404, detail="家族が見つかりません")
    return family


def _sync_family_by_id(session: Session, family_id: int) -> None:
    family = session.exec(
        select(Family)
        .options(selectinload(Family.children), selectinload(Family.parent_accounts))
        .where(Family.id == family_id)
    ).first()
    if family:
        sync_parent_child_links(session, family)


def _render_form(
    request: Request,
    *,
    current_user,
    family: Family | None,
    action_url: str,
    submit_label: str,
    form_error: str = "",
    form_data: dict[str, object] | None = None,
    selected_child_ids: set[int] | None = None,
    selected_parent_account_ids: set[int] | None = None,
    session: Session,
):
    return templates.TemplateResponse(
        "families/form.html",
        {
            "request": request,
            "current_user": current_user,
            "family": family,
            "action_url": action_url,
            "submit_label": submit_label,
            "form_error": form_error,
            "form_data": form_data or family_form_data_from_family(family),
            "children": _all_children(session),
            "parent_accounts": _all_parent_accounts(session),
            "selected_child_ids": (
                selected_child_ids
                if selected_child_ids is not None
                else ({child.id for child in family.children} if family else set())
            ),
            "selected_parent_account_ids": (
                selected_parent_account_ids
                if selected_parent_account_ids is not None
                else ({account.id for account in family.parent_accounts} if family else set())
            ),
        },
    )


def _guardians_data_from_form(
    *,
    g1_last_name: str,
    g1_first_name: str,
    g1_last_name_kana: str,
    g1_first_name_kana: str,
    g1_relationship: str,
    g1_phone: str,
    g1_workplace: str,
    g1_workplace_address: str,
    g1_workplace_phone: str,
    g2_last_name: str,
    g2_first_name: str,
    g2_last_name_kana: str,
    g2_first_name_kana: str,
    g2_relationship: str,
    g2_phone: str,
    g2_workplace: str,
    g2_workplace_address: str,
    g2_workplace_phone: str,
) -> list[dict[str, object]]:
    return guardians_data_from_payload(
        {
            "g1_last_name": g1_last_name,
            "g1_first_name": g1_first_name,
            "g1_last_name_kana": g1_last_name_kana,
            "g1_first_name_kana": g1_first_name_kana,
            "g1_relationship": g1_relationship,
            "g1_phone": g1_phone,
            "g1_workplace": g1_workplace,
            "g1_workplace_address": g1_workplace_address,
            "g1_workplace_phone": g1_workplace_phone,
            "g2_last_name": g2_last_name,
            "g2_first_name": g2_first_name,
            "g2_last_name_kana": g2_last_name_kana,
            "g2_first_name_kana": g2_first_name_kana,
            "g2_relationship": g2_relationship,
            "g2_phone": g2_phone,
            "g2_workplace": g2_workplace,
            "g2_workplace_address": g2_workplace_address,
            "g2_workplace_phone": g2_workplace_phone,
        }
    )


@router.get("/", response_class=HTMLResponse)
def family_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    families = session.exec(
        select(Family)
        .options(selectinload(Family.children), selectinload(Family.parent_accounts))
        .order_by(Family.family_name, Family.id)
    ).all()
    return templates.TemplateResponse(
        "families/list.html",
        {
            "request": request,
            "current_user": current_user,
            "families": families,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_family_form(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    return _render_form(
        request,
        current_user=current_user,
        family=None,
        action_url="/families/",
        submit_label="登録する",
        session=session,
    )


@router.post("/")
def create_family(
    request: Request,
    family_name: str = Form(...),
    home_address: str = Form(""),
    home_phone: str = Form(""),
    child_ids: list[str] = Form(default=[]),
    parent_account_ids: list[str] = Form(default=[]),
    g1_last_name: str = Form(""),
    g1_first_name: str = Form(""),
    g1_last_name_kana: str = Form(""),
    g1_first_name_kana: str = Form(""),
    g1_relationship: str = Form("母"),
    g1_phone: str = Form(""),
    g1_workplace: str = Form(""),
    g1_workplace_address: str = Form(""),
    g1_workplace_phone: str = Form(""),
    g2_last_name: str = Form(""),
    g2_first_name: str = Form(""),
    g2_last_name_kana: str = Form(""),
    g2_first_name_kana: str = Form(""),
    g2_relationship: str = Form("父"),
    g2_phone: str = Form(""),
    g2_workplace: str = Form(""),
    g2_workplace_address: str = Form(""),
    g2_workplace_phone: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)

    family = Family(family_name=family_name.strip())
    session.add(family)
    session.flush()

    selected_child_ids = _parse_ids(child_ids)
    selected_parent_account_ids = _parse_ids(parent_account_ids)
    touched_family_ids: set[int] = {family.id}

    for child in session.exec(select(Child).where(Child.id.in_(selected_child_ids) if selected_child_ids else False)).all():
        if child.family_id and child.family_id != family.id:
            touched_family_ids.add(child.family_id)
        child.family_id = family.id
        child.updated_at = utc_now()
        session.add(child)

    for account in session.exec(
        select(ParentAccount).where(ParentAccount.id.in_(selected_parent_account_ids) if selected_parent_account_ids else False)
    ).all():
        if account.family_id and account.family_id != family.id:
            touched_family_ids.add(account.family_id)
        account.family_id = family.id
        account.updated_at = utc_now()
        session.add(account)

    apply_family_shared_data(
        session,
        family,
        build_family_payload(
            family_name=family_name,
            home_address=home_address,
            home_phone=home_phone,
            guardians_data=_guardians_data_from_form(
                g1_last_name=g1_last_name,
                g1_first_name=g1_first_name,
                g1_last_name_kana=g1_last_name_kana,
                g1_first_name_kana=g1_first_name_kana,
                g1_relationship=g1_relationship,
                g1_phone=g1_phone,
                g1_workplace=g1_workplace,
                g1_workplace_address=g1_workplace_address,
                g1_workplace_phone=g1_workplace_phone,
                g2_last_name=g2_last_name,
                g2_first_name=g2_first_name,
                g2_last_name_kana=g2_last_name_kana,
                g2_first_name_kana=g2_first_name_kana,
                g2_relationship=g2_relationship,
                g2_phone=g2_phone,
                g2_workplace=g2_workplace,
                g2_workplace_address=g2_workplace_address,
                g2_workplace_phone=g2_workplace_phone,
            ),
        ),
    )

    for touched_family_id in touched_family_ids:
        _sync_family_by_id(session, touched_family_id)

    session.commit()
    return RedirectResponse(url="/families/", status_code=303)


@router.get("/{family_id}/edit", response_class=HTMLResponse)
def edit_family_form(
    request: Request,
    family_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    family = _load_family(session, family_id)
    return _render_form(
        request,
        current_user=current_user,
        family=family,
        action_url=f"/families/{family_id}/edit",
        submit_label="更新する",
        session=session,
    )


@router.post("/{family_id}/edit")
def update_family(
    request: Request,
    family_id: int,
    family_name: str = Form(...),
    home_address: str = Form(""),
    home_phone: str = Form(""),
    child_ids: list[str] = Form(default=[]),
    parent_account_ids: list[str] = Form(default=[]),
    g1_last_name: str = Form(""),
    g1_first_name: str = Form(""),
    g1_last_name_kana: str = Form(""),
    g1_first_name_kana: str = Form(""),
    g1_relationship: str = Form("母"),
    g1_phone: str = Form(""),
    g1_workplace: str = Form(""),
    g1_workplace_address: str = Form(""),
    g1_workplace_phone: str = Form(""),
    g2_last_name: str = Form(""),
    g2_first_name: str = Form(""),
    g2_last_name_kana: str = Form(""),
    g2_first_name_kana: str = Form(""),
    g2_relationship: str = Form("父"),
    g2_phone: str = Form(""),
    g2_workplace: str = Form(""),
    g2_workplace_address: str = Form(""),
    g2_workplace_phone: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    family = _load_family(session, family_id)

    selected_child_ids = set(_parse_ids(child_ids))
    selected_parent_account_ids = set(_parse_ids(parent_account_ids))
    touched_family_ids: set[int] = {family.id}

    current_child_ids = {child.id for child in family.children if child.id is not None}
    current_parent_account_ids = {account.id for account in family.parent_accounts if account.id is not None}

    for child in list(family.children):
        if child.id not in selected_child_ids:
            child.family_id = None
            child.updated_at = utc_now()
            session.add(child)
            session.flush()
            new_family = create_family_for_child(session, child, family_name=f"{child.last_name}家")
            touched_family_ids.add(new_family.id)

    for account in list(family.parent_accounts):
        if account.id not in selected_parent_account_ids:
            account.family_id = None
            account.updated_at = utc_now()
            session.add(account)

    newly_selected_children = selected_child_ids - current_child_ids
    if newly_selected_children:
        for child in session.exec(select(Child).where(Child.id.in_(newly_selected_children))).all():
            if child.family_id and child.family_id != family.id:
                touched_family_ids.add(child.family_id)
            child.family_id = family.id
            child.updated_at = utc_now()
            session.add(child)

    newly_selected_accounts = selected_parent_account_ids - current_parent_account_ids
    if newly_selected_accounts:
        for account in session.exec(select(ParentAccount).where(ParentAccount.id.in_(newly_selected_accounts))).all():
            if account.family_id and account.family_id != family.id:
                touched_family_ids.add(account.family_id)
            account.family_id = family.id
            account.updated_at = utc_now()
            session.add(account)

    apply_family_shared_data(
        session,
        family,
        build_family_payload(
            family_name=family_name,
            home_address=home_address,
            home_phone=home_phone,
            guardians_data=_guardians_data_from_form(
                g1_last_name=g1_last_name,
                g1_first_name=g1_first_name,
                g1_last_name_kana=g1_last_name_kana,
                g1_first_name_kana=g1_first_name_kana,
                g1_relationship=g1_relationship,
                g1_phone=g1_phone,
                g1_workplace=g1_workplace,
                g1_workplace_address=g1_workplace_address,
                g1_workplace_phone=g1_workplace_phone,
                g2_last_name=g2_last_name,
                g2_first_name=g2_first_name,
                g2_last_name_kana=g2_last_name_kana,
                g2_first_name_kana=g2_first_name_kana,
                g2_relationship=g2_relationship,
                g2_phone=g2_phone,
                g2_workplace=g2_workplace,
                g2_workplace_address=g2_workplace_address,
                g2_workplace_phone=g2_workplace_phone,
            ),
        ),
    )

    for touched_family_id in touched_family_ids:
        _sync_family_by_id(session, touched_family_id)

    session.commit()
    return RedirectResponse(url="/families/", status_code=303)
