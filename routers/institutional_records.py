from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from auth import get_current_staff_user, require_can_edit
from database import get_session
from institutional_record_service import (
    add_highlight_comment,
    add_link,
    add_review,
    add_series_member,
    archive_highlight,
    assert_target_access,
    change_record_visibility,
    create_event_series,
    create_highlight,
    create_record,
    list_event_series,
    list_visible_records,
    load_event_series,
    load_record_for_view,
    promote_highlight,
    records_for_event_series,
    remove_link,
    resolve_link_labels,
    retire_record,
    series_members,
    update_record,
)
from models import (
    EventSeriesMemberTargetType,
    HighlightSourceType,
    InstitutionalRecordOrigin,
    InstitutionalRecordStatus,
    InstitutionalRecordVisibility,
    RecordLinkTargetType,
    RecordReviewDecision,
)
from template_utils import create_templates
from url_utils import safe_internal_redirect

router = APIRouter(prefix="/records", tags=["institutional-records"])
highlights_router = APIRouter(prefix="/highlights", tags=["record-highlights"])
event_series_router = APIRouter(prefix="/event-series", tags=["event-series"])
templates = create_templates()


def _enum_value(enum_class, raw_value: str, *, field_label: str):
    try:
        return enum_class(raw_value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_label}が正しくありません") from None


def _optional_date(raw_value: str, *, field_label: str) -> date | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"{field_label}が正しくありません") from None


def _optional_year(raw_value: str) -> int | None:
    value = (raw_value or "").strip()
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        raise HTTPException(status_code=400, detail="対象年度が正しくありません") from None


def _form_context(*, record=None, action_url: str, submit_label: str, current_user, **extra):
    return {
        "record": record,
        "action_url": action_url,
        "submit_label": submit_label,
        "current_user": current_user,
        "origin_options": list(InstitutionalRecordOrigin),
        "visibility_options": list(InstitutionalRecordVisibility),
        "target_type_options": [
            item for item in RecordLinkTargetType if item != RecordLinkTargetType.event_series
        ],
        **extra,
    }


@router.get("/", response_class=HTMLResponse)
def record_list(
    request: Request,
    origin: str = Query(default="all"),
    status: str = Query(default="active"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    origin_filter = None
    if origin != "all":
        origin_filter = _enum_value(InstitutionalRecordOrigin, origin, field_label="由来")
    status_filter = None
    if status != "all":
        status_filter = _enum_value(InstitutionalRecordStatus, status, field_label="状態")
    records = list_visible_records(
        session,
        current_user,
        origin=origin_filter,
        status=status_filter,
    )
    return templates.TemplateResponse(
        request,
        "institutional_records/list.html",
        {
            "request": request,
            "records": records,
            "current_user": current_user,
            "origin_options": list(InstitutionalRecordOrigin),
            "status_options": list(InstitutionalRecordStatus),
            "current_origin": origin,
            "current_status": status,
        },
    )


@router.get("/new", response_class=HTMLResponse)
def new_record_form(
    request: Request,
    target_type: str = Query(default=""),
    target_id: str = Query(default=""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    del session
    require_can_edit(current_user)
    selected_visibility = (
        InstitutionalRecordVisibility.linked_targets.value
        if target_type and target_id
        else InstitutionalRecordVisibility.staff.value
    )
    return templates.TemplateResponse(
        request,
        "institutional_records/form.html",
        {
            "request": request,
            **_form_context(
                record=None,
                action_url="/records/",
                submit_label="経緯レコードを作成",
                current_user=current_user,
                initial_target_type=target_type,
                initial_target_id=target_id,
                initial_link_enabled=bool(target_type and target_id),
                selected_visibility=selected_visibility,
            ),
        },
    )


@router.post("/")
def create_record_action(
    title: str = Form(...),
    origin: str = Form(...),
    background: str = Form(...),
    purpose: str = Form(...),
    visibility: str = Form(InstitutionalRecordVisibility.staff.value),
    revisit_condition: str = Form(""),
    occurred_on: str = Form(""),
    fiscal_year: str = Form(""),
    review_due_on: str = Form(""),
    include_initial_link: str = Form(""),
    initial_target_type: str = Form(""),
    initial_target_id: str = Form(""),
    initial_target_label: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    parsed_target_type = (
        _enum_value(RecordLinkTargetType, initial_target_type, field_label="リンク種別")
        if include_initial_link == "yes" and initial_target_type
        else None
    )
    record = create_record(
        session,
        current_user,
        title=title,
        origin=_enum_value(InstitutionalRecordOrigin, origin, field_label="由来"),
        background=background,
        purpose=purpose,
        visibility=_enum_value(InstitutionalRecordVisibility, visibility, field_label="可視性"),
        revisit_condition=revisit_condition,
        occurred_on=_optional_date(occurred_on, field_label="発生日"),
        fiscal_year=_optional_year(fiscal_year),
        review_due_on=_optional_date(review_due_on, field_label="次回確認日"),
        initial_target_type=parsed_target_type,
        initial_target_id=initial_target_id,
        initial_target_label=initial_target_label,
    )
    session.commit()
    return RedirectResponse(url=f"/records/{record.id}", status_code=303)


@router.get("/{record_id}", response_class=HTMLResponse)
def record_detail(
    record_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    record = load_record_for_view(session, current_user, record_id)
    link_labels = resolve_link_labels(session, current_user, list(record.links))
    revisions = sorted(record.revisions, key=lambda item: item.revision_no, reverse=True)
    record_series_links = list(record.series_links)
    record_series_by_id = {
        link.series_id: load_event_series(session, link.series_id)
        for link in record_series_links
    }
    return templates.TemplateResponse(
        request,
        "institutional_records/detail.html",
        {
            "request": request,
            "record": record,
            "revisions": revisions,
            "link_labels": link_labels,
            "record_series_links": record_series_links,
            "record_series_by_id": record_series_by_id,
            "current_user": current_user,
            "visibility_options": list(InstitutionalRecordVisibility),
            "target_type_options": [
                item for item in RecordLinkTargetType if item != RecordLinkTargetType.event_series
            ],
        },
    )


@router.get("/{record_id}/edit", response_class=HTMLResponse)
def edit_record_form(
    record_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    record = load_record_for_view(session, current_user, record_id)
    if record.status != InstitutionalRecordStatus.active:
        raise HTTPException(status_code=409, detail="退役済みの経緯レコードは改訂できません")
    return templates.TemplateResponse(
        request,
        "institutional_records/form.html",
        {
            "request": request,
            **_form_context(
                record=record,
                action_url=f"/records/{record.id}/edit",
                submit_label="改訂を保存",
                current_user=current_user,
                initial_target_type="",
                initial_target_id="",
                initial_link_enabled=False,
                selected_visibility=record.visibility.value,
            ),
        },
    )


@router.post("/{record_id}/edit")
def edit_record_action(
    record_id: int,
    expected_revision_no: int = Form(...),
    change_note: str = Form(...),
    title: str = Form(...),
    origin: str = Form(...),
    background: str = Form(...),
    purpose: str = Form(...),
    revisit_condition: str = Form(""),
    occurred_on: str = Form(""),
    fiscal_year: str = Form(""),
    review_due_on: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    update_record(
        session,
        current_user,
        record_id,
        expected_revision_no=expected_revision_no,
        change_note=change_note,
        title=title,
        origin=_enum_value(InstitutionalRecordOrigin, origin, field_label="由来"),
        background=background,
        purpose=purpose,
        revisit_condition=revisit_condition,
        occurred_on=_optional_date(occurred_on, field_label="発生日"),
        fiscal_year=_optional_year(fiscal_year),
        review_due_on=_optional_date(review_due_on, field_label="次回確認日"),
    )
    session.commit()
    return RedirectResponse(url=f"/records/{record_id}", status_code=303)


@router.post("/{record_id}/visibility")
def change_visibility_action(
    record_id: int,
    new_visibility: str = Form(...),
    expected_revision_no: int = Form(...),
    change_note: str = Form(...),
    confirmed: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    if confirmed != "yes":
        raise HTTPException(status_code=400, detail="可視範囲を確認してください")
    change_record_visibility(
        session,
        current_user,
        record_id,
        new_visibility=_enum_value(
            InstitutionalRecordVisibility,
            new_visibility,
            field_label="可視性",
        ),
        expected_revision_no=expected_revision_no,
        change_note=change_note,
    )
    session.commit()
    return RedirectResponse(url=f"/records/{record_id}", status_code=303)


@router.post("/{record_id}/links")
def add_link_action(
    record_id: int,
    target_type: str = Form(...),
    target_id: str = Form(""),
    target_label: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    add_link(
        session,
        current_user,
        record_id,
        target_type=_enum_value(RecordLinkTargetType, target_type, field_label="リンク種別"),
        target_id=target_id,
        target_label=target_label,
    )
    session.commit()
    return RedirectResponse(url=f"/records/{record_id}", status_code=303)


@router.post("/{record_id}/links/{link_id}/delete")
def remove_link_action(
    record_id: int,
    link_id: int,
    confirmed: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    if confirmed != "yes":
        raise HTTPException(status_code=400, detail="リンク解除後の公開範囲を確認してください")
    remove_link(session, current_user, record_id, link_id)
    session.commit()
    return RedirectResponse(url=f"/records/{record_id}", status_code=303)


@router.post("/{record_id}/retire")
def retire_record_action(
    record_id: int,
    expected_revision_no: int = Form(...),
    change_note: str = Form(...),
    confirmed: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    if confirmed != "yes":
        raise HTTPException(status_code=400, detail="退役操作を確認してください")
    retire_record(
        session,
        current_user,
        record_id,
        expected_revision_no=expected_revision_no,
        change_note=change_note,
    )
    session.commit()
    return RedirectResponse(url=f"/records/{record_id}", status_code=303)


@router.post("/{record_id}/reviews")
def add_review_action(
    request: Request,
    record_id: int,
    series_member_id: int = Form(...),
    review_cycle_fiscal_year: int = Form(...),
    decision: str = Form(RecordReviewDecision.keep.value),
    note: str = Form(""),
    next_review_due_on: str = Form(""),
    redirect_to: str = Form("/calendar"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    add_review(
        session,
        current_user,
        record_id,
        series_member_id=series_member_id,
        review_cycle_fiscal_year=review_cycle_fiscal_year,
        decision=_enum_value(RecordReviewDecision, decision, field_label="確認結果"),
        note=note,
        next_review_due_on=_optional_date(next_review_due_on, field_label="次回確認日"),
    )
    session.commit()
    if request.headers.get("HX-Request", "").lower() == "true":
        return HTMLResponse(
            '<div class="rounded-lg bg-emerald-50 px-3 py-2 text-sm font-semibold '
            'text-emerald-700">今年度の確認済み</div>'
        )
    return RedirectResponse(url=safe_internal_redirect(redirect_to, "/calendar"), status_code=303)


@highlights_router.post("/")
def create_highlight_action(
    source_type: str = Form(HighlightSourceType.meeting_note.value),
    source_id: str = Form(...),
    excerpt: str = Form(...),
    origin: str = Form(InstitutionalRecordOrigin.retrospective.value),
    series_id: str = Form(""),
    fiscal_year: str = Form(""),
    comment: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    create_highlight(
        session,
        current_user,
        source_type=_enum_value(HighlightSourceType, source_type, field_label="マーキング元"),
        source_id=source_id,
        excerpt=excerpt,
        origin=_enum_value(InstitutionalRecordOrigin, origin, field_label="由来"),
        series_id=int(series_id) if series_id.strip() else None,
        fiscal_year=_optional_year(fiscal_year),
        comment=comment,
    )
    session.commit()
    return RedirectResponse(url=f"/meeting-notes/{int(source_id)}#markings", status_code=303)


@highlights_router.post("/{highlight_id}/comments")
def add_highlight_comment_action(
    highlight_id: int,
    body: str = Form(...),
    source_id: int = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    add_highlight_comment(session, current_user, highlight_id, body=body)
    session.commit()
    return RedirectResponse(url=f"/meeting-notes/{source_id}#markings", status_code=303)


@highlights_router.post("/{highlight_id}/promote")
def promote_highlight_action(
    highlight_id: int,
    source_id: int = Form(...),
    title: str = Form(...),
    purpose: str = Form(...),
    fiscal_year: str = Form(""),
    revisit_condition: str = Form(""),
    review_due_on: str = Form(""),
    visibility: str = Form(InstitutionalRecordVisibility.staff.value),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    record = promote_highlight(
        session,
        current_user,
        highlight_id,
        title=title,
        purpose=purpose,
        fiscal_year=_optional_year(fiscal_year),
        revisit_condition=revisit_condition,
        review_due_on=_optional_date(review_due_on, field_label="次回確認日"),
        visibility=_enum_value(
            InstitutionalRecordVisibility,
            visibility,
            field_label="可視性",
        ),
    )
    session.commit()
    return RedirectResponse(url=f"/records/{record.id}", status_code=303)


@highlights_router.post("/{highlight_id}/archive")
def archive_highlight_action(
    highlight_id: int,
    source_id: int = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    archive_highlight(session, current_user, highlight_id)
    session.commit()
    return RedirectResponse(url=f"/meeting-notes/{source_id}#markings", status_code=303)


@event_series_router.get("/", response_class=HTMLResponse)
def event_series_list(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    return templates.TemplateResponse(
        request,
        "event_series/list.html",
        {
            "request": request,
            "series_list": list_event_series(session, include_inactive=True),
            "current_user": current_user,
        },
    )


@event_series_router.post("/")
def create_event_series_action(
    name: str = Form(...),
    description: str = Form(""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    series = create_event_series(
        session,
        current_user,
        name=name,
        description=description,
    )
    session.commit()
    return RedirectResponse(url=f"/event-series/{series.id}", status_code=303)


@event_series_router.get("/{series_id}", response_class=HTMLResponse)
def event_series_detail(
    series_id: int,
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    series = load_event_series(session, series_id)
    members = series_members(session, series_id)
    member_labels: dict[int, str | None] = {}
    for member in members:
        try:
            snapshot = assert_target_access(
                session,
                current_user,
                member.target_type,
                member.target_id,
                action="view",
            )
            member_labels[member.id] = snapshot.label
        except HTTPException:
            member_labels[member.id] = None
    return templates.TemplateResponse(
        request,
        "event_series/detail.html",
        {
            "request": request,
            "series": series,
            "members": members,
            "member_labels": member_labels,
            "linked_records": records_for_event_series(session, current_user, series_id),
            "target_type_options": list(EventSeriesMemberTargetType),
            "current_user": current_user,
        },
    )


@event_series_router.post("/{series_id}/members")
def add_event_series_member_action(
    series_id: int,
    target_type: str = Form(...),
    target_id: str = Form(...),
    fiscal_year: int = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    add_series_member(
        session,
        current_user,
        series_id,
        target_type=_enum_value(
            EventSeriesMemberTargetType,
            target_type,
            field_label="対象種別",
        ),
        target_id=target_id,
        fiscal_year=fiscal_year,
    )
    session.commit()
    return RedirectResponse(url=f"/event-series/{series_id}", status_code=303)
