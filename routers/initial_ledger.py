from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from sqlmodel import Session

from auth import get_current_staff_user, require_child_record_manager
from csrf import verify_csrf
from database import get_session
from data_transfer_service import TransferMessage
from initial_ledger_import import DATASET, FIELDS, MAX_FILE_BYTES, LedgerPlan, commit_ledger, preview_ledger, read_workbook
from models import DataTransferLog
from routers.data_transfers import _delete_preview_file, _load_preview_file, _preview_owner, _save_preview_file
from template_utils import create_templates

router = APIRouter(prefix="/initial-ledger", tags=["initial_ledger"], dependencies=[Depends(verify_csrf)])
templates = create_templates()
TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates/data_transfers/initial-ledger-template.xlsx"


def _render(request, current_user, *, plan=None, receipt=None, status_code=200):
    return templates.TemplateResponse(request, "data_transfers/initial_ledger.html", {
        "request": request, "current_user": current_user, "plan": plan, "receipt": receipt,
        "fields": FIELDS, "groups": list(dict.fromkeys(f["group"] for f in FIELDS)),
    }, status_code=status_code, headers={"Cache-Control": "no-store"})


def _save(plan, current_user):
    content = json.dumps(plan.rows, ensure_ascii=False, allow_nan=False).encode("utf-8")
    plan.preview_token = _save_preview_file(DATASET, plan.filename, content, owner=_preview_owner(current_user), revision=plan.revision)


@router.get("/", response_class=HTMLResponse)
def index(request: Request, receipt: int | None = None, session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    log = None
    if receipt is not None:
        log = session.get(DataTransferLog, receipt)
        if not log or log.dataset != DATASET or log.result != "success":
            raise HTTPException(404, "登録結果が見つかりません。")
    return _render(request, current_user, receipt=log)


@router.get("/template.xlsx")
def download_template(current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    return FileResponse(TEMPLATE_PATH, filename="hoikuict-initial-ledger-template.xlsx", media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@router.post("/preview", response_class=HTMLResponse)
async def preview(request: Request, file: UploadFile = File(...), session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    filename = Path((file.filename or "initial-ledger.xlsx").replace("\\", "/")).name[:200]
    try:
        if not filename.lower().endswith(".xlsx"):
            raise ValueError("初期台帳テンプレートのExcel（.xlsx）を選択してください。")
        content = await file.read(MAX_FILE_BYTES + 1)
        rows = read_workbook(content)
        plan = preview_ledger(session, rows, filename=filename)
        _save(plan, current_user)
    except ValueError as exc:
        plan = LedgerPlan(filename=filename, errors=[TransferMessage(0, "ファイル", "", str(exc))])
    finally:
        await file.close()
    return _render(request, current_user, plan=plan, status_code=400 if plan.errors else 200)


@router.post("/repreview", response_class=HTMLResponse)
def repreview(request: Request, preview_token: str = Form(""), rows_json: str = Form("", max_length=5_000_000),
              session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    filename, _ = _load_preview_file(preview_token, DATASET, owner=_preview_owner(current_user))
    try:
        source = json.loads(rows_json)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, "編集内容を読み込めません。ファイルを読み込み直してください。") from exc
    plan = preview_ledger(session, source, filename=filename)
    _save(plan, current_user)
    _delete_preview_file(preview_token)
    return _render(request, current_user, plan=plan, status_code=400 if plan.errors else 200)


@router.post("/commit", response_class=HTMLResponse)
def commit(request: Request, preview_token: str = Form(""), confirmed: str = Form(""),
           session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    if confirmed != "yes":
        raise HTTPException(400, "人数と家庭のまとまりを確認してください。")
    filename, content, revision = _load_preview_file(preview_token, DATASET, owner=_preview_owner(current_user), claim=True)
    try:
        rows = json.loads(content)
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, "確認データを読み込み直してください。") from exc
    plan = commit_ledger(session, rows, filename=filename, expected_revision=revision, actor_name=current_user.name,
                         actor_id=str(current_user.user_id) if current_user.user_id else None)
    if plan.committed or plan.already_imported:
        return RedirectResponse(f"/initial-ledger/?receipt={plan.receipt_id}", status_code=303)
    _save(plan, current_user)
    return _render(request, current_user, plan=plan, status_code=400)


@router.post("/cancel")
def cancel(preview_token: str = Form(""), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    _load_preview_file(preview_token, DATASET, owner=_preview_owner(current_user))
    _delete_preview_file(preview_token)
    return RedirectResponse("/initial-ledger/", status_code=303)
