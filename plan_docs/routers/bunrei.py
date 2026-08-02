from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response

from ..auth_adapter import DEFAULT_CLASSROOM_REFS, CurrentUser, require_can_edit, require_classroom_access
from ..contracts import DocumentType, annual_section_definitions
from ..services.bunrei import (
    add_facility_example,
    age_class_options,
    annual_candidate_groups,
    build_document_from_bunrei,
    count_examples,
    facility_import_template_csv,
    facility_import_template_xlsx,
    facility_item_options,
    import_facility_examples,
    is_bunrei_available,
    monthly_candidate_groups,
    selected_examples,
)
from ..store import document_store
from ..templating import render_template


router = APIRouter(prefix="/bunrei", tags=["bunrei"])


@router.get("/facility/new")
def new_facility_bunrei(
    request: Request,
    user: CurrentUser,
    imported: int | None = None,
    skipped: int | None = None,
    masked: int | None = None,
):
    _ensure_available()
    require_can_edit(user, request)
    age_options = sorted(set(age_class_options("月案")) | set(age_class_options("年案")))
    return render_template(
        request,
        "bunrei/facility_new.html",
        user=user,
        age_options=age_options,
        item_options=facility_item_options(),
        month_options=[4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3],
        import_result={
            "imported": imported,
            "skipped": skipped,
            "masked": masked,
        } if imported is not None else None,
    )


@router.get("/facility/import-template.csv")
def facility_bunrei_csv_template(request: Request, user: CurrentUser):
    require_can_edit(user, request)
    return Response(
        content=facility_import_template_csv(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="facility_bunrei_template.csv"'},
    )


@router.get("/facility/import-template.xlsx")
def facility_bunrei_xlsx_template(request: Request, user: CurrentUser):
    require_can_edit(user, request)
    return Response(
        content=facility_import_template_xlsx(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="facility_bunrei_template.xlsx"'},
    )


@router.post("/facility")
async def create_facility_bunrei(request: Request, user: CurrentUser):
    _ensure_available()
    require_can_edit(user, request)
    form = await request.form()
    plan_type = str(form.get("plan_type") or "月案")
    age_class = str(form.get("age_class") or "5歳児")
    item = str(form.get("item") or "活動内容")
    month_raw = str(form.get("month") or "").strip()
    month = int(month_raw) if month_raw.isdigit() else None
    try:
        add_facility_example(
            nursery_ref=user.nursery_ref,
            plan_type=plan_type,
            age_class=age_class,
            month=month,
            item=item,
            ryoiki=str(form.get("ryoiki") or "").strip() or None,
            text=str(form.get("text") or ""),
            source_note=str(form.get("source_note") or "").strip() or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if plan_type == "年案":
        query = urlencode({"age_class": age_class})
        return RedirectResponse(url=f"/plans/bunrei/annual?{query}", status_code=303)
    query = urlencode({"age_class": age_class, "month": month or 4})
    return RedirectResponse(url=f"/plans/bunrei/monthly?{query}", status_code=303)


@router.post("/facility/import")
async def import_facility_bunrei(
    request: Request,
    user: CurrentUser,
    file: UploadFile = File(...),
    default_plan_type: str = Form("月案"),
    default_age_class: str = Form("5歳児"),
    default_month: str = Form(""),
    default_item: str = Form("活動内容"),
    default_source_note: str = Form(""),
):
    _ensure_available()
    require_can_edit(user, request)
    content = await file.read()
    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="5MB以下のCSVまたはExcelファイルを選択してください")
    month_value = int(default_month) if default_month.isdigit() else None
    try:
        result = import_facility_examples(
            nursery_ref=user.nursery_ref,
            filename=file.filename or "",
            content=content,
            default_plan_type=default_plan_type,
            default_age_class=default_age_class,
            default_month=month_value,
            default_item=default_item,
            default_source_note=default_source_note or None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    query = urlencode(
        {
            "imported": result.imported,
            "skipped": result.skipped,
            "masked": result.masked_rows,
        }
    )
    return RedirectResponse(url=f"/plans/bunrei/facility/new?{query}", status_code=303)


@router.get("/monthly")
def monthly_bunrei_selector(
    request: Request,
    user: CurrentUser,
    age_class: str = "5歳児",
    month: int = 4,
):
    _ensure_available()
    return render_template(
        request,
        "bunrei/monthly.html",
        user=user,
        age_options=age_class_options("月案"),
        selected_age_class=age_class,
        selected_month=month,
        month_options=[4, 5, 6, 7, 8, 9, 10, 11, 12, 1, 2, 3],
        groups=monthly_candidate_groups(age_class, month, nursery_ref=user.nursery_ref),
        total_examples=count_examples(),
        default_classroom_ref=user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0],
    )


@router.post("/monthly")
async def create_monthly_from_bunrei(request: Request, user: CurrentUser):
    _ensure_available()
    require_can_edit(user, request)
    form = await request.form()
    target_month = str(form.get("target_month") or "2026-04")
    classroom_ref = str(form.get("classroom_ref") or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0]))
    class_name = str(form.get("class_name") or classroom_ref).strip()
    owner_name = str(form.get("owner_name") or user.name).strip()
    require_classroom_access(user, classroom_ref)

    selection = {
        section_key.removeprefix("section_"): list(form.getlist(section_key))
        for section_key in form
        if section_key.startswith("section_")
    }
    selected_by_section = selected_examples(selection, nursery_ref=user.nursery_ref)
    groups = monthly_candidate_groups(
        str(form.get("age_class") or "5歳児"),
        int(form.get("month") or 4),
        nursery_ref=user.nursery_ref,
        limit_per_section=1,
    )
    definitions = [
        _definition(group.section_key, group.section_title)
        for group in groups
    ]
    document = build_document_from_bunrei(
        document_type=DocumentType.MONTHLY_PLAN,
        title=f"{target_month} 月案（{class_name}）",
        owner_name=owner_name,
        classroom_ref=classroom_ref,
        user=user,
        section_definitions=definitions,
        selected_by_section=selected_by_section,
        target_month=target_month,
    )
    created = document_store.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}/edit", status_code=303)


@router.get("/annual")
def annual_bunrei_selector(
    request: Request,
    user: CurrentUser,
    age_class: str = "5歳児",
    school_year: int = 2026,
):
    _ensure_available()
    return render_template(
        request,
        "bunrei/annual.html",
        user=user,
        age_options=age_class_options("年案"),
        selected_age_class=age_class,
        school_year=school_year,
        groups=annual_candidate_groups(age_class, nursery_ref=user.nursery_ref),
        total_examples=count_examples(),
        default_classroom_ref=user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0],
    )


@router.post("/annual")
async def create_annual_from_bunrei(request: Request, user: CurrentUser):
    _ensure_available()
    require_can_edit(user, request)
    form = await request.form()
    school_year = int(form.get("school_year") or 2026)
    classroom_ref = str(form.get("classroom_ref") or (user.classroom_refs[0] if user.classroom_refs else DEFAULT_CLASSROOM_REFS[0]))
    class_name = str(form.get("class_name") or classroom_ref).strip()
    owner_name = str(form.get("owner_name") or user.name).strip()
    require_classroom_access(user, classroom_ref)

    selection = {
        section_key.removeprefix("section_"): list(form.getlist(section_key))
        for section_key in form
        if section_key.startswith("section_")
    }
    document = build_document_from_bunrei(
        document_type=DocumentType.ANNUAL_PLAN,
        title=f"{school_year}年度 年案（{class_name}）",
        owner_name=owner_name,
        classroom_ref=classroom_ref,
        user=user,
        section_definitions=annual_section_definitions(),
        selected_by_section=selected_examples(selection, nursery_ref=user.nursery_ref),
        school_year=school_year,
    )
    created = document_store.create(document)
    return RedirectResponse(url=f"/plans/documents/{created.id}/edit", status_code=303)


def _definition(section_key: str, section_title: str):
    from ..contracts import SectionDefinition

    return SectionDefinition(section_key, section_title, "文例選択")


def _ensure_available() -> None:
    if not is_bunrei_available():
        raise HTTPException(status_code=503, detail="文例データベースが見つかりません")
