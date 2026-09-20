from __future__ import annotations

import hmac
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session

from auth import get_current_staff_user, require_local_staff_auth
from backup_jobs import list_backup_jobs
from database import get_session
from local_auth import AuthenticationFailed, authenticate_staff, revoke_session_token, verify_password
from restore_control import (
    RestoreError, active_job, confirm_ticket, enabled, grant_viewer, issue_ticket, load_ticket,
    queue_restore, read_job, recent_jobs, service_state, viewer_cookie,
)
from restore_data import RestorePaths, admin_credential, backup_path, inspect_backup, list_backups
from security_config import secure_cookie_enabled
from staff_permissions import require_live_admin
from template_utils import create_templates

router = APIRouter(prefix="/settings/backups/restore", tags=["restore-settings"],
                   dependencies=[Depends(require_local_staff_auth)])
templates = create_templates()


def actor_and_paths(session, current_user):
    actor = require_live_admin(session, current_user)
    if not enabled():
        raise HTTPException(status_code=404, detail="復元機能は設定されていません")
    return actor, RestorePaths.from_environment()


def render(request, current_user, *, stage, status=200, **context):
    return templates.TemplateResponse(request, "backups/restore.html", {
        "current_user": current_user, "stage": stage, "error": "", "reason": "", "selected_id": "", **context,
    }, status_code=status, headers={"Cache-Control": "private, no-store", "Referrer-Policy": "same-origin"})


def render_selection(request, current_user, paths, *, error="", reason="", selected_id="", status=200):
    online = all(service_state(name)["online"] for name in ("worker", "gateway", "backup"))
    return render(request, current_user, stage="select", backups=list_backups(paths), online=online,
                  active=active_job(), history=recent_jobs(), error=error, reason=reason, selected_id=selected_id, status=status)


@router.get("")
def select_backup(request: Request, backup_id: str = "", error: str = "", ticket_id: str = "", session: Session = Depends(get_session),
                  current_user=Depends(get_current_staff_user)):
    actor, paths = actor_and_paths(session, current_user)
    reason = ""
    if ticket_id:
        try:
            ticket = load_ticket(ticket_id, str(actor.id))
            backup_id, reason = ticket["backup_id"], ticket["reason"]
        except RestoreError as exc:
            error = str(exc)
    return render_selection(request, current_user, paths, selected_id=backup_id, reason=reason, error=error)


@router.post("/inspect")
def inspect_selection(request: Request, backup_id: str = Form(""), reason: str = Form(""),
                      session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor, paths = actor_and_paths(session, current_user)
    try:
        if len(reason) > 200:
            raise RestoreError("復元の理由は200文字以内で入力してください。")
        if active_job():
            raise RestoreError("別の復元処理が進行中です。進行状況を確認してください。")
        if not all(service_state(name)["online"] for name in ("worker", "gateway", "backup")):
            raise RestoreError("復元サービスが停止中です。運用担当者に確認してください。")
        result = inspect_backup(paths, backup_id, str(actor.id))
        ticket = issue_ticket({**result, "actor_id": str(actor.id), "actor_name": actor.display_name,
                               "reason": reason.strip()})
    except RestoreError as exc:
        return render_selection(request, current_user, paths, selected_id=backup_id, reason=reason,
                                error=str(exc), status=400)
    return RedirectResponse("/settings/backups/restore/review/" + ticket["ticket_id"], status_code=303)


@router.get("/review/{ticket_id}")
def review(request: Request, ticket_id: str, session: Session = Depends(get_session),
           current_user=Depends(get_current_staff_user)):
    actor, paths = actor_and_paths(session, current_user)
    try:
        ticket = load_ticket(ticket_id, str(actor.id))
    except RestoreError as exc:
        return render_selection(request, current_user, paths, error=str(exc), status=400)
    return render(request, current_user, stage="review", ticket=ticket)


@router.post("/confirm")
def confirmation(request: Request, ticket_id: str = Form(""), acknowledged: str = Form(""),
                 session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor, paths = actor_and_paths(session, current_user)
    try:
        ticket = load_ticket(ticket_id, str(actor.id))
        if acknowledged != "yes":
            return render(request, current_user, stage="review", ticket=ticket,
                          error="戻す日時と影響を確認してください。", status=400)
        ticket = confirm_ticket(ticket_id, str(actor.id))
    except RestoreError as exc:
        return render_selection(request, current_user, paths, error=str(exc), status=400)
    return render(request, current_user, stage="confirm", ticket=ticket)


def progress_redirect(job_id: str, token: str):
    path = "/settings/backups/restore/jobs/" + job_id
    response = RedirectResponse(path, status_code=303, headers={"Cache-Control": "no-store"})
    response.set_cookie(viewer_cookie(job_id), token, max_age=86400, httponly=True,
                        secure=secure_cookie_enabled(), samesite="strict", path=path)
    return response


@router.post("/execute")
def execute(request: Request, ticket_id: str = Form(""), password: str = Form("", max_length=1024),
            session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor, paths = actor_and_paths(session, current_user)
    ticket = None
    try:
        ticket = load_ticket(ticket_id, str(actor.id))
        if not ticket.get("confirmed"):
            raise RestoreError("戻す日時と影響を確認してください。")
        credential = admin_credential(paths.data / "hoikuict.db", str(actor.id))
        if not hmac.compare_digest(credential["fingerprint"], ticket["credential_fingerprint"]):
            raise RestoreError("確認後に管理者情報が変わりました。復元元の選択からやり直してください。")
        # Reuse the normal password verifier, persistent throttling and audit events.
        result = authenticate_staff(session, login_id=credential["login_id_normalized"], password=password, request=request)
        revoke_session_token(session, result.session_token, reason="restore_reauthentication")
        if result.user.id != actor.id:
            raise RestoreError("管理者の再確認に失敗しました。")
        target = admin_credential(backup_path(paths, ticket["backup_id"]) / "db/hoikuict.db", str(actor.id))
        if not hmac.compare_digest(target["fingerprint"], ticket["target_credential_fingerprint"]):
            raise RestoreError("確認後に復元元が変わりました。復元元の選択からやり直してください。")
        if not verify_password(target["password_hash"], password):
            raise RestoreError("現在のパスワードでは復元後にログインできません。このバックアップの復元は運用担当者に確認してください。")
        if any(job.get("status") in {"queued", "running"} for job in list_backup_jobs()):
            raise RestoreError("バックアップの作成が進行中です。完了後に実行してください。")
        job, token = queue_restore(ticket_id, str(actor.id))
    except AuthenticationFailed:
        return render(request, current_user, stage="confirm", ticket=ticket,
                      error="管理者パスワードを確認してください。続けて失敗した場合は時間をおいてください。", status=400)
    except RestoreError as exc:
        if ticket:
            return render(request, current_user, stage="confirm", ticket=ticket, error=str(exc), status=400)
        return render_selection(request, current_user, paths, error=str(exc), status=400)
    return progress_redirect(job["job_id"], token)


@router.post("/cancel")
def cancel(ticket_id: str = Form(""), session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor, _ = actor_and_paths(session, current_user)
    from restore_control import control_dir, exclusive_lock, identifier
    try:
        with exclusive_lock():
            load_ticket(ticket_id, str(actor.id))
            (control_dir() / "tickets" / (identifier(ticket_id) + ".json")).unlink()
    except RestoreError as exc:
        return RedirectResponse("/settings/backups/restore?" + urlencode({"error": str(exc)}), status_code=303)
    return RedirectResponse("/settings/backups", status_code=303)


@router.get("/resume/{job_id}")
def resume_progress(job_id: str, session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    actor_and_paths(session, current_user)
    try:
        read_job(job_id)
        return progress_redirect(job_id, grant_viewer(job_id))
    except RestoreError as exc:
        return RedirectResponse("/settings/backups/restore?" + urlencode({"error": str(exc)}), status_code=303)
