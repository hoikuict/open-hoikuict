from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth import get_current_staff_user, require_admin
from backup_jobs import (
    BackupJobConflict,
    enqueue_backup,
    list_backup_jobs,
    worker_status,
)
from backup_schedule import (
    WEEKDAY_LABELS,
    BackupScheduleError,
    default_backup_schedule,
    load_backup_schedule,
    next_scheduled_run,
    save_backup_schedule,
)
from template_utils import create_templates
from security_config import is_public_demo


def require_backup_environment() -> None:
    if is_public_demo():
        raise HTTPException(404, "Not Found")


router = APIRouter(
    prefix="/settings/backups", tags=["backup-settings"],
    dependencies=[Depends(require_backup_environment)],
)
templates = create_templates()

STATUS_LABELS = {
    "queued": "待機中",
    "running": "実行中",
    "succeeded": "成功",
    "failed": "失敗",
}


@router.get("", response_class=HTMLResponse)
def backup_settings_page(
    request: Request,
    message: str | None = Query(default=None),
    error: str | None = Query(default=None),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    jobs = list_backup_jobs()
    active_job = next(
        (job for job in jobs if job.get("status") in {"queued", "running"}),
        None,
    )
    schedule_error = None
    try:
        schedule = load_backup_schedule()
        next_run = next_scheduled_run(schedule)
    except BackupScheduleError as exc:
        schedule = default_backup_schedule()
        next_run = None
        schedule_error = str(exc)
    return templates.TemplateResponse(
        request,
        "backups/settings.html",
        {
            "request": request,
            "current_user": current_user,
            "jobs": jobs,
            "active_job": active_job,
            "worker": worker_status(),
            "status_labels": STATUS_LABELS,
            "schedule": schedule,
            "schedule_error": schedule_error,
            "next_run_jst": next_run.isoformat(timespec="minutes") if next_run else None,
            "weekday_options": list(enumerate(WEEKDAY_LABELS)),
            "message": message,
            "error": error,
        },
    )


@router.post("/create")
def request_backup(
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    if worker_status().get("status") != "online":
        query = urlencode(
            {"error": "バックアップ実行サービスが起動していません。運用サービスを確認してください。"}
        )
        return RedirectResponse(url=f"/settings/backups?{query}", status_code=303)
    try:
        enqueue_backup(
            requested_by_id=(
                str(current_user.user_id) if current_user.user_id is not None else None
            ),
            requested_by_name=current_user.name,
        )
    except BackupJobConflict as exc:
        query = urlencode({"error": str(exc)})
        return RedirectResponse(url=f"/settings/backups?{query}", status_code=303)
    query = urlencode({"message": "バックアップの実行を受け付けました。"})
    return RedirectResponse(url=f"/settings/backups?{query}", status_code=303)


@router.post("/schedule")
def update_backup_schedule(
    enabled: str | None = Form(default=None),
    frequency: str = Form(default="daily"),
    run_time: str = Form(default="02:00"),
    weekday: int = Form(default=0),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    try:
        save_backup_schedule(
            enabled=enabled in {"1", "true", "on", "yes"},
            frequency=frequency,
            run_time=run_time,
            weekday=weekday,
            updated_by_id=(
                str(current_user.user_id) if current_user.user_id is not None else None
            ),
            updated_by_name=current_user.name,
        )
    except BackupScheduleError as exc:
        query = urlencode({"error": str(exc)})
        return RedirectResponse(url=f"/settings/backups?{query}", status_code=303)
    query = urlencode({"message": "定期実行設定を保存しました。"})
    return RedirectResponse(url=f"/settings/backups?{query}", status_code=303)
