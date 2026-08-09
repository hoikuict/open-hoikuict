from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from ..auth_adapter import CurrentUser, require_can_edit, require_classroom_access
from ..auth_adapter import DEFAULT_CLASSROOM_REFS
from ..contracts import AGE_CLASS_OPTIONS, DocumentStatus, DocumentType
from ..services.generators import (
    generate_annual_plan,
    generate_monthly_plan,
    generate_simple_daily_plan,
    generate_weekly_plan,
    week_start_date_from_target_week,
)
from ..services.daily_examples import (
    DailyExampleCorpusError,
    corpus_metadata,
    get_daily_plan_example,
    list_daily_plan_examples,
)
from ..store import DocumentRepositoryDep, SqlModelDocumentRepository
from ..templating import render_template
from time_utils import local_today


router = APIRouter(tags=["plans"])


def _annual_documents_for_user(user: CurrentUser, repository: SqlModelDocumentRepository):
    classroom_refs = None if user.is_admin else user.classroom_refs
    return repository.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=classroom_refs,
        document_type=DocumentType.ANNUAL_PLAN,
    )


def _documents_for_user(
    user: CurrentUser,
    repository: SqlModelDocumentRepository,
    document_type: DocumentType,
    *,
    classroom_ref: str | None = None,
    limit: int = 8,
):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = repository.list(
        nursery_ref=user.nursery_ref,
        classroom_refs=classroom_refs,
        document_type=document_type,
    )
    if classroom_ref:
        documents = [document for document in documents if document.classroom_ref == classroom_ref]
    documents = [document for document in documents if document.status != DocumentStatus.ARCHIVED]
    return documents[:limit]


def _monthly_documents_for_user(user: CurrentUser, repository: SqlModelDocumentRepository, *, classroom_ref: str | None = None, limit: int = 8):
    return _documents_for_user(user, repository, DocumentType.MONTHLY_PLAN, classroom_ref=classroom_ref, limit=limit)


def _weekly_documents_for_user(user: CurrentUser, repository: SqlModelDocumentRepository, *, classroom_ref: str | None = None, limit: int = 8):
    return _documents_for_user(user, repository, DocumentType.WEEKLY_PLAN, classroom_ref=classroom_ref, limit=limit)


def _resolve_parent_document_id(
    raw_value: str,
    *,
    user: CurrentUser,
    repository: SqlModelDocumentRepository,
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
    document = repository.get(document_id)
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


def _list_value(values: list[str], index: int) -> str:
    return values[index] if index < len(values) else ""


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
    repository: DocumentRepositoryDep,
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
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/monthly-plans/new")
def new_monthly_plan(request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    return render_template(
        request,
        "monthly_plans/form.html",
        user=user,
        annual_documents=_annual_documents_for_user(user, repository),
        default_classroom_ref=user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0],
    )


@router.post("/monthly-plans")
def create_monthly_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
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
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/weekly-plans/new")
def new_weekly_plan(request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    default_classroom_ref = user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0]
    return render_template(
        request,
        "weekly_plans/form.html",
        user=user,
        default_classroom_ref=default_classroom_ref,
        age_class_options=AGE_CLASS_OPTIONS,
        monthly_documents=_monthly_documents_for_user(user, repository, classroom_ref=default_classroom_ref),
        errors=[],
        form_values={},
    )


@router.post("/weekly-plans")
def create_weekly_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
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
        repository=repository,
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
            monthly_documents=_monthly_documents_for_user(user, repository, classroom_ref=selected_classroom_ref),
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
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@router.get("/daily-plans/new")
def new_daily_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    age_class: str = "",
    month: int | None = None,
    q: str = "",
    example_id: str = "",
):
    default_classroom_ref = user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0]
    selected_month = month if month is not None and 1 <= month <= 12 else local_today().month
    selected_example = None
    examples = []
    corpus_info: dict[str, str] = {}
    corpus_error = ""
    try:
        examples = list_daily_plan_examples(
            age_class=age_class or None,
            month=selected_month,
            query=q,
        )
        selected_example = get_daily_plan_example(example_id) if example_id else None
        corpus_info = corpus_metadata()
    except DailyExampleCorpusError as exc:
        corpus_error = str(exc)
    values = {
        "age_class": age_class,
        "daily_aims": "\n".join(selected_example.aims) if selected_example else "",
        "daily_content": selected_example.content if selected_example else "",
        "example_id": selected_example.id if selected_example else "",
        "example_source_ref": selected_example.source_ref if selected_example else "",
        "timeline_rows": [
            {
                "row_key": f"corpus_{block.position + 1}",
                "time_label": block.time_label,
                "activity_name": " / ".join(
                    value
                    for value in (block.activity_name, block.activity_text)
                    if value
                ),
                "child_state": block.child_state,
                "support": block.support,
                "considerations": block.considerations,
            }
            for block in selected_example.activity_blocks
        ]
        if selected_example
        else [
            {
                "row_key": "row_1",
                "time_label": "",
                "activity_name": "",
                "child_state": "",
                "support": "",
                "considerations": "",
            }
        ],
    }
    return render_template(
        request,
        "daily_plans/form.html",
        user=user,
        default_classroom_ref=default_classroom_ref,
        age_class_options=AGE_CLASS_OPTIONS,
        weekly_documents=[],
        errors=[],
        form_values=values,
        examples=examples,
        selected_month=selected_month,
        search_query=q,
        corpus_info=corpus_info,
        corpus_error=corpus_error,
    )


@router.post("/daily-plans")
def create_daily_plan(
    request: Request,
    user: CurrentUser,
    repository: DocumentRepositoryDep,
    target_date: Annotated[str, Form()] = "",
    classroom_ref: Annotated[str, Form()] = "",
    age_class: Annotated[str, Form()] = "",
    owner_name: Annotated[str, Form()] = "",
    daily_aims: Annotated[str, Form()] = "",
    daily_content: Annotated[str, Form()] = "",
    timeline_row_key: Annotated[list[str], Form()] = [],
    timeline_time: Annotated[list[str], Form()] = [],
    timeline_activity: Annotated[list[str], Form()] = [],
    timeline_children: Annotated[list[str], Form()] = [],
    timeline_support: Annotated[list[str], Form()] = [],
    timeline_considerations: Annotated[list[str], Form()] = [],
    example_id: Annotated[str, Form()] = "",
    example_source_ref: Annotated[str, Form()] = "",
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
    row_count = max(
        len(timeline_row_key),
        len(timeline_time),
        len(timeline_activity),
        len(timeline_children),
        len(timeline_support),
        len(timeline_considerations),
    )
    timeline_rows = [
        {
            "row_key": _list_value(timeline_row_key, index) or f"row_{index + 1}",
            "time_label": _list_value(timeline_time, index),
            "activity_name": _list_value(timeline_activity, index),
            "child_state": _list_value(timeline_children, index),
            "support": _list_value(timeline_support, index),
            "considerations": _list_value(timeline_considerations, index),
        }
        for index in range(row_count)
    ]
    if not any(
        any(str(row[key]).strip() for key in ("time_label", "activity_name", "child_state", "support", "considerations"))
        for row in timeline_rows
    ):
        errors.append("1日の流れを1行以上入力してください。")
    selected_example = None
    if example_id:
        try:
            selected_example = get_daily_plan_example(example_id)
        except DailyExampleCorpusError:
            selected_example = None
    values = _form_values(
        target_date=target_date,
        classroom_ref=selected_classroom_ref,
        age_class=age_class,
        owner_name=owner_name,
        daily_aims=daily_aims,
        daily_content=daily_content,
        example_id=selected_example.id if selected_example else "",
        example_source_ref=(selected_example.source_ref if selected_example else example_source_ref),
    )
    values["timeline_rows"] = timeline_rows or [
        {
            "row_key": "row_1",
            "time_label": "",
            "activity_name": "",
            "child_state": "",
            "support": "",
            "considerations": "",
        }
    ]
    if errors:
        return render_template(
            request,
            "daily_plans/form.html",
            user=user,
            default_classroom_ref=selected_classroom_ref,
            age_class_options=AGE_CLASS_OPTIONS,
            weekly_documents=[],
            errors=errors,
            form_values=values,
            examples=[],
            selected_month=local_today().month,
            search_query="",
            corpus_info={},
            corpus_error="",
        )
    document = generate_simple_daily_plan(
        {
            **values,
            "class_name": selected_class_name,
        },
        user,
    )
    created = repository.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)
