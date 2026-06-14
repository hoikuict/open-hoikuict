from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..auth_adapter import CurrentUser, require_can_edit, require_classroom_access
from ..auth_adapter import DEFAULT_CLASSROOM_REFS
from ..contracts import AGE_CLASS_OPTIONS, DocumentStatus, DocumentType
from ..services.generators import (
    generate_annual_plan,
    generate_daily_plan,
    generate_monthly_plan,
    generate_weekly_plan,
    week_start_date_from_target_week,
)
from ..store import document_store
from ..templating import render_template


router = APIRouter(tags=["plans"])


def _annual_documents_for_user(user: CurrentUser):
    classroom_refs = None if user.is_admin else user.classroom_refs
    return document_store.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=classroom_refs,
        document_type=DocumentType.ANNUAL_PLAN,
    )


def _documents_for_user(
    user: CurrentUser,
    document_type: DocumentType,
    *,
    classroom_ref: str | None = None,
    limit: int = 8,
):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = document_store.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=classroom_refs,
        document_type=document_type,
    )
    if classroom_ref:
        documents = [document for document in documents if document.classroom_ref == classroom_ref]
    documents = [document for document in documents if document.status != DocumentStatus.ARCHIVED]
    return documents[:limit]


def _monthly_documents_for_user(user: CurrentUser, *, classroom_ref: str | None = None, limit: int = 8):
    return _documents_for_user(user, DocumentType.MONTHLY_PLAN, classroom_ref=classroom_ref, limit=limit)


def _weekly_documents_for_user(user: CurrentUser, *, classroom_ref: str | None = None, limit: int = 8):
    return _documents_for_user(user, DocumentType.WEEKLY_PLAN, classroom_ref=classroom_ref, limit=limit)


def _resolve_parent_document_id(
    raw_value: str,
    *,
    user: CurrentUser,
    classroom_ref: str,
    expected_type: DocumentType,
) -> tuple[str, str]:
    value = (raw_value or "").strip()
    if not value:
        return "", "上位計画の接続未確認"
    try:
        document_id = int(value)
    except ValueError:
        return "", "上位計画の接続未確認"
    document = document_store.get(document_id)
    if (
        document is None
        or document.nursery_ref != user.nursery_ref
        or document.classroom_ref != classroom_ref
        or document.document_type != expected_type
    ):
        return "", "上位計画の接続未確認"
    return str(document.id), ""


def _form_values(**values: str) -> dict[str, str]:
    return {key: value for key, value in values.items()}


@router.get("/annual-plans/new")
def new_annual_plan(request: Request, user: CurrentUser):
    return render_template(
        request,
        "annual_plans/form.html",
        user=user,
        default_classroom_ref=user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0],
    )


@router.post("/annual-plans")
def create_annual_plan(
    request: Request,
    user: CurrentUser,
    school_year: Annotated[str, Form()] = "2026",
    class_name: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    class_outlook: Annotated[str, Form()] = "",
    focus_growth: Annotated[str, Form()] = "",
    annual_events: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    care_points: Annotated[str, Form()] = "",
    family_collaboration_policy: Annotated[str, Form()] = "",
    health_safety_policy: Annotated[str, Form()] = "",
    preferred_expressions: Annotated[str, Form()] = "",
    term_1_note: Annotated[str, Form()] = "",
    term_2_note: Annotated[str, Form()] = "",
    term_3_note: Annotated[str, Form()] = "",
    term_4_note: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or class_name or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    selected_class_name = class_name or selected_classroom_ref
    require_classroom_access(user, selected_classroom_ref)
    document = generate_annual_plan(
        {
            "school_year": school_year,
            "class_name": selected_class_name,
            "classroom_ref": selected_classroom_ref,
            "owner_name": owner_name,
            "class_outlook": class_outlook,
            "focus_growth": focus_growth,
            "annual_events": annual_events,
            "seasonal_context": seasonal_context,
            "care_points": care_points,
            "family_collaboration_policy": family_collaboration_policy,
            "health_safety_policy": health_safety_policy,
            "preferred_expressions": preferred_expressions,
            "term_1_note": term_1_note,
            "term_2_note": term_2_note,
            "term_3_note": term_3_note,
            "term_4_note": term_4_note,
        },
        user,
    )
    created = document_store.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/monthly-plans/new")
def new_monthly_plan(request: Request, user: CurrentUser):
    return render_template(
        request,
        "monthly_plans/form.html",
        user=user,
        annual_documents=_annual_documents_for_user(user),
        default_classroom_ref=user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0],
    )


@router.post("/monthly-plans")
def create_monthly_plan(
    request: Request,
    user: CurrentUser,
    target_month: Annotated[str, Form()] = "",
    class_name: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    related_annual_summary: Annotated[str, Form()] = "",
    previous_reflection: Annotated[str, Form()] = "",
    current_children_snapshot: Annotated[str, Form()] = "",
    play_interests: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    family_context: Annotated[str, Form()] = "",
    class_notes: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or class_name or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    selected_class_name = class_name or selected_classroom_ref
    require_classroom_access(user, selected_classroom_ref)
    document = generate_monthly_plan(
        {
            "target_month": target_month,
            "class_name": selected_class_name,
            "classroom_ref": selected_classroom_ref,
            "owner_name": owner_name,
            "related_annual_summary": related_annual_summary,
            "previous_reflection": previous_reflection,
            "current_children_snapshot": current_children_snapshot,
            "play_interests": play_interests,
            "seasonal_context": seasonal_context,
            "family_context": family_context,
            "class_notes": class_notes,
        },
        user,
    )
    created = document_store.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/weekly-plans/new")
def new_weekly_plan(request: Request, user: CurrentUser):
    default_classroom_ref = user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0]
    return render_template(
        request,
        "weekly_plans/form.html",
        user=user,
        default_classroom_ref=default_classroom_ref,
        age_class_options=AGE_CLASS_OPTIONS,
        monthly_documents=_monthly_documents_for_user(user, classroom_ref=default_classroom_ref),
        errors=[],
        form_values={},
    )


@router.post("/weekly-plans")
def create_weekly_plan(
    request: Request,
    user: CurrentUser,
    target_week: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    age_class: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    parent_document_id: Annotated[str, Form()] = "",
    related_monthly_summary: Annotated[str, Form()] = "",
    previous_week_reflection: Annotated[str, Form()] = "",
    current_children_snapshot: Annotated[str, Form()] = "",
    weekly_activities_note: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    family_context: Annotated[str, Form()] = "",
    class_notes: Annotated[str, Form()] = "",
    include_saturday: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    require_classroom_access(user, selected_classroom_ref)
    selected_class_name = selected_classroom_ref
    errors: list[str] = []
    if not target_week:
        errors.append("対象週を選択してください。")
    else:
        try:
            week_start_date_from_target_week(target_week)
        except ValueError:
            errors.append("対象週を正しい形式で選択してください。")
    if not age_class:
        errors.append("年齢を選択してください。")
    resolved_parent_id, connection_warning = _resolve_parent_document_id(
        parent_document_id,
        user=user,
        classroom_ref=selected_classroom_ref,
        expected_type=DocumentType.MONTHLY_PLAN,
    )
    if not parent_document_id and related_monthly_summary.strip():
        connection_warning = ""
    values = _form_values(
        target_week=target_week,
        classroom_ref=selected_classroom_ref,
        age_class=age_class,
        owner_name=owner_name,
        parent_document_id=parent_document_id,
        related_monthly_summary=related_monthly_summary,
        previous_week_reflection=previous_week_reflection,
        current_children_snapshot=current_children_snapshot,
        weekly_activities_note=weekly_activities_note,
        seasonal_context=seasonal_context,
        family_context=family_context,
        class_notes=class_notes,
        include_saturday=include_saturday,
    )
    if errors:
        return render_template(
            request,
            "weekly_plans/form.html",
            user=user,
            default_classroom_ref=selected_classroom_ref,
            age_class_options=AGE_CLASS_OPTIONS,
            monthly_documents=_monthly_documents_for_user(user, classroom_ref=selected_classroom_ref),
            errors=errors,
            form_values=values,
        )
    document = generate_weekly_plan(
        {
            **values,
            "class_name": selected_class_name,
            "parent_document_id": resolved_parent_id,
            "connection_warning": connection_warning,
        },
        user,
    )
    created = document_store.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/daily-plans/new")
def new_daily_plan(request: Request, user: CurrentUser):
    default_classroom_ref = user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0]
    return render_template(
        request,
        "daily_plans/form.html",
        user=user,
        default_classroom_ref=default_classroom_ref,
        age_class_options=AGE_CLASS_OPTIONS,
        weekly_documents=_weekly_documents_for_user(user, classroom_ref=default_classroom_ref),
        errors=[],
        form_values={},
    )


@router.post("/daily-plans")
def create_daily_plan(
    request: Request,
    user: CurrentUser,
    target_date: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    age_class: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    parent_document_id: Annotated[str, Form()] = "",
    related_weekly_summary: Annotated[str, Form()] = "",
    current_children_snapshot: Annotated[str, Form()] = "",
    daily_main_activity_note: Annotated[str, Form()] = "",
    seasonal_context: Annotated[str, Form()] = "",
    health_notes: Annotated[str, Form()] = "",
    family_context: Annotated[str, Form()] = "",
):
    require_can_edit(user, request)
    selected_classroom_ref = classroom_ref or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0])
    require_classroom_access(user, selected_classroom_ref)
    selected_class_name = selected_classroom_ref
    errors: list[str] = []
    if not target_date:
        errors.append("対象日を選択してください。")
    else:
        try:
            from datetime import date

            date.fromisoformat(target_date)
        except ValueError:
            errors.append("対象日を正しい形式で選択してください。")
    if not age_class:
        errors.append("年齢を選択してください。")
    resolved_parent_id, connection_warning = _resolve_parent_document_id(
        parent_document_id,
        user=user,
        classroom_ref=selected_classroom_ref,
        expected_type=DocumentType.WEEKLY_PLAN,
    )
    if not parent_document_id and related_weekly_summary.strip():
        connection_warning = ""
    values = _form_values(
        target_date=target_date,
        classroom_ref=selected_classroom_ref,
        age_class=age_class,
        owner_name=owner_name,
        parent_document_id=parent_document_id,
        related_weekly_summary=related_weekly_summary,
        current_children_snapshot=current_children_snapshot,
        daily_main_activity_note=daily_main_activity_note,
        seasonal_context=seasonal_context,
        health_notes=health_notes,
        family_context=family_context,
    )
    if errors:
        return render_template(
            request,
            "daily_plans/form.html",
            user=user,
            default_classroom_ref=selected_classroom_ref,
            age_class_options=AGE_CLASS_OPTIONS,
            weekly_documents=_weekly_documents_for_user(user, classroom_ref=selected_classroom_ref),
            errors=errors,
            form_values=values,
        )
    document = generate_daily_plan(
        {
            **values,
            "class_name": selected_class_name,
            "parent_document_id": resolved_parent_id,
            "connection_warning": connection_warning,
        },
        user,
    )
    created = document_store.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)
