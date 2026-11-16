from __future__ import annotations

from copy import deepcopy
import json
import sqlite3

from fastapi import APIRouter, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import ValidationError
from html import escape
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import select

from models import Classroom
from time_utils import local_today
from ..auth_adapter import CurrentUser, require_actor, require_can_edit, require_classroom_access
from ..contracts import DocumentStatus, DocumentType
from ..db_models import PlanDocumentRow, PlanRevisionRow
from ..models import PlanDocument
from ..services.monthly_library import (
    COLUMNS, DOMAINS, PERSONAL, TEMPLATES, TEMPLATE_VERSION, SaveInput,
    field_definitions, month_date, new_sheet, previous_months, search_phrases,
    validated_fields,
)
from ..store import ConcurrentUpdateError, DocumentRepositoryDep
from ..services.monthly_ai import GenerateInput, availability, generate
from ..services.monthly_export import ExportInput, export_context, render_export
from ..templating import render_template

from ..services.monthly_access import can_edit_monthly, require_monthly_edit, EDIT_REASON
from ..services.monthly_presence import PresenceInput, heartbeat
from ..services.monthly_merge import baseline_token, read_baseline, merge_cells

router = APIRouter(prefix="/monthly-library", tags=["monthly-library"])


def _scope(user, repository, classroom_id, target_month, age, document_id=None):
    month_date(target_month)
    if age not in range(6):
        raise HTTPException(422, "年齢クラスは0〜5歳で指定してください")
    classroom = repository.session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(404, "クラスが見つかりません")
    require_classroom_access(user, classroom.name)
    if document_id is None:
        key = json.dumps([user.nursery_ref, classroom_id, target_month, age], ensure_ascii=False)
        row = repository.session.exec(select(PlanDocumentRow).where(
            PlanDocumentRow.monthly_sheet_key == key)).first()
        document_id = row.id if row else None
    document = repository.get(document_id) if document_id else None
    if document_id and (not document or not document.monthly_sheet
                        or document.nursery_ref != user.nursery_ref
                        or document.target_month != target_month
                        or document.monthly_sheet["classroom_id"] != classroom_id
                        or document.monthly_sheet["age"] != age):
        raise HTTPException(404, "月案が見つかりません")
    if document:
        require_classroom_access(user, document.classroom_ref)
    sheet = deepcopy(document.monthly_sheet) if document else new_sheet(
        repository.session, classroom, target_month, age)
    if document and document.can_edit_body and age < 3:
        # Enrolments can change after the first draft. Add current members without
        # removing former members or moving any existing child's text.
        known = {child["ref"] for child in sheet["children"]}
        roster = new_sheet(repository.session, classroom, target_month, age)["children"]
        sheet["children"].extend(child for child in roster if child["ref"] not in known)
    if sheet.get("template_version") != TEMPLATE_VERSION:
        raise HTTPException(409, "この帳票の版は対応していません")
    return classroom, document, sheet


def _begin_snapshot(repository, *, write=False):
    connection = repository.session.connection()
    if connection.dialect.name == "sqlite" and not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")


def _context(user, repository, classroom_id, target_month, age, document_id=None):
    _begin_snapshot(repository)
    classroom, document, sheet = _scope(user, repository, classroom_id, target_month, age, document_id)
    head = repository.head(document.id) if document else None
    if head:
        revision = repository.session.get(PlanRevisionRow, head.current_revision_id)
        if (revision is None or revision.snapshot.get("monthly_sheet") != document.monthly_sheet
                or revision.snapshot.get("owner_name") != document.owner_name):
            raise HTTPException(409, "月案が更新されました。入力は保持しています。もう一度お試しください")
    allowed = can_edit_monthly(repository.session, user, classroom_id, target_month)
    result = {"document_id": document.id if document else None,
            "lock_version": head.lock_version if head else 0,
            "classroom_id": classroom.id, "classroom_name": classroom.name,
            "target_month": target_month, "age": age, "sheet": sheet,
            "owner_name": document.owner_name if document else user.name,
            "editable": allowed and (document is None or document.can_edit_body),
            "edit_reason": EDIT_REASON if not allowed else ("この状態の月案は閲覧のみです。" if document and not document.can_edit_body else "対象月の担当者として編集できます。"),
            "status": document.status_label if document else "未保存",
            "definitions": field_definitions(sheet, target_month),
            "ai": availability(user.nursery_ref),
            "template": TEMPLATES[min(age, 3)],
            "personal": PERSONAL, "columns": COLUMNS, "domains": DOMAINS}
    result["base_token"] = baseline_token(user, repository, result) if result["editable"] else None
    return result


@router.get("")
def page(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
         document_id: int | None = None):
    require_actor(user, request)
    classrooms = [c for c in repository.session.exec(
        select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        if user.can_access_classroom(c.name)]
    if not classrooms:
        raise HTTPException(403, "参照できるクラスがありません")
    classroom_id, target_month, age = classrooms[0].id, local_today().strftime("%Y-%m"), 0
    if document_id:
        document = repository.get(document_id)
        if not document or not document.monthly_sheet or document.nursery_ref != user.nursery_ref:
            raise HTTPException(404, "月案が見つかりません")
        classroom_id, target_month, age = (document.monthly_sheet["classroom_id"],
                                         document.target_month, document.monthly_sheet["age"])
    boot = _context(user, repository, classroom_id, target_month, age, document_id)
    return render_template(request, "monthly_library/sheet.html", user=user, boot=boot,
                           classrooms=classrooms)


@router.get("/context")
def context(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
            classroom_id: int, target_month: str, age: int = Query(ge=0, le=5),
            document_id: int | None = None):
    require_actor(user, request)
    return _context(user, repository, classroom_id, target_month, age, document_id)


@router.post("/presence")
def presence(payload: PresenceInput, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_actor(user, request)
    context = _context(user, repository, payload.classroom_id, payload.target_month, payload.age, payload.document_id)
    try:
        return heartbeat(repository.session, user, payload, context)
    except (OSError, sqlite3.Error) as exc:
        raise HTTPException(503, "編集中の状況を確認できません。入力内容は保持されています") from exc


@router.get("/candidates")
def candidates(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
               classroom_id: int, target_month: str, field: str,
               age: int = Query(ge=0, le=5), keyword: str = Query(default="", max_length=200),
               offset: int = Query(default=0, ge=0, le=100000), document_id: int | None = None):
    require_actor(user, request)
    _, _, sheet = _scope(user, repository, classroom_id, target_month, age, document_id)
    definition = field_definitions(sheet, target_month).get(field)
    if definition is None:
        raise HTTPException(422, "候補の対象欄が不正です")
    return search_phrases(user.nursery_ref, definition, age, month_date(target_month).month,
                          keyword, offset)


@router.post("/generate")
def generate_candidates(payload: GenerateInput, request: Request, user: CurrentUser,
                        repository: DocumentRepositoryDep):
    require_can_edit(user, request)
    require_monthly_edit(repository.session, user, payload.classroom_id, payload.target_month)
    _, document, sheet = _scope(user, repository, payload.classroom_id,
        payload.target_month, payload.age, payload.document_id)
    if document and not document.can_edit_body:
        raise HTTPException(409, "この状態の月案は編集できません")
    definition = field_definitions(sheet, payload.target_month).get(payload.field)
    if not definition or not definition["section"]:
        raise HTTPException(422, "この欄はAI提案の対象ではありません")
    return generate(user.nursery_ref, payload, definition)


@router.post("/export")
def export(payload: ExportInput, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    return _export_response(payload, request, user, repository)


def _export_response(payload, request, user, repository, pdf_attachment=False):
    require_actor(user, request)
    classroom, document, sheet = _scope(user, repository, payload.classroom_id,
        payload.target_month, payload.age, payload.document_id)
    if payload.mode == "current":
        require_monthly_edit(repository.session, user, payload.classroom_id, payload.target_month)
    snapshot = export_context(payload, user, repository, classroom, document, sheet)
    return render_export(snapshot, payload.kind, payload.mode,
        fixture=bool(getattr(request.app.state, 'monthly_library_fixture', False)),
        pdf_attachment=pdf_attachment, download_snapshot=payload.model_dump_json(),
        csrf_token=request.cookies.get('hoikuict_csrf', ''))


@router.post("/export-file")
def export_file(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
                snapshot: str = Form(max_length=4000000), download_pdf: bool = Form(default=False)):
    # A native form response works in browsers that do not support blob: tabs/downloads.
    try:
        payload = ExportInput.model_validate_json(snapshot)
        response = _export_response(payload, request, user, repository, pdf_attachment=download_pdf)
        if payload.kind == 'pdf' and not download_pdf:
            return HTMLResponse(json.loads(response.body)['html'], headers={'Cache-Control':'no-store'})
        return response
    except ValidationError:
        message, code = '出力する入力内容を確認してください。', 422
    except HTTPException as exc:
        if exc.status_code == 303:
            raise
        message, code = str(exc.detail), exc.status_code
    return HTMLResponse('<!doctype html><html lang="ja"><meta charset="utf-8"><title>月案の出力</title>'
        '<main><h1>出力できませんでした</h1><p>' + escape(message) + '</p>'
        '<p>編集画面の入力は保持されています。編集画面に戻ってもう一度お試しください。</p></main></html>',
        status_code=code, headers={'Cache-Control':'no-store'})


def _save_merged(payload, user, repository):
    base = read_baseline(payload, user, repository)
    if not payload.owner_name.strip():
        raise HTTPException(422, "担任名を入力してください")
    for attempt in range(3):
        # Rollback also expires identity-map objects after a competing CAS wins.
        if attempt:
            repository.session.rollback()
            repository.session.expire_all()
        _begin_snapshot(repository, write=True)
        require_monthly_edit(repository.session, user, payload.classroom_id, payload.target_month)
        latest = _context(user, repository, payload.classroom_id, payload.target_month,
                          payload.age, payload.document_id)
        if not latest["editable"]:
            raise HTTPException(409, latest["edit_reason"])
        sheet = deepcopy(latest["sheet"])
        # A baseline's verified provenance stays valid even if a peer cleared it.
        validation_sheet = deepcopy(sheet)
        for key, cell in base["fields"].items():
            entry = validation_sheet["fields"].setdefault(key, {"body": "", "origins": []})
            entry["origins"] = cell.get("origins", []) + entry.get("origins", [])
        mine = {"fields": validated_fields(payload, validation_sheet, user.nursery_ref),
                "owner": payload.owner_name}
        merged, conflicts, remote = merge_cells(base, mine,
            {"fields": sheet["fields"], "owner": latest["owner_name"]})
        def field_label(key):
            label = "担任名" if key == "@owner" else latest["definitions"].get(key, {}).get("label", key)
            if key.startswith("child:"):
                ref = ":".join(key.split(":")[:2])
                child = next((c["name"] for c in sheet["children"] if c["ref"] == ref), "")
                label = child + " / " + label
            return label
        if conflicts:
            raise HTTPException(409, {"kind": "cell_conflict", "latest": latest,
                "conflicts": [{"key": key, "label": field_label(key)} for key in conflicts]})
        if sum(len(cell.get("body", "")) for cell in merged["fields"].values()) > 500000:
            raise HTTPException(422, "本文が保存可能な容量を超えています")
        sheet["fields"] = merged["fields"]
        title = f"{payload.target_month} 月案（{latest['classroom_name']}・{payload.age}歳児）"
        try:
            if latest["document_id"]:
                document = repository.get(latest["document_id"])
                repository.update_document(document.id, title=title, owner_name=merged["owner"],
                    confirmation_items=document.confirmation_items, section_updates={},
                    monthly_sheet=sheet, expected_lock_version=latest["lock_version"], actor_ref=user.actor_ref)
            else:
                target = month_date(payload.target_month)
                document = repository.create(PlanDocument(id=0, document_type=DocumentType.MONTHLY_PLAN,
                    title=title, status=DocumentStatus.DRAFT, nursery_ref=user.nursery_ref,
                    classroom_ref=latest["classroom_name"], actor_ref=user.actor_ref,
                    owner_name=merged["owner"], sections=[], monthly_sheet=sheet,
                    target_month=payload.target_month, age_class=f"{payload.age}歳児",
                    school_year=target.year - (target.month < 4)))
        except OperationalError as exc:
            if getattr(exc.orig, "sqlite_errorcode", 0) & 255 not in (5, 6):
                raise
            continue
        except (ConcurrentUpdateError, IntegrityError):
            continue
        result = _context(user, repository, payload.classroom_id, payload.target_month, payload.age, document.id)
        result["merged_remote_fields"] = [field_label(key) for key in remote]
        return result
    repository.session.rollback()
    raise HTTPException(409, "更新が続いています。入力は保持しています。もう一度保存してください")


@router.post("/save")
def save(payload: SaveInput, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_can_edit(user, request)
    _begin_snapshot(repository, write=True)
    require_monthly_edit(repository.session, user, payload.classroom_id, payload.target_month)
    if payload.base_token:
        return _save_merged(payload, user, repository)
    if not payload.owner_name.strip():
        raise HTTPException(422, "担任名を入力してください")
    classroom, document, sheet = _scope(user, repository, payload.classroom_id,
                                        payload.target_month, payload.age, payload.document_id)
    if document and (payload.document_id != document.id or not document.can_edit_body):
        raise HTTPException(409, "既存の月案を開き直してください。入力内容は保持されています")
    sheet["fields"] = validated_fields(payload, sheet, user.nursery_ref)
    title = f"{payload.target_month} 月案（{classroom.name}・{payload.age}歳児）"
    try:
        if document:
            repository.update_document(document.id, title=title, owner_name=payload.owner_name,
                confirmation_items=document.confirmation_items, section_updates={},
                monthly_sheet=sheet, expected_lock_version=payload.lock_version,
                actor_ref=user.actor_ref)
        else:
            target = month_date(payload.target_month)
            document = repository.create(PlanDocument(
                id=0, document_type=DocumentType.MONTHLY_PLAN, title=title,
                status=DocumentStatus.DRAFT, nursery_ref=user.nursery_ref,
                classroom_ref=classroom.name, actor_ref=user.actor_ref,
                owner_name=payload.owner_name, sections=[], monthly_sheet=sheet,
                target_month=payload.target_month, age_class=f"{payload.age}歳児",
                school_year=target.year - (target.month < 4)))
    except (ConcurrentUpdateError, IntegrityError) as exc:
        repository.session.rollback()
        raise HTTPException(409, "他の職員の保存と競合しました。入力内容を保持しています。別画面で最新版を確認してください") from exc
    return _context(user, repository, payload.classroom_id, payload.target_month, payload.age, document.id)


@router.get("/history")
def history(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
            classroom_id: int, target_month: str, child_ref: str,
            age: int = Query(ge=0, le=2), document_id: int | None = None):
    require_actor(user, request)
    _, _, sheet = _scope(user, repository, classroom_id, target_month, age, document_id)
    if child_ref not in {c["ref"] for c in sheet["children"]}:
        raise HTTPException(404, "園児が見つかりません")
    months = previous_months(target_month)
    documents = repository.list(nursery_ref=user.nursery_ref)
    documents = [d for d in documents if d.target_month in months
                 and user.can_access_classroom(d.classroom_ref)]
    result = []
    for month in months:
        matching = [d for d in documents if d.target_month == month and d.monthly_sheet
                    and child_ref in {c["ref"] for c in d.monthly_sheet["children"]}
                    and any(d.monthly_sheet["fields"].get(f"{child_ref}:{key}", {}).get("body", "").strip()
                            for key, _ in PERSONAL)]
        records = []
        for document in matching:
            fields = document.monthly_sheet["fields"]
            records.append({"document_id": document.id, "status": document.status_label,
                "classroom": document.classroom_ref, "age": document.monthly_sheet["age"],
                "template_id": document.monthly_sheet["template_id"],
                "template_version": document.monthly_sheet["template_version"],
                "updated_at": document.updated_at.isoformat(),
                "fields": {key: fields.get(f"{child_ref}:{key}", {"body": ""}) for key, _ in PERSONAL}})
        # Older individual plans keep their original labels. Never invent a
        # correspondence between observed/predicted states or reflection viewpoints.
        legacy = [{"document_id": d.id, "title": d.title, "status": d.status_label,
                   "sections": [{"title": s.title, "body": s.body} for s in d.sections]}
                  for d in documents if d.target_month == month and d.child_ref == child_ref
                  and d.document_type == DocumentType.INDIVIDUAL_PLAN and not d.monthly_sheet]
        result.append({"month": month, "records": records, "legacy": legacy})
    return {"child_ref": child_ref, "months": result, "version_policy": "latest_saved"}
