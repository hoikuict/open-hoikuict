from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import (
    StaffUser,
    get_current_staff_user,
    require_admin,
    require_can_edit,
)
from database import get_session
from models import Child, ChildStatus, StaffClassroomAssignment
from template_utils import create_templates
from time_utils import local_today, utc_now
from plan_docs.auth_adapter import DEFAULT_NURSERY_REF
from plan_docs.contracts import (
    DocumentStatus,
    DocumentType,
    section_definitions,
)
from plan_docs.db_models import PlanDocumentRow
from plan_docs.models import PlanDocument, SectionBlock
from plan_docs.store import SqlModelDocumentRepository

from .models import (
    ChildObservationLog,
    ChildObservationLogRevision,
    ChildRecordSettingVersion,
)
from .settings import (
    AGE_RULES,
    CATEGORY_OPTIONS,
    PERSPECTIVE_OPTIONS,
    PRESET_LABELS,
    custom_field_key,
    default_config,
    effective_config,
    enabled_fields,
    field_map,
)


router = APIRouter(prefix="/children", tags=["child-records"])
settings_router = APIRouter(prefix="/settings/child-records", tags=["child-record-settings"])
progress_router = APIRouter(prefix="/child-records", tags=["child-progress-records"])
templates = create_templates()

PROGRESS_STATUS_LABELS = {
    "draft": "下書き",
    "in_review": "レビュー待ち",
    "approved": "承認済み",
    "rejected": "差戻し",
    "archived": "アーカイブ",
}

PROGRESS_FILTER_STATUS_OPTIONS = (
    ("uncreated", "未作成"),
    ("created", "作成済み（すべて）"),
    *tuple(PROGRESS_STATUS_LABELS.items()),
)


def _load_child(session: Session, child_id: int) -> Child:
    child = session.exec(
        select(Child)
        .options(selectinload(Child.classroom))
        .where(Child.id == child_id)
    ).first()
    if child is None:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    return child


def _has_child_access(session: Session, user: StaffUser, child: Child) -> bool:
    if user.is_admin or user.can_manage_child_records:
        return True
    if user.user_id is None or child.classroom_id is None:
        return False
    today = local_today()
    assignment = session.exec(
        select(StaffClassroomAssignment).where(
            StaffClassroomAssignment.staff_user_id == user.user_id,
            StaffClassroomAssignment.classroom_id == child.classroom_id,
            StaffClassroomAssignment.starts_on <= today,
            (
                StaffClassroomAssignment.ends_on.is_(None)
                | (StaffClassroomAssignment.ends_on >= today)
            ),
        )
    ).first()
    return assignment is not None


def _require_child_access(session: Session, user: StaffUser, child: Child) -> None:
    if not _has_child_access(session, user, child):
        raise HTTPException(status_code=403, detail="この園児の記録を閲覧できません")


def _actor_id(user: StaffUser) -> str | None:
    return str(user.user_id) if user.user_id is not None else None


def _can_correct(user: StaffUser, log: ChildObservationLog) -> bool:
    return (
        user.is_admin
        or user.can_manage_child_records
        or (_actor_id(user) is not None and log.created_by == _actor_id(user))
    )


def _parse_date(raw: str, *, field_label: str) -> date:
    try:
        return date.fromisoformat((raw or "").strip())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"{field_label}を正しく入力してください") from exc


def _clean_text(raw: Any, *, max_length: int = 5000) -> str:
    value = str(raw or "").strip()
    if len(value) > max_length:
        raise HTTPException(status_code=422, detail=f"入力は{max_length}文字以内にしてください")
    return value


def _setting_versions(session: Session) -> list[ChildRecordSettingVersion]:
    return session.exec(
        select(ChildRecordSettingVersion).order_by(
            ChildRecordSettingVersion.version_no.desc()
        )
    ).all()


def _ensure_setting_for_record(
    session: Session,
    *,
    actor_id: str | None,
) -> ChildRecordSettingVersion:
    config, setting_id = effective_config(session)
    if setting_id is not None:
        setting = session.get(ChildRecordSettingVersion, setting_id)
        if setting is not None:
            return setting
    latest_version = session.exec(select(func.max(ChildRecordSettingVersion.version_no))).one()
    setting = ChildRecordSettingVersion(
        version_no=int(latest_version or 0) + 1,
        status="active",
        preset_key="standard",
        effective_from=date(2000, 1, 1),
        config=config,
        created_by=actor_id,
        activated_by=actor_id,
        activated_at=utc_now(),
    )
    session.add(setting)
    session.flush()
    return setting


@settings_router.get("", response_class=HTMLResponse)
@settings_router.get("/", response_class=HTMLResponse)
def child_record_settings(
    request: Request,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)
    config, active_setting_id = effective_config(session)
    return templates.TemplateResponse(
        request,
        "child_records/settings.html",
        {
            "request": request,
            "current_user": current_user,
            "config": config,
            "field_map": field_map(config),
            "age_rules": AGE_RULES,
            "preset_labels": PRESET_LABELS,
            "active_setting_id": active_setting_id,
            "versions": _setting_versions(session),
            "today": local_today().isoformat(),
        },
    )


@settings_router.post("")
@settings_router.post("/")
async def save_child_record_settings(
    request: Request,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_admin(current_user)
    form = await request.form()
    preset_key = str(form.get("preset_key") or "standard")
    config = default_config(preset_key)
    enabled_keys = {str(value) for value in form.getlist("enabled_fields")}
    required_keys = {str(value) for value in form.getlist("required_fields")}
    enabled_keys.update({"observed_on", "child_state", "sensitivity"})
    required_keys.update({"observed_on", "child_state"})

    fields = config["record_types"]["observation_log"]["fields"]
    for item in fields:
        key = item["key"]
        item["enabled"] = key in enabled_keys
        item["required"] = key in required_keys and item["enabled"]
        custom_label = _clean_text(form.get(f"label_{key}"), max_length=80)
        if custom_label:
            item["label"] = custom_label

    custom_labels = []
    for raw_label in str(form.get("custom_field_labels") or "").splitlines():
        label = _clean_text(raw_label, max_length=80)
        if label and label not in custom_labels:
            custom_labels.append(label)
    if len(custom_labels) > 10:
        raise HTTPException(status_code=422, detail="園独自項目は10件以内にしてください")
    for offset, label in enumerate(custom_labels, start=1):
        fields.append(
            {
                "key": custom_field_key(label),
                "label": label,
                "input_type": "long_text",
                "description": "園独自の記録項目です。",
                "enabled": True,
                "required": False,
                "order": 100 + offset * 10,
                "custom": True,
            }
        )

    for age_key, _, default_interval in AGE_RULES:
        raw_interval = str(form.get(f"interval_{age_key}") or default_interval)
        try:
            interval = int(raw_interval)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="記録頻度を正しく入力してください") from exc
        if not 1 <= interval <= 12:
            raise HTTPException(status_code=422, detail="記録頻度は1〜12か月で指定してください")
        config["age_rules"][age_key]["child_progress_record"]["interval_months"] = interval

    effective_from = _parse_date(
        str(form.get("effective_from") or ""), field_label="適用開始日"
    )
    same_date_rows = session.exec(
        select(ChildRecordSettingVersion).where(
            ChildRecordSettingVersion.status == "active",
            ChildRecordSettingVersion.effective_from == effective_from,
        )
    ).all()
    for row in same_date_rows:
        row.status = "retired"
        session.add(row)
    latest_version = session.exec(select(func.max(ChildRecordSettingVersion.version_no))).one()
    version_no = int(latest_version or 0) + 1
    setting = ChildRecordSettingVersion(
        version_no=version_no,
        status="active",
        preset_key=preset_key if preset_key in PRESET_LABELS else "standard",
        effective_from=effective_from,
        config=config,
        created_by=_actor_id(current_user),
        activated_by=_actor_id(current_user),
        activated_at=utc_now(),
    )
    session.add(setting)
    session.commit()
    return RedirectResponse(url="/settings/child-records?saved=1", status_code=303)


def _log_snapshot(log: ChildObservationLog) -> dict[str, Any]:
    return {
        "observed_on": log.observed_on.isoformat(),
        "child_state": log.child_state,
        "caregiver_support": log.caregiver_support,
        "reflection": log.reflection,
        "next_focus": log.next_focus,
        "family_note": log.family_note,
        "categories": list(log.categories or []),
        "perspective_tags": list(log.perspective_tags or []),
        "custom_values": dict(log.custom_values or {}),
        "sensitivity": log.sensitivity,
        "updated_at": log.updated_at.isoformat(),
    }


def _log_form_context(
    request: Request,
    *,
    child: Child,
    current_user: StaffUser,
    config: dict[str, Any],
    log: ChildObservationLog | None = None,
    error: str = "",
):
    return templates.TemplateResponse(
        request,
        "child_records/log_form.html",
        {
            "request": request,
            "current_user": current_user,
            "child": child,
            "log": log,
            "error": error,
            "fields": enabled_fields(config),
            "field_map": field_map(config),
            "categories": config.get("categories") or list(CATEGORY_OPTIONS),
            "perspective_tags": config.get("perspective_tags") or list(PERSPECTIVE_OPTIONS),
            "today": local_today().isoformat(),
            "is_correction": log is not None,
        },
        status_code=422 if error else 200,
    )


@router.get("/{child_id}/records", response_class=HTMLResponse)
def child_record_timeline(
    request: Request,
    child_id: int,
    category: str = Query(default=""),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    child = _load_child(session, child_id)
    if not _has_child_access(session, current_user, child):
        return RedirectResponse(
            url=f"/children/{child_id}?child_records_denied=1",
            status_code=303,
        )
    statement = select(ChildObservationLog).where(
        ChildObservationLog.child_id == child_id,
        ChildObservationLog.voided_at.is_(None),
    )
    if not current_user.is_admin:
        statement = statement.where(ChildObservationLog.sensitivity == "normal")
    logs = session.exec(
        statement.order_by(
            ChildObservationLog.observed_on.desc(),
            ChildObservationLog.created_at.desc(),
        )
    ).all()
    if category:
        logs = [log for log in logs if category in (log.categories or [])]
    config, _ = effective_config(session)
    setting_ids = {log.setting_version_id for log in logs if log.setting_version_id}
    settings_by_id = {
        setting.id: setting
        for setting in session.exec(
            select(ChildRecordSettingVersion).where(
                ChildRecordSettingVersion.id.in_(setting_ids)
            )
        ).all()
    } if setting_ids else {}
    custom_labels_by_log_id = {}
    for log in logs:
        setting = settings_by_id.get(log.setting_version_id)
        log_config = setting.config if setting else config
        custom_labels_by_log_id[log.id] = {
            key: str(item.get("label") or key)
            for key, item in field_map(log_config).items()
            if key.startswith("custom.")
        }
    return templates.TemplateResponse(
        request,
        "child_records/timeline.html",
        {
            "request": request,
            "current_user": current_user,
            "child": child,
            "logs": logs,
            "category": category,
            "categories": config.get("categories") or list(CATEGORY_OPTIONS),
            "can_add": current_user.can_edit,
            "can_view_restricted": current_user.is_admin,
            "custom_labels_by_log_id": custom_labels_by_log_id,
        },
    )


@router.get("/{child_id}/records/new", response_class=HTMLResponse)
def new_child_record_form(
    request: Request,
    child_id: int,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    if not _has_child_access(session, current_user, child):
        return RedirectResponse(
            url=f"/children/{child_id}?child_records_denied=1",
            status_code=303,
        )
    config, _ = effective_config(session)
    return _log_form_context(
        request,
        child=child,
        current_user=current_user,
        config=config,
    )


def _values_from_form(form: Any, config: dict[str, Any], user: StaffUser) -> dict[str, Any]:
    observed_on = _parse_date(str(form.get("observed_on") or ""), field_label="観察日")
    child_state = _clean_text(form.get("child_state"))
    if not child_state:
        raise ValueError("子どもの姿を入力してください")
    sensitivity = str(form.get("sensitivity") or "normal")
    if sensitivity not in {"normal", "restricted"}:
        sensitivity = "normal"
    if not user.is_admin:
        sensitivity = "normal"
    configured_fields = field_map(config)
    custom_values: dict[str, str] = {}
    for item in enabled_fields(config):
        key = str(item.get("key") or "")
        if not key.startswith("custom."):
            continue
        value = _clean_text(form.get(f"custom_{key.removeprefix('custom.')}"))
        if item.get("required") and not value:
            raise ValueError(f"{item.get('label', '園独自項目')}を入力してください")
        if value:
            custom_values[key] = value
    values = {
        "observed_on": observed_on,
        "child_state": child_state,
        "caregiver_support": (
            _clean_text(form.get("caregiver_support")) or None
            if configured_fields.get("caregiver_support", {}).get("enabled")
            else None
        ),
        "reflection": (
            _clean_text(form.get("reflection")) or None
            if configured_fields.get("reflection", {}).get("enabled")
            else None
        ),
        "next_focus": (
            _clean_text(form.get("next_focus")) or None
            if configured_fields.get("next_focus", {}).get("enabled")
            else None
        ),
        "family_note": (
            _clean_text(form.get("family_note")) or None
            if configured_fields.get("family_note", {}).get("enabled")
            else None
        ),
        "categories": (
            [str(value) for value in form.getlist("categories") if str(value)]
            if configured_fields.get("categories", {}).get("enabled")
            else []
        ),
        "perspective_tags": [
            str(value) for value in form.getlist("perspective_tags") if str(value)
        ] if configured_fields.get("perspective_tags", {}).get("enabled") else [],
        "custom_values": custom_values,
        "sensitivity": sensitivity,
    }
    for key, item in configured_fields.items():
        if not item.get("enabled") or not item.get("required") or key in {"observed_on", "child_state"}:
            continue
        value = custom_values.get(key) if key.startswith("custom.") else values.get(key)
        if value is None or value == "" or value == []:
            raise ValueError(f"{item.get('label', '必須項目')}を入力してください")
    return values


def _validate_observation_period(child: Child, observed_on: date) -> None:
    if observed_on < child.enrollment_date:
        raise ValueError("入園日より前の日付は記録できません")
    if observed_on > local_today() + timedelta(days=31):
        raise ValueError("観察日が未来になりすぎています")


def _fiscal_year(target: date) -> int:
    return target.year if target.month >= 4 else target.year - 1


def _age_on(child: Child, target: date) -> int:
    return target.year - child.birth_date.year - (
        (target.month, target.day) < (child.birth_date.month, child.birth_date.day)
    )


def _age_rule_key(child: Child, target: date) -> str:
    age = max(0, _age_on(child, date(_fiscal_year(target), 4, 1)))
    return f"age_{age}" if age <= 4 else "final_year"


def _add_months(year: int, month: int, offset: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + offset
    return index // 12, index % 12 + 1


def _progress_cycle(
    child: Child,
    config: dict[str, Any],
    target: date | None = None,
) -> dict[str, Any]:
    target = target or local_today()
    fiscal_year = _fiscal_year(target)
    age_key = _age_rule_key(child, target)
    rule = config.get("age_rules", {}).get(age_key, {}).get("child_progress_record", {})
    interval = int(rule.get("interval_months") or 3)
    interval = min(12, max(1, interval))
    fiscal_start_index = fiscal_year * 12 + 3
    target_index = target.year * 12 + target.month - 1
    elapsed = max(0, target_index - fiscal_start_index)
    cycle_offset = (elapsed // interval) * interval
    start_year, start_month = _add_months(fiscal_year, 4, cycle_offset)
    next_year, next_month = _add_months(start_year, start_month, interval)
    period_start = date(start_year, start_month, 1)
    period_end = date(next_year, next_month, 1) - timedelta(days=1)
    fiscal_end = date(fiscal_year + 1, 3, 31)
    period_end = min(period_end, fiscal_end)
    cycle_key = (
        f"fy{fiscal_year}:{period_start.isoformat()}:{period_end.isoformat()}"
    )
    return {
        "fiscal_year": fiscal_year,
        "age_key": age_key,
        "interval_months": interval,
        "period_start": period_start,
        "period_end": period_end,
        "cycle_key": cycle_key,
    }


def _progress_logs(
    session: Session,
    *,
    child_id: int,
    period_start: date,
    period_end: date,
    current_user: StaffUser,
) -> list[ChildObservationLog]:
    statement = select(ChildObservationLog).where(
        ChildObservationLog.child_id == child_id,
        ChildObservationLog.observed_on >= period_start,
        ChildObservationLog.observed_on <= period_end,
        ChildObservationLog.voided_at.is_(None),
    )
    if not current_user.is_admin:
        statement = statement.where(ChildObservationLog.sensitivity == "normal")
    return session.exec(
        statement.order_by(
            ChildObservationLog.observed_on.desc(),
            ChildObservationLog.created_at.desc(),
        )
    ).all()


@router.post("/{child_id}/records")
async def create_child_record(
    request: Request,
    child_id: int,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    _require_child_access(session, current_user, child)
    setting = _ensure_setting_for_record(session, actor_id=_actor_id(current_user))
    config = setting.config
    form = await request.form()
    try:
        values = _values_from_form(form, config, current_user)
        _validate_observation_period(child, values["observed_on"])
    except ValueError as exc:
        return _log_form_context(
            request,
            child=child,
            current_user=current_user,
            config=config,
            error=str(exc),
        )
    log = ChildObservationLog(
        child_id=child_id,
        setting_version_id=setting.id,
        classroom_id_snapshot=child.classroom_id,
        classroom_name_snapshot=child.classroom.name if child.classroom else None,
        created_by=_actor_id(current_user),
        created_by_name=current_user.name,
        **values,
    )
    session.add(log)
    session.commit()
    return RedirectResponse(url=f"/children/{child_id}/records?created=1", status_code=303)


def _load_log(session: Session, child_id: int, log_id: int) -> ChildObservationLog:
    log = session.exec(
        select(ChildObservationLog).where(
            ChildObservationLog.id == log_id,
            ChildObservationLog.child_id == child_id,
        )
    ).first()
    if log is None:
        raise HTTPException(status_code=404, detail="子どもの記録が見つかりません")
    return log


@router.get("/{child_id}/records/{log_id}/correct", response_class=HTMLResponse)
def correct_child_record_form(
    request: Request,
    child_id: int,
    log_id: int,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    _require_child_access(session, current_user, child)
    log = _load_log(session, child_id, log_id)
    if log.sensitivity == "restricted" and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="この記録を閲覧できません")
    if not _can_correct(current_user, log):
        raise HTTPException(status_code=403, detail="この記録を訂正できません")
    config = (
        session.get(ChildRecordSettingVersion, log.setting_version_id).config
        if log.setting_version_id and session.get(ChildRecordSettingVersion, log.setting_version_id)
        else effective_config(session)[0]
    )
    return _log_form_context(
        request,
        child=child,
        current_user=current_user,
        config=config,
        log=log,
    )


@router.post("/{child_id}/records/{log_id}/correct")
async def correct_child_record(
    request: Request,
    child_id: int,
    log_id: int,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    _require_child_access(session, current_user, child)
    log = _load_log(session, child_id, log_id)
    if log.sensitivity == "restricted" and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="この記録を閲覧できません")
    if not _can_correct(current_user, log):
        raise HTTPException(status_code=403, detail="この記録を訂正できません")
    setting = session.get(ChildRecordSettingVersion, log.setting_version_id) if log.setting_version_id else None
    config = setting.config if setting else effective_config(session)[0]
    form = await request.form()
    reason = _clean_text(form.get("correction_reason"), max_length=500)
    if not reason:
        return _log_form_context(
            request,
            child=child,
            current_user=current_user,
            config=config,
            log=log,
            error="訂正理由を入力してください",
        )
    try:
        values = _values_from_form(form, config, current_user)
        _validate_observation_period(child, values["observed_on"])
    except ValueError as exc:
        return _log_form_context(
            request,
            child=child,
            current_user=current_user,
            config=config,
            log=log,
            error=str(exc),
        )
    latest_revision = session.exec(
        select(func.max(ChildObservationLogRevision.revision_no)).where(
            ChildObservationLogRevision.log_id == log_id
        )
    ).one()
    session.add(
        ChildObservationLogRevision(
            log_id=log_id,
            revision_no=int(latest_revision or 0) + 1,
            snapshot=_log_snapshot(log),
            reason=reason,
            created_by=_actor_id(current_user),
            created_by_name=current_user.name,
        )
    )
    for key, value in values.items():
        setattr(log, key, value)
    log.updated_at = utc_now()
    session.add(log)
    session.commit()
    return RedirectResponse(url=f"/children/{child_id}/records?corrected=1", status_code=303)


@router.post("/{child_id}/records/{log_id}/void")
async def void_child_record(
    request: Request,
    child_id: int,
    log_id: int,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    _require_child_access(session, current_user, child)
    log = _load_log(session, child_id, log_id)
    if log.sensitivity == "restricted" and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="この記録を閲覧できません")
    if not _can_correct(current_user, log):
        raise HTTPException(status_code=403, detail="この記録を無効化できません")
    form = await request.form()
    reason = _clean_text(form.get("void_reason"), max_length=500)
    if not reason:
        raise HTTPException(status_code=422, detail="無効化理由を入力してください")
    if log.voided_at is None:
        log.voided_at = utc_now()
        log.voided_by = _actor_id(current_user)
        log.void_reason = reason
        log.updated_at = utc_now()
        session.add(log)
        session.commit()
    return RedirectResponse(url=f"/children/{child_id}/records?voided=1", status_code=303)


def _progress_form_context(
    request: Request,
    *,
    child: Child,
    current_user: StaffUser,
    period_start: date,
    period_end: date,
    cycle_key: str,
    logs: list[ChildObservationLog],
    values: dict[str, str] | None = None,
    error: str = "",
    existing_document_id: int | None = None,
):
    return templates.TemplateResponse(
        request,
        "child_records/progress_form.html",
        {
            "request": request,
            "current_user": current_user,
            "child": child,
            "period_start": period_start,
            "period_end": period_end,
            "cycle_key": cycle_key,
            "logs": logs,
            "section_definitions": section_definitions(DocumentType.CHILD_PROGRESS_RECORD),
            "values": values or {},
            "error": error,
            "existing_document_id": existing_document_id,
        },
        status_code=422 if error else 200,
    )


@router.get("/{child_id}/progress-records", response_class=HTMLResponse)
def child_progress_record_list(
    request: Request,
    child_id: int,
    permission_denied: bool = Query(default=False),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    child = _load_child(session, child_id)
    if not _has_child_access(session, current_user, child):
        return RedirectResponse(
            url=f"/children/{child_id}?child_records_denied=1",
            status_code=303,
        )
    config, _ = effective_config(session)
    cycle = _progress_cycle(child, config)
    records = session.exec(
        select(PlanDocumentRow).where(
            PlanDocumentRow.document_type == DocumentType.CHILD_PROGRESS_RECORD.value,
            PlanDocumentRow.child_id == child_id,
        ).order_by(PlanDocumentRow.period_start.desc(), PlanDocumentRow.created_at.desc())
    ).all()
    current_record = next(
        (item for item in records if item.record_cycle_key == cycle["cycle_key"]),
        None,
    )
    return templates.TemplateResponse(
        request,
        "child_records/progress_list.html",
        {
            "request": request,
            "current_user": current_user,
            "child": child,
            "records": records,
            "current_cycle": cycle,
            "current_record": current_record,
            "status_labels": PROGRESS_STATUS_LABELS,
            "permission_denied": permission_denied,
        },
    )


@router.get("/{child_id}/progress-records/new", response_class=HTMLResponse)
def new_child_progress_record_form(
    request: Request,
    child_id: int,
    period_start: str = Query(default=""),
    period_end: str = Query(default=""),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    child = _load_child(session, child_id)
    if not _has_child_access(session, current_user, child):
        return RedirectResponse(
            url=f"/children/{child_id}?child_records_denied=1",
            status_code=303,
        )
    if not current_user.can_edit:
        return RedirectResponse(
            url=f"/children/{child_id}/progress-records?permission_denied=1",
            status_code=303,
        )
    config, _ = effective_config(session)
    cycle = _progress_cycle(child, config)
    selected_start = (
        _parse_date(period_start, field_label="対象期間の開始日")
        if period_start
        else cycle["period_start"]
    )
    selected_end = (
        _parse_date(period_end, field_label="対象期間の終了日")
        if period_end
        else cycle["period_end"]
    )
    if selected_start > selected_end:
        raise HTTPException(status_code=422, detail="対象期間の開始日と終了日を確認してください")
    selected_cycle_key = (
        cycle["cycle_key"]
        if selected_start == cycle["period_start"] and selected_end == cycle["period_end"]
        else f"manual:{selected_start.isoformat()}:{selected_end.isoformat()}"
    )
    existing = session.exec(
        select(PlanDocumentRow).where(
            PlanDocumentRow.document_type == DocumentType.CHILD_PROGRESS_RECORD.value,
            PlanDocumentRow.child_id == child_id,
            PlanDocumentRow.record_cycle_key == selected_cycle_key,
        )
    ).first()
    logs = _progress_logs(
        session,
        child_id=child_id,
        period_start=selected_start,
        period_end=selected_end,
        current_user=current_user,
    )
    return _progress_form_context(
        request,
        child=child,
        current_user=current_user,
        period_start=selected_start,
        period_end=selected_end,
        cycle_key=selected_cycle_key,
        logs=logs,
        existing_document_id=existing.id if existing is not None else None,
    )


@router.post("/{child_id}/progress-records")
async def create_child_progress_record(
    request: Request,
    child_id: int,
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    _require_child_access(session, current_user, child)
    form = await request.form()
    period_start = _parse_date(str(form.get("period_start") or ""), field_label="対象期間の開始日")
    period_end = _parse_date(str(form.get("period_end") or ""), field_label="対象期間の終了日")
    if period_start > period_end:
        raise HTTPException(status_code=422, detail="対象期間の開始日と終了日を確認してください")
    if (period_end - period_start).days > 370:
        raise HTTPException(status_code=422, detail="児童票の対象期間は1年以内にしてください")
    if period_end < child.enrollment_date:
        raise HTTPException(status_code=422, detail="在籍期間と重ならない児童票は作成できません")
    cycle_key = _clean_text(form.get("cycle_key"), max_length=100)
    if not cycle_key:
        raise HTTPException(status_code=422, detail="作成周期を確認してください")

    setting = _ensure_setting_for_record(session, actor_id=_actor_id(current_user))
    logs = _progress_logs(
        session,
        child_id=child_id,
        period_start=period_start,
        period_end=period_end,
        current_user=current_user,
    )
    available_logs = {str(log.id): log for log in logs}
    selected_logs = [
        available_logs[log_id]
        for log_id in form.getlist("source_log_ids")
        if str(log_id) in available_logs
    ]
    source_refs = [
        f"record.child_observation_log:{log.public_id}" for log in selected_logs
    ]
    values: dict[str, str] = {}
    sections: list[SectionBlock] = []
    for definition in section_definitions(DocumentType.CHILD_PROGRESS_RECORD):
        body = _clean_text(form.get(f"body_{definition.key}"))
        values[definition.key] = body
        sections.append(
            SectionBlock(
                section_key=definition.key,
                title=definition.title,
                body=body,
                source_refs=list(source_refs),
                evidence_tags=["子どもの記録"] if source_refs else ["入力"],
            )
        )
    if not values.get("progress_children_overview"):
        return _progress_form_context(
            request,
            child=child,
            current_user=current_user,
            period_start=period_start,
            period_end=period_end,
            cycle_key=cycle_key,
            logs=logs,
            values=values,
            error="対象期間の子どもの姿を入力してください",
        )

    document = PlanDocument(
        id=0,
        document_type=DocumentType.CHILD_PROGRESS_RECORD,
        title=f"{child.full_name} 児童票（{period_start:%Y/%m/%d}〜{period_end:%Y/%m/%d}）",
        status=DocumentStatus.DRAFT,
        nursery_ref=os.getenv("HOIKU_NURSERY_REF", DEFAULT_NURSERY_REF),
        classroom_ref=child.classroom.name if child.classroom else "クラス未設定",
        actor_ref=f"staff:{current_user.user_id}" if current_user.user_id else None,
        owner_name=current_user.name,
        sections=sections,
        school_year=_fiscal_year(period_start),
        period_start=period_start.isoformat(),
        period_end=period_end.isoformat(),
        record_cycle_key=cycle_key,
        setting_version_id=setting.id,
        age_class=_age_rule_key(child, period_start),
        child_id=child_id,
        child_ref=str(child_id),
        child_name=child.full_name,
    )
    try:
        created = SqlModelDocumentRepository(session).create(document)
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(status_code=409, detail="同じ期間の児童票はすでに作成されています") from exc
    return RedirectResponse(url=f"/plans/documents/{created.id}", status_code=303)


@progress_router.get("/progress", response_class=HTMLResponse)
def child_progress_dashboard(
    request: Request,
    age_group: str = Query(default=""),
    status: str = Query(default=""),
    session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    age_labels = {key: label for key, label, _ in AGE_RULES}
    allowed_statuses = {key for key, _ in PROGRESS_FILTER_STATUS_OPTIONS}
    selected_age_group = age_group if age_group in age_labels else ""
    selected_status = status if status in allowed_statuses else ""
    children = session.exec(
        select(Child)
        .options(selectinload(Child.classroom))
        .where(Child.status == ChildStatus.enrolled)
        .order_by(Child.last_name_kana, Child.first_name_kana)
    ).all()
    accessible_children = [
        child for child in children if _has_child_access(session, current_user, child)
    ]
    config, _ = effective_config(session)
    documents = session.exec(
        select(PlanDocumentRow).where(
            PlanDocumentRow.document_type == DocumentType.CHILD_PROGRESS_RECORD.value
        )
    ).all()
    documents_by_child_cycle = {
        (document.child_id, document.record_cycle_key): document for document in documents
    }
    rows = []
    for child in accessible_children:
        cycle = _progress_cycle(child, config)
        document = documents_by_child_cycle.get((child.id, cycle["cycle_key"]))
        rows.append(
            {
                "child": child,
                "cycle": cycle,
                "age_label": age_labels.get(cycle["age_key"], cycle["age_key"]),
                "document": document,
            }
        )
    total_count = len(rows)
    uncreated_count = sum(1 for row in rows if row["document"] is None)
    if selected_age_group:
        rows = [row for row in rows if row["cycle"]["age_key"] == selected_age_group]
    if selected_status == "uncreated":
        rows = [row for row in rows if row["document"] is None]
    elif selected_status == "created":
        rows = [row for row in rows if row["document"] is not None]
    elif selected_status:
        rows = [
            row
            for row in rows
            if row["document"] is not None
            and row["document"].status == selected_status
        ]
    return templates.TemplateResponse(
        request,
        "child_records/progress_dashboard.html",
        {
            "request": request,
            "current_user": current_user,
            "rows": rows,
            "status_labels": PROGRESS_STATUS_LABELS,
            "age_filter_options": tuple((key, label) for key, label, _ in AGE_RULES),
            "status_filter_options": PROGRESS_FILTER_STATUS_OPTIONS,
            "selected_age_group": selected_age_group,
            "selected_status": selected_status,
            "total_count": total_count,
            "uncreated_count": uncreated_count,
            "filtered_count": len(rows),
        },
    )
