from __future__ import annotations

import os
from datetime import date, timedelta
from typing import Any
from types import SimpleNamespace
from urllib.parse import urlencode, urlsplit

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
from models import Child, User
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
from plan_docs.store import ConcurrentUpdateError, SqlModelDocumentRepository
from .progress import (
    containing_cycle, cycle_ending_by, cycle_key as progress_cycle_key,
    in_period, period_context, target_month as parse_target_month, validate_period,
)

from .models import (
    ChildObservationLog,
    ChildObservationLogRevision,
    ChildRecordSettingVersion,
)
from .access import (
    PROGRESS_VIEW_ALL_STAFF,
    PROGRESS_VIEW_ASSIGNED_CLASS,
    can_create_progress_record,
    can_view_observation_records,
    can_view_observation_log,
    can_view_progress_records,
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
    return can_view_observation_records(session, user, child)


def _require_child_access(session: Session, user: StaffUser, child: Child) -> None:
    if not _has_child_access(session, user, child):
        raise HTTPException(status_code=403, detail="この園児の記録を閲覧できません")


def _actor_id(user: StaffUser) -> str | None:
    return str(user.user_id) if user.user_id is not None else None


def _can_correct(user: StaffUser, log: ChildObservationLog) -> bool:
    author = _actor_id(user) is not None and log.created_by == _actor_id(user)
    return (
        user.can_edit
        and not log.voided_at
        and (author or (user.is_admin and log.visibility != "private"))
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
    progress_view_scope = str(
        form.get("progress_record_view_scope") or PROGRESS_VIEW_ALL_STAFF
    )
    if progress_view_scope not in {
        PROGRESS_VIEW_ASSIGNED_CLASS,
        PROGRESS_VIEW_ALL_STAFF,
    }:
        progress_view_scope = PROGRESS_VIEW_ALL_STAFF
    config["access_policy"]["progress_record_view_scope"] = progress_view_scope
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
        "visibility": log.visibility,
        "shared_staff_ids": list(log.shared_staff_ids or []),
        "updated_at": log.updated_at.isoformat(),
    }


def _save_log_revision(
    session: Session, log: ChildObservationLog, user: StaffUser, reason: str,
    *, action: str = "correct",
) -> None:
    latest = session.exec(
        select(func.max(ChildObservationLogRevision.revision_no)).where(
            ChildObservationLogRevision.log_id == log.id
        )
    ).one()
    session.add(ChildObservationLogRevision(
        log_id=log.id, revision_no=int(latest or 0) + 1,
        snapshot={**_log_snapshot(log), "action": action}, reason=reason,
        created_by=_actor_id(user), created_by_name=user.name,
    ))


def _log_form_context(
    request: Request,
    *,
    child: Child,
    current_user: StaffUser,
    config: dict[str, Any],
    log: ChildObservationLog | None = None,
    error: str = "",
    form: Any = None,
    session: Session,
):
    values = _log_snapshot(log) if log else {
        "observed_on": local_today().isoformat(),
        "visibility": "private", "sensitivity": "normal",
    }
    values.setdefault("custom_values", {})
    values.setdefault("categories", [])
    values.setdefault("perspective_tags", [])
    values.setdefault("shared_staff_ids", [])
    if form is not None:
        for key in (
            "observed_on", "child_state", "caregiver_support", "reflection",
            "next_focus", "family_note", "sensitivity", "visibility", "correction_reason",
        ):
            if key in form:
                values[key] = str(form.get(key) or "")
        for key in ("categories", "perspective_tags", "shared_staff_ids"):
            values[key] = form.getlist(key)
        values["custom_values"] = {
            key: str(form.get("custom_" + key.removeprefix("custom.")) or "")
            for key in field_map(config) if key.startswith("custom.")
        }
    staff_options = session.exec(
        select(User).where(User.is_active == True).order_by(User.staff_sort_order, User.display_name)
    ).all() if current_user.is_admin else []
    return templates.TemplateResponse(
        request,
        "child_records/log_form.html",
        {
            "request": request,
            "current_user": current_user,
            "child": child,
            "log": log,
            "values": values,
            "staff_options": staff_options,
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
    sharing: str = Query(default="all"),
    include_voided: bool = Query(default=False),
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
    )
    if not include_voided:
        statement = statement.where(ChildObservationLog.voided_at.is_(None))
    logs = session.exec(
        statement.order_by(
            ChildObservationLog.observed_on.desc(),
            ChildObservationLog.created_at.desc(),
        )
    ).all()
    logs = [log for log in logs if can_view_observation_log(session, current_user, child, log)]
    if sharing in {"private", "shared"}:
        logs = [log for log in logs if log.visibility == sharing]
    if category:
        logs = [log for log in logs if category in (log.categories or [])]
    revisions_by_log_id = {}
    for log in logs:
        revisions = session.exec(
            select(ChildObservationLogRevision).where(
                ChildObservationLogRevision.log_id == log.id
            ).order_by(ChildObservationLogRevision.revision_no.desc())
        ).all()
        # Sharing a current record does not publish its earlier private content.
        revisions_by_log_id[log.id] = [
            revision for revision in revisions if can_view_observation_log(
                session, current_user, child, SimpleNamespace(
                    visibility=revision.snapshot.get("visibility"),
                    sensitivity=revision.snapshot.get("sensitivity", "restricted"),
                    created_by=log.created_by,
                    shared_staff_ids=revision.snapshot.get("shared_staff_ids", []),
                ),
            )
        ]
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
            "sharing": sharing,
            "include_voided": include_voided,
            "correctable_ids": {log.id for log in logs if _can_correct(current_user, log)},
            "revisions_by_log_id": revisions_by_log_id,
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
        session=session,
        child=child,
        current_user=current_user,
        config=config,
    )


def _values_from_form(form: Any, config: dict[str, Any], user: StaffUser, session: Session, log: ChildObservationLog | None = None) -> dict[str, Any]:
    try:
        observed_on = date.fromisoformat(str(form.get("observed_on") or ""))
    except ValueError as exc:
        raise ValueError("観察日を正しく入力してください") from exc
    child_state = _clean_text(form.get("child_state"))
    if not child_state:
        raise ValueError("子どもの姿を入力してください")
    sensitivity = str(form.get("sensitivity") or (log.sensitivity if log else "normal"))
    if sensitivity not in {"normal", "restricted"}:
        raise ValueError("取扱区分を選択してください")
    if not user.is_admin:
        sensitivity = log.sensitivity if log else "normal"
    visibility = str(form.get("visibility") or ((log.visibility or "legacy") if log else "private"))
    if visibility == "legacy" and log and log.visibility is None:
        visibility = None
    elif visibility not in {"private", "shared"}:
        raise ValueError("共有範囲を選択してください")
    # Only the author may turn an existing shared record into a personal memo.
    if log and visibility == "private" and log.created_by != _actor_id(user):
        raise ValueError("自分だけに変更できるのは記録した本人です")
    shared_staff_ids = list(log.shared_staff_ids or []) if log else []
    if user.is_admin:
        shared_staff_ids = sorted(set(str(value) for value in form.getlist("shared_staff_ids")))
        active_ids = {str(item.id) for item in session.exec(select(User).where(User.is_active == True)).all()}
        if not set(shared_staff_ids) <= active_ids:
            raise ValueError("共有先の職員を選び直してください")
    if visibility != "shared" or sensitivity != "restricted":
        shared_staff_ids = []
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
        "visibility": visibility,
        "shared_staff_ids": shared_staff_ids,
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
    if target is not None:
        return containing_cycle(child, config, target)
    return cycle_ending_by(child, config, parse_target_month("", local_today()))


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
    statement = statement.where(
        ChildObservationLog.sensitivity == "normal",
        (ChildObservationLog.visibility == "shared") | ChildObservationLog.visibility.is_(None),
    )
    child = _load_child(session, child_id)
    logs = session.exec(
        statement.order_by(
            ChildObservationLog.observed_on.desc(),
            ChildObservationLog.created_at.desc(),
        )
    ).all()
    return [log for log in logs if can_view_observation_log(session, current_user, child, log)]


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
        values = _values_from_form(form, config, current_user, session)
        _validate_observation_period(child, values["observed_on"])
    except (ValueError, HTTPException) as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 422:
            raise
        return _log_form_context(
            request,
            session=session,
            child=child,
            current_user=current_user,
            config=config,
            error=str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
            form=form,
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
    if not can_view_observation_log(session, current_user, child, log):
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
        session=session,
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
    if not can_view_observation_log(session, current_user, child, log):
        raise HTTPException(status_code=403, detail="この記録を閲覧できません")
    if not _can_correct(current_user, log):
        raise HTTPException(status_code=403, detail="この記録を訂正できません")
    setting = session.get(ChildRecordSettingVersion, log.setting_version_id) if log.setting_version_id else None
    config = setting.config if setting else effective_config(session)[0]
    form = await request.form()
    try:
        reason = _clean_text(form.get("correction_reason"), max_length=500)
        if not reason:
            raise ValueError("訂正理由を入力してください")
        if form.get("expected_updated_at") and form["expected_updated_at"] != log.updated_at.isoformat():
            raise ValueError("別の操作で更新されています。入力内容を控えて記録を開き直してください")
        values = _values_from_form(form, config, current_user, session, log)
        _validate_observation_period(child, values["observed_on"])
    except (ValueError, HTTPException) as exc:
        if isinstance(exc, HTTPException) and exc.status_code != 422:
            raise
        return _log_form_context(
            request,
            session=session,
            child=child,
            current_user=current_user,
            config=config,
            log=log,
            error=str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
            form=form,
        )
    _save_log_revision(session, log, current_user, reason)
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
    if not can_view_observation_log(session, current_user, child, log):
        raise HTTPException(status_code=403, detail="この記録を閲覧できません")
    if not _can_correct(current_user, log):
        raise HTTPException(status_code=403, detail="この記録を無効化できません")
    form = await request.form()
    reason = _clean_text(form.get("void_reason"), max_length=500)
    if not reason:
        raise HTTPException(status_code=422, detail="無効化理由を入力してください")
    if log.voided_at is None:
        _save_log_revision(session, log, current_user, reason, action="void")
        log.voided_at = utc_now()
        log.voided_by = _actor_id(current_user)
        log.void_reason = reason
        log.updated_at = utc_now()
        session.add(log)
        session.commit()
    return RedirectResponse(url=f"/children/{child_id}/records?voided=1", status_code=303)


def _progress_records(session: Session, child_id: int | None = None):
    statement = select(PlanDocumentRow).where(
        PlanDocumentRow.document_type == DocumentType.CHILD_PROGRESS_RECORD.value,
    )
    if child_id is not None:
        statement = statement.where(PlanDocumentRow.child_id == child_id)
    return session.exec(statement.order_by(PlanDocumentRow.updated_at.desc(), PlanDocumentRow.id.desc())).all()


def _same_period(records, start: date, end: date):
    return [item for item in records if item.period_start == start.isoformat() and item.period_end == end.isoformat()]


def _progress_form_url(child_id, start, end, **params):
    return f"/children/{child_id}/progress-records/new?" + urlencode({
        "period_start": start.isoformat(), "period_end": end.isoformat(), **params,
    })


def _selected_cycle(child, config, target_month, period_start="", period_end=""):
    cycle = cycle_ending_by(child, config, parse_target_month(target_month, local_today()))
    if bool(period_start) != bool(period_end):
        raise HTTPException(422, "対象期間の開始日と終了日を指定してください")
    if period_start:
        start = _parse_date(period_start, field_label="対象期間の開始日")
        end = _parse_date(period_end, field_label="対象期間の終了日")
        validate_period(start, end)
        cycle = {**containing_cycle(child, config, start), "period_start": start,
                 "period_end": end, "cycle_key": progress_cycle_key(start, end)}
    return cycle


def _progress_form_context(
    request: Request, *, session: Session, child: Child, current_user: StaffUser,
    period_start: date, period_end: date, logs: list[ChildObservationLog],
    values: dict[str, str] | None = None, error: str = "", status_code: int = 200,
    document=None, lock_version: int | None = None, selected_log_ids=None,
    conflict_document_id=None, duplicate_count=0, saved=False, continue_url="",
):
    config, _ = effective_config(session)
    available = in_period(child, period_start, period_end)
    if document is not None:
        if values is None:
            values = {section.section_key: section.body for section in document.sections}
        if selected_log_ids is None:
            refs = {ref for section in document.sections for ref in section.source_refs}
            selected_log_ids = [str(log.id) for log in logs if f"record.child_observation_log:{log.public_id}" in refs]
        if lock_version is None:
            lock_version = SqlModelDocumentRepository(session).lock_version(document.id)
    return templates.TemplateResponse(request, "child_records/progress_form.html", {
        "request": request, "current_user": current_user, "child": child,
        **period_context(child, config, period_start, period_end, local_today()),
        "cycle_key": progress_cycle_key(period_start, period_end), "logs": logs,
        "section_definitions": section_definitions(DocumentType.CHILD_PROGRESS_RECORD),
        "values": values or {}, "error": error, "document": document,
        "lock_version": lock_version, "selected_log_ids": selected_log_ids or [],
        "conflict_document_id": conflict_document_id, "duplicate_count": duplicate_count,
        "period_available": available or document is not None, "saved": saved,
        "continue_url": continue_url,
        "period_action": f"/children/{child.id}/progress-records/new",
    }, status_code=status_code)


@router.get("/{child_id}/progress-records", response_class=HTMLResponse)
def child_progress_record_list(
    request: Request, child_id: int, permission_denied: bool = Query(default=False),
    target_month: str = Query(default=""), session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    child = _load_child(session, child_id)
    config, _ = effective_config(session)
    if not can_view_progress_records(session, current_user, child, config):
        return RedirectResponse(url=f"/children/{child_id}?child_records_denied=1", status_code=303)
    cycle = _selected_cycle(child, config, target_month)
    start, end = cycle["period_start"], cycle["period_end"]
    records = _progress_records(session, child_id)
    matches = _same_period(records, start, end)
    current_record = matches[0] if matches else None
    can_create = can_create_progress_record(session, current_user, child)
    return templates.TemplateResponse(request, "child_records/progress_list.html", {
        "request": request, "current_user": current_user, "child": child,
        "records": sorted(records, key=lambda item: (item.period_start or "", item.id or 0), reverse=True),
        "current_cycle": cycle, "current_record": current_record,
        **period_context(child, config, start, end, local_today()),
        "period_action": f"/children/{child_id}/progress-records",
        "period_available": in_period(child, start, end),
        "entry_url": _progress_form_url(child_id, start, end),
        "can_edit_current": can_create and current_record is not None and current_record.status in {"draft", "rejected"},
        "status_labels": PROGRESS_STATUS_LABELS, "permission_denied": permission_denied,
        "can_view_observation_records": can_view_observation_records(session, current_user, child),
        "can_create_progress_record": can_create,
    })


@router.get("/{child_id}/progress-records/new", response_class=HTMLResponse)
def new_child_progress_record_form(
    request: Request, child_id: int, target_month: str = Query(default=""),
    period_start: str = Query(default=""), period_end: str = Query(default=""),
    document_id: int | None = Query(default=None), saved: bool = Query(default=False),
    session: Session = Depends(get_session), current_user: StaffUser = Depends(get_current_staff_user),
):
    child = _load_child(session, child_id)
    config, _ = effective_config(session)
    if not can_view_progress_records(session, current_user, child, config):
        return RedirectResponse(url=f"/children/{child_id}?child_records_denied=1", status_code=303)
    if not can_create_progress_record(session, current_user, child):
        return RedirectResponse(url=f"/children/{child_id}/progress-records?permission_denied=1", status_code=303)
    repository = SqlModelDocumentRepository(session)
    document = repository.get(document_id) if document_id is not None else None
    if document_id is not None:
        if document is None or document.child_id != child_id or document.document_type != DocumentType.CHILD_PROGRESS_RECORD:
            raise HTTPException(404, "児童票が見つかりません")
        period_start, period_end = document.period_start, document.period_end
    cycle = _selected_cycle(child, config, target_month, period_start, period_end)
    start, end = cycle["period_start"], cycle["period_end"]
    matches = _same_period(_progress_records(session, child_id), start, end)
    if document is None and matches:
        document = repository.get(matches[0].id)
        if document is None:
            raise HTTPException(409, "この期間の児童票は削除されています。管理者に復元を依頼してください")
    if document is not None and not document.can_edit_body:
        return RedirectResponse(url=f"/plans/documents/{document.id}", status_code=303)
    logs = _progress_logs(session, child_id=child_id, period_start=start, period_end=end, current_user=current_user)
    return _progress_form_context(request, session=session, child=child, current_user=current_user,
        period_start=start, period_end=end, logs=logs, document=document,
        duplicate_count=len(matches), saved=saved)


def _progress_return_url(raw: str, child_id: int) -> str:
    if not raw:
        return ""
    parsed = urlsplit(raw)
    if parsed.scheme or parsed.netloc or parsed.fragment or parsed.path not in {
        "/child-records/progress", f"/children/{child_id}/progress-records",
        f"/children/{child_id}/progress-records/new",
    }:
        raise HTTPException(422, "移動先を確認してください")
    return raw


@router.post("/{child_id}/progress-records")
async def create_child_progress_record(
    request: Request, child_id: int, session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    child = _load_child(session, child_id)
    if not can_create_progress_record(session, current_user, child):
        raise HTTPException(403, "この園児の児童票を作成できません")
    form = await request.form()
    start = _parse_date(str(form.get("period_start") or ""), field_label="対象期間の開始日")
    end = _parse_date(str(form.get("period_end") or ""), field_label="対象期間の終了日")
    validate_period(start, end)
    continue_url = _progress_return_url(str(form.get("continue_url") or ""), child_id)
    repository = SqlModelDocumentRepository(session)
    document = None
    version = None
    raw_id = str(form.get("document_id") or "")
    if raw_id:
        try:
            document = repository.get(int(raw_id))
            version = int(str(form.get("lock_version") or ""))
        except ValueError as exc:
            raise HTTPException(422, "児童票を開き直してから保存してください") from exc
        if document is None or document.child_id != child_id or document.document_type != DocumentType.CHILD_PROGRESS_RECORD:
            raise HTTPException(404, "児童票が見つかりません")
        if (document.period_start, document.period_end) != (start.isoformat(), end.isoformat()):
            raise HTTPException(422, "保存済み児童票の対象期間は変更できません")
    elif not in_period(child, start, end):
        raise HTTPException(422, "在籍期間と重ならない児童票は作成できません。退園・卒園の場合は退園日も確認してください")
    logs = _progress_logs(session, child_id=child_id, period_start=start, period_end=end, current_user=current_user)
    available_logs = {str(log.id): log for log in logs}
    selected_ids = list(dict.fromkeys(str(value) for value in form.getlist("source_log_ids") if str(value) in available_logs))
    source_refs = [f"record.child_observation_log:{available_logs[value].public_id}" for value in selected_ids]
    values = {definition.key: _clean_text(form.get(f"body_{definition.key}"))
              for definition in section_definitions(DocumentType.CHILD_PROGRESS_RECORD)}

    def invalid(message, status=422, conflict_id=None):
        return _progress_form_context(request, session=session, child=child, current_user=current_user,
            period_start=start, period_end=end, logs=logs, values=values, error=message,
            status_code=status, document=document, lock_version=version,
            selected_log_ids=selected_ids, conflict_document_id=conflict_id, continue_url=continue_url)

    if not values.get("progress_children_overview"):
        return invalid("対象期間の子どもの姿を入力してください")
    if document is not None:
        if not document.can_edit_body:
            return invalid("この児童票はレビュー中または承認済みのため修正できません。入力内容を確認し、作成済み児童票を開いてください", 409, document.id)
        visible_refs = {f"record.child_observation_log:{log.public_id}" for log in logs}
        updates = {}
        for section in document.sections:
            # Keep evidence which is now unavailable (for example, a corrected/private log).
            refs = list(dict.fromkeys([ref for ref in section.source_refs if ref not in visible_refs] + source_refs))
            tags = [tag for tag in section.evidence_tags if tag != "子どもの記録"]
            if refs:
                tags.append("子どもの記録")
            updates[section.section_key] = {"body": values.get(section.section_key, section.body),
                "editor_note": section.editor_note, "needs_confirmation": section.needs_confirmation,
                "source_refs": refs, "evidence_tags": tags}
        try:
            repository.update_document(document.id, title=document.title, owner_name=document.owner_name,
                confirmation_items=document.confirmation_items, section_updates=updates,
                expected_lock_version=version, actor_ref=f"staff:{current_user.user_id}")
        except ConcurrentUpdateError:
            session.rollback()
            return invalid("他の職員が先に更新しました。入力内容は保持しています。作成済み児童票を別のタブで確認し、内容を合わせてください", 409, document.id)
        saved_id = document.id
    else:
        matches = _same_period(_progress_records(session, child_id), start, end)
        if matches:
            return invalid("同じ期間の児童票はすでに作成されています。入力内容を確認してから作成済み児童票を開いてください", 409, matches[0].id)
        setting = _ensure_setting_for_record(session, actor_id=_actor_id(current_user))
        sections = [SectionBlock(section_key=definition.key, title=definition.title,
            body=values[definition.key], source_refs=list(source_refs),
            evidence_tags=["子どもの記録"] if source_refs else [])
            for definition in section_definitions(DocumentType.CHILD_PROGRESS_RECORD)]
        document_to_create = PlanDocument(id=0, document_type=DocumentType.CHILD_PROGRESS_RECORD,
            title=f"{child.full_name} 児童票（{start:%Y/%m/%d}〜{end:%Y/%m/%d}）", status=DocumentStatus.DRAFT,
            nursery_ref=os.getenv("HOIKU_NURSERY_REF", DEFAULT_NURSERY_REF),
            classroom_ref=child.classroom.name if child.classroom else "クラス未設定",
            actor_ref=f"staff:{current_user.user_id}" if current_user.user_id else None,
            owner_name=current_user.name, sections=sections, school_year=_fiscal_year(start),
            period_start=start.isoformat(), period_end=end.isoformat(), record_cycle_key=progress_cycle_key(start, end),
            setting_version_id=setting.id, age_class=_age_rule_key(child, start),
            child_id=child_id, child_ref=str(child_id), child_name=child.full_name)
        try:
            saved_id = repository.create(document_to_create).id
        except IntegrityError:
            session.rollback()
            matches = _same_period(_progress_records(session, child_id), start, end)
            if not matches:
                raise
            return invalid("同じ期間の児童票はすでに作成されています。入力内容を確認してから作成済み児童票を開いてください", 409, matches[0].id)
    destination = continue_url or _progress_form_url(child_id, start, end, document_id=saved_id, saved=1)
    return RedirectResponse(url=destination, status_code=303)


@progress_router.get("/progress", response_class=HTMLResponse)
def child_progress_dashboard(
    request: Request, age_group: str = Query(default=""), status: str = Query(default=""),
    classroom_id: str = Query(default=""), group_by: str = Query(default="classroom"),
    target_month: str = Query(default=""), session: Session = Depends(get_session),
    current_user: StaffUser = Depends(get_current_staff_user),
):
    target = parse_target_month(target_month, local_today())
    age_labels = {key: label for key, label, _ in AGE_RULES}
    selected_age_group = age_group if age_group in age_labels else ""
    selected_status = status if status in {key for key, _ in PROGRESS_FILTER_STATUS_OPTIONS} else ""
    config, _ = effective_config(session)
    children = session.exec(select(Child).options(selectinload(Child.classroom))
        .where(Child.enrollment_date <= target).order_by(Child.last_name_kana, Child.first_name_kana)).all()
    documents_by_period = {}
    for document in _progress_records(session):
        documents_by_period.setdefault((document.child_id, document.period_start, document.period_end), []).append(document)
    rows = []
    for child in children:
        cycle = cycle_ending_by(child, config, target)
        start, end = cycle["period_start"], cycle["period_end"]
        if not in_period(child, start, end) or not can_view_progress_records(session, current_user, child, config):
            continue
        matches = documents_by_period.get((child.id, start.isoformat(), end.isoformat()), [])
        document = matches[0] if matches else None
        can_create = can_create_progress_record(session, current_user, child)
        rows.append({"child": child, "cycle": cycle, "age_label": age_labels.get(cycle["age_key"], cycle["age_key"]),
            "document": document, "can_create": can_create,
            "can_edit": can_create and document is not None and document.status in {"draft", "rejected"},
            "entry_url": _progress_form_url(child.id, start, end), "duplicate_count": len(matches)})
    classrooms_by_id = {row["child"].classroom.id: row["child"].classroom for row in rows if row["child"].classroom}
    classrooms = sorted(classrooms_by_id.values(), key=lambda item: (item.display_order, item.id))
    selected_classroom_id = classroom_id if classroom_id == "unassigned" or (classroom_id.isascii() and classroom_id.isdigit() and len(classroom_id) <= 18) else ""
    selected_group_by = group_by if group_by in {"classroom", "age"} else "classroom"
    for row in rows:
        child = row["child"]
        row["group_label"] = row["age_label"] if selected_group_by == "age" else (child.classroom.name if child.classroom else "クラス未設定")
        row["group_key"] = row["cycle"]["age_key"] if selected_group_by == "age" else child.classroom_id
    rows.sort(key=lambda row: (
        row["cycle"]["age_key"] if selected_group_by == "age" else "",
        row["child"].classroom is None, row["child"].classroom.display_order if row["child"].classroom else 0,
        row["child"].classroom_id or 0, row["child"].last_name_kana or "", row["child"].first_name_kana or "", row["child"].id))
    total_count = len(rows)
    uncreated_count = sum(1 for row in rows if row["document"] is None)
    if selected_classroom_id:
        rows = [row for row in rows if (row["child"].classroom_id is None if selected_classroom_id == "unassigned" else row["child"].classroom_id == int(selected_classroom_id))]
    if selected_age_group:
        rows = [row for row in rows if row["cycle"]["age_key"] == selected_age_group]
    if selected_status == "uncreated":
        rows = [row for row in rows if row["document"] is None]
    elif selected_status == "created":
        rows = [row for row in rows if row["document"] is not None]
    elif selected_status:
        rows = [row for row in rows if row["document"] is not None and row["document"].status == selected_status]
    previous_year, previous_month = _add_months(target.year, target.month, -1)
    next_year, next_month = _add_months(target.year, target.month, 1)
    return templates.TemplateResponse(request, "child_records/progress_dashboard.html", {
        "request": request, "current_user": current_user, "rows": rows,
        "status_labels": PROGRESS_STATUS_LABELS,
        "age_filter_options": tuple((key, label) for key, label, _ in AGE_RULES),
        "status_filter_options": PROGRESS_FILTER_STATUS_OPTIONS,
        "classrooms": classrooms, "selected_classroom_id": selected_classroom_id,
        "selected_group_by": selected_group_by, "selected_age_group": selected_age_group,
        "selected_status": selected_status, "total_count": total_count,
        "uncreated_count": uncreated_count, "filtered_count": len(rows),
        "selected_target_month": target.strftime("%Y-%m"),
        "previous_target_month": f"{previous_year:04d}-{previous_month:02d}",
        "next_target_month": f"{next_year:04d}-{next_month:02d}",
        "period_action": "/child-records/progress", "today": local_today(),
        "is_latest_period": target == parse_target_month("", local_today()),
    })
