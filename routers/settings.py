from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session, select

from auth import get_current_staff_user
from database import get_session
from models import StaffSessionPolicyAudit
from staff_permissions import require_live_admin
from staff_session_settings import get_staff_session_policy, parse_session_policy, save_staff_session_policy
from template_utils import create_templates

router = APIRouter(prefix="/settings", tags=["settings"])
templates = create_templates()


@router.get("", response_class=HTMLResponse)
@router.get("/", response_class=HTMLResponse, include_in_schema=False)
def settings_index(request: Request, current_user=Depends(get_current_staff_user)):
    return templates.TemplateResponse(
        request, "settings/index.html", {"current_user": current_user},
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
