from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit
from child_profile_changes import RELATIONSHIP_OPTIONS
from database import get_session
from family_support import (
    apply_family_shared_data,
    build_family_form_data,
    build_family_payload,
    create_family_for_child,
    family_form_data_from_child,
    family_form_data_from_family,
    guardians_data_from_payload,
    move_child_to_family,
    sync_parent_child_links,
)
from models import CHILD_FIELDS, Child, ChildStatus, Classroom, Family, ParentChildLink
from time_utils import utc_now

router = APIRouter(prefix="/children", tags=["children"])
templates = Jinja2Templates(directory="templates")
SORT_OPTIONS = {
    "name": "名前",
    "birth_date": "生年月日",
}
SORT_ORDER_OPTIONS = {
    "asc": "昇順",
    "desc": "降順",
}


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw or not raw.strip():
        return None
    try:
        return date.fromisoformat(raw.strip())
    except ValueError:
        return None


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _all_children(session: Session) -> list[Child]:
    return session.exec(
        select(Child).order_by(Child.last_name_kana, Child.first_name_kana)
    ).all()


def _all_classrooms(session: Session) -> list[Classroom]:
    return session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()


def _apply_child_sort(statement, sort_by: str, sort_order: str):
    sort_direction = sort_order if sort_order in SORT_ORDER_OPTIONS else "asc"
    if sort_by == "birth_date":
        first = Child.birth_date.asc() if sort_direction == "asc" else Child.birth_date.desc()
        second = Child.last_name_kana.asc() if sort_direction == "asc" else Child.last_name_kana.desc()
        third = Child.first_name_kana.asc() if sort_direction == "asc" else Child.first_name_kana.desc()
        return statement.order_by(first, second, third)

    first = Child.last_name_kana.asc() if sort_direction == "asc" else Child.last_name_kana.desc()
    second = Child.first_name_kana.asc() if sort_direction == "asc" else Child.first_name_kana.desc()
    third = Child.birth_date.asc() if sort_direction == "asc" else Child.birth_date.desc()
    return statement.order_by(first, second, third)


def _all_families(session: Session) -> list[Family]:
    return session.exec(
        select(Family)
        .options(selectinload(Family.children), selectinload(Family.parent_accounts))
        .order_by(Family.family_name, Family.id)
    ).all()


def _load_child(session: Session, child_id: int) -> Child:
    child = session.exec(
        select(Child)
        .options(
            selectinload(Child.classroom),
            selectinload(Child.guardians),
            selectinload(Child.older_sibling).selectinload(Child.classroom),
            selectinload(Child.younger_siblings).selectinload(Child.classroom),
            selectinload(Child.family).selectinload(Family.children).selectinload(Child.classroom),
            selectinload(Child.family).selectinload(Family.parent_accounts),
        )
        .where(Child.id == child_id)
    ).first()
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    return child


def _sorted_family_children(child: Child) -> list[Child]:
    if not child.family or not child.family.children:
        return []
    return sorted(
        child.family.children,
        key=lambda item: (
            item.birth_date,
            item.last_name_kana,
            item.first_name_kana,
            item.id or 0,
        ),
    )


def _sibling_relationships(child: Optional[Child]) -> list[dict[str, object]]:
    if not child:
        return []

    relationships: list[dict[str, object]] = []
    if child.older_sibling:
        relationships.append({"label": "兄姉", "child": child.older_sibling})

    younger_siblings = sorted(
        child.younger_siblings,
        key=lambda item: (
            item.birth_date or date.max,
            item.last_name_kana or "",
            item.first_name_kana or "",
            item.id or 0,
        ),
    )
    relationships.extend(
        {"label": "弟妹", "child": sibling} for sibling in younger_siblings
    )
    return relationships


def _load_family(session: Session, raw_selection: Optional[str]) -> Optional[Family]:
    if not raw_selection or raw_selection == "new":
        return None
    try:
        family_id = int(raw_selection)
    except (TypeError, ValueError):
        return None
    return session.get(Family, family_id)


def _selected_family_value(child: Optional[Child], selected_family: Optional[Family]):
    if selected_family and selected_family.id is not None:
        return selected_family.id
    if child and child.family_id is not None:
        return child.family_id
    return "new"


def _base_form_context(
    request: Request,
    *,
    child: Optional[Child],
    all_children: list[Child],
    classrooms: list[Classroom],
    families: list[Family],
    selected_family_value: str,
    family_form_data: dict[str, object],
    current_user,
    action_url: str,
    submit_label: str,
    page_title: str,
    form_error: str = "",
    form_data: Optional[dict[str, str]] = None,
    older_sibling_id: Optional[int] = None,
    inherit_from: Optional[Child] = None,
):
    relationship_child = child or inherit_from
    base_family = (
        child.family
        if child and child.family
        else inherit_from.family
        if inherit_from and inherit_from.family
        else None
    )
    sibling_children = []
    if base_family and base_family.children:
        excluded_id = child.id if child else None
        sibling_children = [
            family_child
            for family_child in sorted(
                base_family.children,
                key=lambda item: (item.birth_date, item.last_name_kana, item.first_name_kana),
            )
            if family_child.id != excluded_id
        ]
    return templates.TemplateResponse(
        "children/form.html",
        {
            "request": request,
            "child": child,
            "all_children": all_children,
            "classrooms": classrooms,
            "families": families,
            "selected_family_value": selected_family_value,
            "family_form_data": family_form_data,
            "form_data": form_data or {},
            "action_url": action_url,
            "submit_label": submit_label,
            "page_title": page_title,
            "form_error": form_error,
            "older_sibling_id": older_sibling_id,
            "inherit_from": inherit_from,
            "show_family_selection": child is None and inherit_from is None,
            "sibling_relationships": _sibling_relationships(relationship_child),
            "siblings": sibling_children,
            "family_context_child": child or inherit_from,
            "current_user": current_user,
            "relationship_options": RELATIONSHIP_OPTIONS,
        },
    )


@router.get("/", response_class=HTMLResponse)
def list_children(
    request: Request,
    status: Optional[str] = Query(default="enrolled"),
    fields: list[str] = Query(default=[]),
    sort_by: str = Query(default="name"),
    sort_order: str = Query(default="asc"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    stmt = select(Child).options(
        selectinload(Child.classroom),
        selectinload(Child.guardians),
        selectinload(Child.family).selectinload(Family.parent_accounts),
        selectinload(Child.older_sibling),
        selectinload(Child.parent_links).selectinload(ParentChildLink.parent_account),
    )
    if status and status != "all":
        stmt = stmt.where(Child.status == status)
    stmt = _apply_child_sort(stmt, sort_by, sort_order)
    children = session.exec(stmt).all()

    if not fields:
        fields = [field["key"] for field in CHILD_FIELDS if field["default"]]

    return templates.TemplateResponse(
        "children/list.html",
        {
            "request": request,
            "children": children,
            "all_fields": CHILD_FIELDS,
            "selected_fields": fields,
            "current_status": status,
            "current_sort_by": sort_by if sort_by in SORT_OPTIONS else "name",
            "current_sort_order": sort_order if sort_order in SORT_ORDER_OPTIONS else "asc",
            "sort_options": SORT_OPTIONS,
            "sort_order_options": SORT_ORDER_OPTIONS,
            "total": len(children),
            "current_user": current_user,
        },
    )


@router.get("/table", response_class=HTMLResponse)
def children_table(
    request: Request,
    status: Optional[str] = Query(default="enrolled"),
    fields: list[str] = Query(default=[]),
    sort_by: str = Query(default="name"),
    sort_order: str = Query(default="asc"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    stmt = select(Child).options(
        selectinload(Child.classroom),
        selectinload(Child.guardians),
        selectinload(Child.family).selectinload(Family.parent_accounts),
        selectinload(Child.older_sibling),
        selectinload(Child.parent_links).selectinload(ParentChildLink.parent_account),
    )
    if status and status != "all":
        stmt = stmt.where(Child.status == status)
    stmt = _apply_child_sort(stmt, sort_by, sort_order)
    children = session.exec(stmt).all()

    if not fields:
        fields = [field["key"] for field in CHILD_FIELDS if field["default"]]

    field_labels = {field["key"]: field["label"] for field in CHILD_FIELDS}
    return templates.TemplateResponse(
        "children/_table.html",
        {
            "request": request,
            "children": children,
            "selected_fields": fields,
            "field_labels": field_labels,
            "total": len(children),
            "current_user": current_user,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_child_form(
    request: Request,
    sibling_id: Optional[int] = Query(default=None),
    family_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    inherit_from = _load_child(session, sibling_id) if sibling_id else None
    selected_family = session.get(Family, family_id) if family_id else (inherit_from.family if inherit_from else None)
    family_form_data = (
        family_form_data_from_family(selected_family)
        if selected_family
        else family_form_data_from_child(inherit_from)
        if inherit_from
        else family_form_data_from_family(None)
    )

    return _base_form_context(
        request,
        child=None,
        all_children=_all_children(session),
        classrooms=_all_classrooms(session),
        families=_all_families(session),
        selected_family_value=_selected_family_value(None, selected_family),
        family_form_data=family_form_data,
        current_user=current_user,
        action_url="/children/",
        submit_label="登録する",
        page_title="園児を追加",
        older_sibling_id=sibling_id,
        inherit_from=inherit_from,
    )


def _build_form_input(
    *,
    last_name: str,
    first_name: str,
    last_name_kana: str,
    first_name_kana: str,
    birth_date: Optional[str],
    enrollment_date: Optional[str],
    withdrawal_date: Optional[str],
    status: str,
    classroom_id: Optional[str],
    allergy: str,
    medical_notes: str,
) -> dict[str, str]:
    return {
        "last_name": last_name,
        "first_name": first_name,
        "last_name_kana": last_name_kana,
        "first_name_kana": first_name_kana,
        "birth_date": birth_date or "",
        "enrollment_date": enrollment_date or "",
        "withdrawal_date": withdrawal_date or "",
        "status": status,
        "classroom_id": classroom_id or "",
        "allergy": allergy,
        "medical_notes": medical_notes,
    }


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


def _family_form_data_from_input(
    *,
    family_name: str,
    home_address: str,
    home_phone: str,
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
) -> dict[str, object]:
    return build_family_form_data(
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
    )


def _family_payload_from_input(
    *,
    family_name: str,
    home_address: str,
    home_phone: str,
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
) -> dict[str, object]:
    return build_family_payload(
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
    )


def _selected_classroom_id_value(classroom_id: Optional[int]) -> str:
    return str(classroom_id) if classroom_id is not None else ""


def _resolve_classroom(session: Session, raw_classroom_id: Optional[str]) -> tuple[Optional[Classroom], Optional[str]]:
    classroom_id = _parse_optional_int(raw_classroom_id)
    if classroom_id is None:
        return None, None

    classroom = session.get(Classroom, classroom_id)
    if not classroom:
        return None, "選択されたクラスが見つかりません。"
    return classroom, None


@router.post("/")
def create_child(
    request: Request,
    current_user=Depends(get_current_staff_user),
    last_name: str = Form(...),
    first_name: str = Form(...),
    last_name_kana: str = Form(...),
    first_name_kana: str = Form(...),
    birth_date: Optional[str] = Form(None),
    enrollment_date: Optional[str] = Form(None),
    withdrawal_date: Optional[str] = Form(None),
    status: str = Form("enrolled"),
    classroom_id: str = Form(""),
    allergy: str = Form(""),
    medical_notes: str = Form(""),
    older_sibling_id: Optional[str] = Form(None),
    family_selection: str = Form("new"),
    family_name: str = Form(""),
    home_address: str = Form(""),
    home_phone: str = Form(""),
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
):
    require_can_edit(current_user)
    parsed_birth_date = _parse_date(birth_date)
    parsed_enrollment_date = _parse_date(enrollment_date)
    parsed_withdrawal_date = _parse_date(withdrawal_date)
    selected_family = _load_family(session, family_selection)
    selected_classroom, classroom_error = _resolve_classroom(session, classroom_id)

    if not parsed_birth_date or not parsed_enrollment_date or classroom_error:
        return _base_form_context(
            request,
            child=None,
            all_children=_all_children(session),
            classrooms=_all_classrooms(session),
            families=_all_families(session),
            selected_family_value=_selected_family_value(None, selected_family),
            family_form_data=_family_form_data_from_input(
                family_name=family_name,
                home_address=home_address,
                home_phone=home_phone,
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
            current_user=current_user,
            action_url="/children/",
            submit_label="登録する",
            page_title="園児を追加",
            form_error=classroom_error or "生年月日と入園日は必須です。",
            form_data=_build_form_input(
                last_name=last_name,
                first_name=first_name,
                last_name_kana=last_name_kana,
                first_name_kana=first_name_kana,
                birth_date=birth_date,
                enrollment_date=enrollment_date,
                withdrawal_date=withdrawal_date,
                status=status,
                classroom_id=classroom_id,
                allergy=allergy,
                medical_notes=medical_notes,
            ),
            older_sibling_id=int(older_sibling_id) if older_sibling_id and older_sibling_id.isdigit() else None,
        )

    try:
        normalized_status = ChildStatus(status)
    except ValueError:
        normalized_status = ChildStatus.enrolled

    allergies = [item.strip() for item in allergy.replace("、", ",").split(",") if item.strip()]
    child = Child(
        last_name=last_name.strip(),
        first_name=first_name.strip(),
        last_name_kana=last_name_kana.strip(),
        first_name_kana=first_name_kana.strip(),
        birth_date=parsed_birth_date,
        enrollment_date=parsed_enrollment_date,
        withdrawal_date=parsed_withdrawal_date,
        status=normalized_status,
        classroom_id=selected_classroom.id if selected_classroom else None,
        older_sibling_id=int(older_sibling_id) if older_sibling_id and older_sibling_id.isdigit() else None,
        extra_data={"allergy": allergies, "medical_notes": medical_notes or ""},
    )
    session.add(child)
    session.flush()

    if selected_family:
        move_child_to_family(session, child, selected_family)
        family = selected_family
    else:
        family = create_family_for_child(session, child, family_name=(family_name or "").strip() or f"{child.last_name}家")

    apply_family_shared_data(
        session,
        family,
        _family_payload_from_input(
            family_name=(family_name or "").strip() or family.family_name,
            home_address=home_address,
            home_phone=home_phone,
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
    )

    session.commit()
    return RedirectResponse(url="/children/", status_code=303)


@router.get("/{child_id}", response_class=HTMLResponse)
def child_detail(
    request: Request,
    child_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    child = _load_child(session, child_id)
    family_children = _sorted_family_children(child)
    family_parent_accounts = (
        sorted(
            child.family.parent_accounts,
            key=lambda account: (account.display_name or "", account.id or 0),
        )
        if child.family and child.family.parent_accounts
        else []
    )
    guardian_profiles = child.family.guardian_profiles() if child.family else []

    return templates.TemplateResponse(
        request,
        "children/detail.html",
        {
            "request": request,
            "child": child,
            "current_user": current_user,
            "guardian_profiles": guardian_profiles,
            "family_children": family_children,
            "family_parent_accounts": family_parent_accounts,
        },
    )


@router.get("/{child_id}/edit", response_class=HTMLResponse)
def edit_child_form(
    request: Request,
    child_id: int,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    return _base_form_context(
        request,
        child=child,
        all_children=_all_children(session),
        classrooms=_all_classrooms(session),
        families=_all_families(session),
        selected_family_value=_selected_family_value(child, child.family),
        family_form_data=family_form_data_from_child(child),
        current_user=current_user,
        action_url=f"/children/{child_id}/edit",
        submit_label="更新する",
        page_title=f"{child.full_name} を編集",
    )


@router.post("/{child_id}/edit")
def update_child(
    request: Request,
    child_id: int,
    current_user=Depends(get_current_staff_user),
    last_name: str = Form(...),
    first_name: str = Form(...),
    last_name_kana: str = Form(...),
    first_name_kana: str = Form(...),
    birth_date: Optional[str] = Form(None),
    enrollment_date: Optional[str] = Form(None),
    withdrawal_date: Optional[str] = Form(None),
    status: str = Form("enrolled"),
    classroom_id: str = Form(""),
    allergy: str = Form(""),
    medical_notes: str = Form(""),
    family_selection: str = Form("new"),
    family_name: str = Form(""),
    home_address: str = Form(""),
    home_phone: str = Form(""),
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
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    old_family_id = child.family_id
    parsed_birth_date = _parse_date(birth_date)
    parsed_enrollment_date = _parse_date(enrollment_date)
    parsed_withdrawal_date = _parse_date(withdrawal_date)
    selected_family = _load_family(session, family_selection)
    selected_classroom, classroom_error = _resolve_classroom(session, classroom_id)

    if not parsed_birth_date or not parsed_enrollment_date or classroom_error:
        return _base_form_context(
            request,
            child=child,
            all_children=_all_children(session),
            classrooms=_all_classrooms(session),
            families=_all_families(session),
            selected_family_value=_selected_family_value(child, selected_family),
            family_form_data=_family_form_data_from_input(
                family_name=family_name,
                home_address=home_address,
                home_phone=home_phone,
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
            current_user=current_user,
            action_url=f"/children/{child_id}/edit",
            submit_label="更新する",
            page_title=f"{child.full_name} を編集",
            form_error=classroom_error or "生年月日と入園日は必須です。",
            form_data=_build_form_input(
                last_name=last_name,
                first_name=first_name,
                last_name_kana=last_name_kana,
                first_name_kana=first_name_kana,
                birth_date=birth_date,
                enrollment_date=enrollment_date,
                withdrawal_date=withdrawal_date,
                status=status,
                classroom_id=classroom_id,
                allergy=allergy,
                medical_notes=medical_notes,
            ),
        )

    try:
        normalized_status = ChildStatus(status)
    except ValueError:
        normalized_status = ChildStatus.enrolled

    allergies = [item.strip() for item in allergy.replace("、", ",").split(",") if item.strip()]
    child.last_name = last_name.strip()
    child.first_name = first_name.strip()
    child.last_name_kana = last_name_kana.strip()
    child.first_name_kana = first_name_kana.strip()
    child.birth_date = parsed_birth_date
    child.enrollment_date = parsed_enrollment_date
    child.withdrawal_date = parsed_withdrawal_date
    child.status = normalized_status
    child.classroom_id = selected_classroom.id if selected_classroom else None
    child.extra_data = {"allergy": allergies, "medical_notes": medical_notes or ""}
    child.updated_at = utc_now()
    session.add(child)
    session.flush()

    if selected_family:
        move_child_to_family(session, child, selected_family)
        family = selected_family
    else:
        if old_family_id is not None:
            child.family_id = None
            session.add(child)
            session.flush()
        family = create_family_for_child(session, child, family_name=(family_name or "").strip() or f"{child.last_name}家")

    apply_family_shared_data(
        session,
        family,
        _family_payload_from_input(
            family_name=(family_name or "").strip() or family.family_name,
            home_address=home_address,
            home_phone=home_phone,
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
    )

    if old_family_id and old_family_id != family.id:
        previous_family = session.exec(
            select(Family)
            .options(selectinload(Family.children), selectinload(Family.parent_accounts))
            .where(Family.id == old_family_id)
        ).first()
        if previous_family:
            sync_parent_child_links(session, previous_family)

    session.commit()
    return RedirectResponse(url="/children/", status_code=303)
