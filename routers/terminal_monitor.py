from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlmodel import Session

from auth import get_current_staff_user
from database import get_session
from models import GuardianTerminalStatus
from template_utils import create_templates
from terminal_monitor_service import terminal_statuses

router = APIRouter(prefix="/settings/guardian-terminals", tags=["guardian_terminals"])
templates = create_templates()


@router.get("/alert", response_class=HTMLResponse)
def monitor_alert(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "管理者権限が必要です。")
    return templates.TemplateResponse(
        request,
        "guardian/_monitor_alert.html",
        {
            "terminal_alerts": [
                row for row in terminal_statuses(session) if row["stale"]
            ],
        },
        headers={"Cache-Control": "no-store"},
    )


@router.get("", response_class=HTMLResponse)
def monitor(
    request: Request,
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "管理者権限が必要です。")
    return templates.TemplateResponse(
        request,
        "guardian/monitor.html",
        {
            "current_user": current_user,
            "statuses": terminal_statuses(session),
        },
    )


@router.post("/{device_id}")
def save_monitor(
    device_id: str,
    label: str = Form(...),
    enabled: str = Form(""),
    start_hour: int = Form(...),
    end_hour: int = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    if not current_user.is_admin:
        raise HTTPException(403, "管理者権限が必要です。")
    terminal = session.get(GuardianTerminalStatus, device_id)
    if terminal is None:
        raise HTTPException(404, "端末が見つかりません。")
    if not label.strip() or len(label) > 100 or not 0 <= start_hour < end_hour <= 24:
        raise HTTPException(400, "端末名と監視時間（0〜24時）を確認してください。")
    terminal.label = label.strip()
    terminal.monitoring_enabled = enabled == "yes"
    terminal.start_hour, terminal.end_hour = start_hour, end_hour
    session.add(terminal)
    session.commit()
    return RedirectResponse("/settings/guardian-terminals", status_code=303)
