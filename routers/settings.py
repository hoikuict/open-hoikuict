from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import get_current_staff_user
from database import get_session
from models import GuardianHoursAudit, GuardianHoursSetting, StaffSessionPolicyAudit
from guardian_hours import closing_time, parse_closing_time
from time_utils import utc_now
from staff_permissions import require_live_admin
from staff_session_settings import get_staff_session_policy, parse_session_policy, save_staff_session_policy
from template_utils import create_templates
import parent_contact_fields as contact_fields
from parent_contact_preview import render_preview
from fastapi import HTTPException
from models import ParentContactFieldAudit

router = APIRouter(prefix="/settings", tags=["settings"])
templates = create_templates()


def _contact_fields_page(request, session, current_user, *, policy=None, revision=None,
                         error="", status_code=200, saved=False, form=None):
    persisted, current_revision = contact_fields.get_policy(session)
    policy = policy if policy is not None else persisted
    rooms = contact_fields.classrooms(session)
    policy = contact_fields.policy_for_rooms(policy, rooms)
    form = form or {}
    preview_age = form.get("preview_age", "0")
    preview_class = form.get("preview_class", str(rooms[0].id) if rooms else "")
    preview_state = form.get("preview_state", "empty")
    group = preview_age if policy["mode"] == "age" else preview_class
    return templates.TemplateResponse(request, "settings/parent_contact_fields.html", {
        "current_user": current_user, "policy": policy, "groups": contact_fields.GROUPS,
        "tables": contact_fields.policy_groups(policy, rooms),
        "room_ids": contact_fields.room_revision(rooms),
        "revision": current_revision if revision is None else revision,
        "error": error, "saved": saved, "conflict": status_code == 409,
        "preview_age": preview_age, "preview_class": preview_class, "preview_state": preview_state,
        "preview_html": render_preview(templates, policy, group, preview_state),
        "latest": session.exec(select(ParentContactFieldAudit).order_by(ParentContactFieldAudit.id.desc())).first(),
    }, status_code=status_code, headers={"Cache-Control": "private, no-store"})


@router.get("/parent-contact-fields", response_class=HTMLResponse)
def parent_contact_fields(request: Request, saved: bool = False, session: Session = Depends(get_session),
                          current_user=Depends(get_current_staff_user)):
    require_live_admin(session, current_user)
    return _contact_fields_page(request, session, current_user, saved=saved)


@router.post("/parent-contact-fields", response_class=HTMLResponse)
async def save_parent_contact_fields(request: Request, session: Session = Depends(get_session),
                                     current_user=Depends(get_current_staff_user)):
    actor = require_live_admin(session, current_user)
    form = await request.form()
    previous, _ = contact_fields.get_policy(session)
    policy, revision = previous, form.get("revision", "")
    try:
        policy = contact_fields.parse_policy(form, previous, contact_fields.classrooms(session))
        revision = int(revision)
        if form.get("action") == "preview":
            return _contact_fields_page(request, session, current_user, policy=policy, revision=revision, form=form)
        if form.get("action") != "save":
            raise ValueError("保存またはプレビューを選んでください。")
        contact_fields.save_policy(session, policy, revision, actor)
    except (ValueError, HTTPException) as exc:
        session.rollback()
        return _contact_fields_page(request, session, current_user, policy=policy, revision=revision, form=form,
            error=str(exc.detail) if isinstance(exc, HTTPException) else str(exc),
            status_code=exc.status_code if isinstance(exc, HTTPException) else 400)
    return RedirectResponse("/settings/parent-contact-fields?saved=true", status_code=303,
                            headers={"Cache-Control": "private, no-store"})


@router.get("/guardian-hours", response_class=HTMLResponse)
def guardian_hours(request: Request, saved: bool = False, session: Session = Depends(get_session),
                   current_user=Depends(get_current_staff_user)):
    require_live_admin(session, current_user)
    return _hours_page(request, session, current_user, saved=saved)


def _hours_page(request, session, current_user, *, value=None, error="", saved=False):
    return templates.TemplateResponse(request, "settings/guardian_hours.html", {
        "current_user": current_user, "closing_time": value if value is not None else closing_time(session),
        "error": error, "saved": saved,
        "history": session.exec(select(GuardianHoursAudit).order_by(GuardianHoursAudit.id.desc()).limit(10)).all(),
    }, status_code=400 if error else 200, headers={"Cache-Control": "private, no-store"})


@router.post("/guardian-hours", response_class=HTMLResponse)
def save_guardian_hours(request: Request, closing: str = Form("", alias="closing_time"),
                        session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor = require_live_admin(session, current_user)
    try:
        value = parse_closing_time(closing)
    except ValueError as exc:
        return _hours_page(request, session, current_user, value=closing, error=str(exc))
    previous = closing_time(session)
    setting = session.get(GuardianHoursSetting, 1) or GuardianHoursSetting()
    setting.closing_time, setting.updated_by_name, setting.updated_at = value, actor.display_name, utc_now()
    session.add(setting)
    session.add(GuardianHoursAudit(previous_closing_time=previous, closing_time=value,
                                  changed_by_name=actor.display_name, changed_by_user_id=actor.id))
    session.commit()
    return RedirectResponse("/settings/guardian-hours?saved=true", status_code=303)


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def settings_index(request: Request, current_user=Depends(get_current_staff_user)):
    from restore_control import enabled
    import os
    origin = os.getenv("HOIKUICT_CLASS_KIOSK_ORIGIN", "").rstrip("/")
    kiosk_url = origin + "/settings/class-kiosk/" if os.getenv("HOIKUICT_CLASS_KIOSK_ENABLED") == "1" and origin else None
    return templates.TemplateResponse(
        request, "settings/index.html", {"current_user": current_user, "restore_enabled": enabled(), "class_kiosk_admin_url": kiosk_url},
        headers={"Cache-Control": "private, no-store"},
    )


def _session_page(request, session, current_user, *, values=None, error="", status_code=200, saved=False):
    policy = get_staff_session_policy(session)
    persisted = {
        "idle_value": str(policy.idle_minutes // 60 if policy.idle_minutes % 60 == 0 else policy.idle_minutes),
        "idle_unit": "hours" if policy.idle_minutes % 60 == 0 else "minutes",
        "absolute_hours": str(policy.absolute_hours),
    }
    latest = session.exec(select(StaffSessionPolicyAudit).order_by(
        StaffSessionPolicyAudit.changed_at.desc(), StaffSessionPolicyAudit.id.desc(),
    )).first()
    return templates.TemplateResponse(request, "settings/staff_sessions.html", {
        "current_user": current_user, "values": values if values is not None else persisted,
        "persisted": persisted, "error": error, "saved": saved, "latest": latest,
    }, status_code=status_code, headers={"Cache-Control": "private, no-store"})


@router.get("/staff-sessions", response_class=HTMLResponse)
def staff_sessions(request: Request, saved: bool = False, session: Session = Depends(get_session),
                   current_user=Depends(get_current_staff_user)):
    require_live_admin(session, current_user)
    return _session_page(request, session, current_user, saved=saved)


@router.post("/staff-sessions", response_class=HTMLResponse)
def save_staff_sessions(request: Request, idle_value: str = Form(""), idle_unit: str = Form(""),
                        absolute_hours: str = Form(""), session: Session = Depends(get_session),
                        current_user=Depends(get_current_staff_user)):
    actor = require_live_admin(session, current_user)
    try:
        policy = parse_session_policy(idle_value, idle_unit, absolute_hours)
    except ValueError as exc:
        return _session_page(request, session, current_user, values={
            "idle_value": idle_value, "idle_unit": idle_unit, "absolute_hours": absolute_hours,
        }, error=str(exc), status_code=400)
    save_staff_session_policy(session, policy, actor)
    return RedirectResponse("/settings/staff-sessions?saved=true", status_code=303,
                            headers={"Cache-Control": "private, no-store"})
