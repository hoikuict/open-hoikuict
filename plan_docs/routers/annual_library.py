from copy import deepcopy
import json

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from models import Classroom, StaffClassroomAssignment, User
from time_utils import local_today
from ..auth_adapter import CurrentUser, require_actor, require_can_edit, require_classroom_access
from ..contracts import DocumentStatus, DocumentType
from ..db_models import PlanDocumentRow, PlanRevisionRow
from ..models import PlanDocument
from ..services.annual_library import (
    OriginInput, SaveInput, TEMPLATE_IDS, confirmation_items, digest, import_sheet,
    pending_count, source_choices, validate_fields, class_key, reference_choices,
)
from ..store import ConcurrentUpdateError, DocumentRepositoryDep
from ..templating import render_template
from ..services import reflection_reviews

router = APIRouter(prefix="/annual-library", tags=["annual-library"])


def _begin(repository, write=False):
    conn = repository.session.connection()
    if conn.dialect.name == "sqlite" and not conn.connection.driver_connection.in_transaction:
        conn.exec_driver_sql("BEGIN IMMEDIATE" if write else "BEGIN")


def _document(user, repository, document_id):
    document = repository.get(document_id)
    if (not document or not document.annual_sheet
            or document.document_type != DocumentType.ANNUAL_PLAN
            or document.nursery_ref != user.nursery_ref):
        raise HTTPException(404, "年案が見つかりません")
    classroom = repository.session.get(Classroom, document.annual_sheet["classroom_id"])
    require_classroom_access(user, classroom.name if classroom else document.classroom_ref)
    if document.annual_sheet.get("template_id") not in TEMPLATE_IDS:
        raise HTTPException(409, "この年案の様式には対応していません")
    return document


def _scope(user, repository, classroom_id, school_year, document_id=None):
    if not 1900 <= school_year <= 2199:
        raise HTTPException(422, "年度は1900〜2199年で指定してください")
    classroom = repository.session.get(Classroom, classroom_id)
    if not classroom:
        raise HTTPException(404, "クラスが見つかりません")
    require_classroom_access(user, classroom.name)
    ages = range(6)
    if not document_id:
        try:
            matched = {s["age"] for s in source_choices(user.nursery_ref)
                       if class_key(s["class_name"]) == class_key(classroom.name)}
            if len(matched) == 1:
                ages = matched
        except HTTPException:
            pass  # Saved documents remain accessible when external sources are unavailable.
    keys = [json.dumps([user.nursery_ref, classroom_id, school_year, age], ensure_ascii=False) for age in ages]
    rows = repository.session.exec(select(PlanDocumentRow).where(
        PlanDocumentRow.annual_sheet_key.in_(keys))).all() if not document_id else []
    if len(rows) > 1:
        raise HTTPException(409, "年案が複数あります。文書一覧から対象を選択してください")
    found_id = document_id or (rows[0].id if rows else None)
    document = _document(user, repository, found_id) if found_id else None
    if document and (document.school_year != school_year
                     or document.annual_sheet["classroom_id"] != classroom_id):
        raise HTTPException(404, "指定した年度・クラスの年案が見つかりません")
    return classroom, document


def _new_sheet(user, repository, classroom_id, school_year, origin):
    if origin.kind == "source":
        sheet = import_sheet(user.nursery_ref, classroom_id, origin.key)
        return sheet, _registered_teachers(repository.session, classroom_id)
    if not origin.document_id or not origin.revision_id:
        raise HTTPException(422, "引き継ぐ年案と改訂を選択してください")
    previous = _document(user, repository, origin.document_id)
    revision = repository.session.get(PlanRevisionRow, origin.revision_id)
    if (not revision or revision.document_id != previous.id
            or previous.school_year != school_year - 1
            or not revision.snapshot.get("annual_sheet")):
        raise HTTPException(422, "前年の年案を選択してください")
    sheet = deepcopy(revision.snapshot["annual_sheet"])
    if sheet.get("template_id") not in TEMPLATE_IDS:
        raise HTTPException(422, "前年の帳票の様式が異なります")
    sheet["classroom_id"] = classroom_id
    sheet["baseline"] = deepcopy(sheet["fields"])
    sheet["baseline_label"] = f"{previous.school_year}年度 {previous.classroom_ref}（改訂{revision.revision_no}）"
    sheet["origin"] = origin.model_dump(exclude_none=True)
    sheet["source_digest"] = digest({"revision_id": revision.id, "snapshot": revision.snapshot})
    # A new year's document is a draft. Approval and responsible staff are not copied.
    return sheet, _registered_teachers(repository.session, classroom_id)


def _registered_teachers(session, classroom_id):
    today = local_today()
    rows = session.exec(select(User.display_name).join(StaffClassroomAssignment,
        StaffClassroomAssignment.staff_user_id == User.id).where(
        StaffClassroomAssignment.classroom_id == classroom_id,
        StaffClassroomAssignment.starts_on <= today,
        (StaffClassroomAssignment.ends_on.is_(None) | (StaffClassroomAssignment.ends_on >= today)),
        User.is_active.is_(True)).order_by(StaffClassroomAssignment.display_order,
            User.staff_sort_order, User.display_name, User.id)).all()
    return "・".join(dict.fromkeys(rows))


def _previous_choices(user, repository, school_year):
    result = []
    for document in repository.list(nursery_ref=user.nursery_ref, document_type=DocumentType.ANNUAL_PLAN):
        classroom = repository.session.get(Classroom, document.annual_sheet["classroom_id"]) if document.annual_sheet else None
        if (document.school_year != school_year - 1 or not document.annual_sheet
                or document.annual_sheet.get("template_id") not in TEMPLATE_IDS
                or not user.can_access_classroom(classroom.name if classroom else document.classroom_ref)):
            continue
        head = repository.head(document.id)
        if head:
            result.append({"document_id": document.id, "revision_id": head.current_revision_id,
                           "classroom_id": document.annual_sheet["classroom_id"],
                           "title": document.title, "status": document.status_label})
    return result


def _context(user, repository, classroom_id, school_year, document_id=None, origin=None):
    _begin(repository)
    classroom, document = _scope(user, repository, classroom_id, school_year, document_id)
    sheet, owner = None, _registered_teachers(repository.session, classroom_id)
    lock = 0
    if document:
        sheet, owner = deepcopy(document.annual_sheet), document.owner_name
        head = repository.head(document.id)
        revision = repository.session.get(PlanRevisionRow, head.current_revision_id)
        if (not revision or revision.snapshot.get("annual_sheet") != sheet
                or revision.snapshot.get("owner_name") != owner):
            raise HTTPException(409, "年案が更新されました。もう一度開いてください")
        lock = head.lock_version
    elif origin:
        sheet, owner = _new_sheet(user, repository, classroom_id, school_year, origin)
    sources, references, source_error = [], [], None
    try:
        sources = source_choices(user.nursery_ref)
        matches = [s for s in sources if class_key(s["class_name"]) == class_key(classroom.name)]
        if matches:
            sources = matches
        references = reference_choices(user.nursery_ref, classroom.name, school_year)
        current = [s for s in matches if s["year"] == school_year]
        if not sheet and not origin and len(current) == 1:
            sheet, owner = _new_sheet(user, repository, classroom_id, school_year,
                                     OriginInput(kind="source", key=current[0]["key"]))
    except HTTPException as exc:
        source_error = exc.detail
    reflection_states = [reflection_reviews.state(repository.session, document, i) for i in range(4)] if document else []
    periods, columns = reflection_reviews.annual_layout(sheet["age"]) if sheet else ([], [])
    return {
        "document_id": document.id if document else None, "lock_version": lock,
        "classroom_id": classroom_id, "classroom_name": document.classroom_ref if document else classroom.name,
        "school_year": school_year, "age": sheet["age"] if sheet else None, "nursery_name": user.nursery_ref,
        "owner_name": owner, "sheet": sheet,
        "editable": user.can_edit and (not document or document.can_edit_body),
        "status": document.status_label if document else "未保存",
        "sources": sources, "references": references, "source_error": source_error,
        "previous": _previous_choices(user, repository, school_year),
        "pending_timings": pending_count(sheet) if sheet else 0,
        "created_at": document.created_at.isoformat() if document else None,
        "reflection": [r["values"] for r in reflection_states] if document else [["", ""] for _ in range(4)],
        "reflection_states": reflection_states or [{"version": 0, "status": "draft", "label": "下書き", "locked": False, "review_id": None} for _ in range(4)],
        "reflection_columns": columns, "reflection_periods": periods,
        "reflection_editable": user.can_edit and (not document or document.status != DocumentStatus.ARCHIVED),
    }


@router.get("")
def page(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
         document_id: int | None = Query(default=None, gt=0),
         classroom_id: int | None = Query(default=None, gt=0),
         school_year: int | None = Query(default=None, ge=1900, le=2199)):
    require_actor(user, request)
    classrooms = [c for c in repository.session.exec(
        select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        if user.can_access_classroom(c.name)]
    if not classrooms:
        raise HTTPException(403, "参照できるクラスがありません")
    if document_id:
        document = _document(user, repository, document_id)
        classroom_id, school_year = document.annual_sheet["classroom_id"], document.school_year
    today = local_today()
    boot = _context(user, repository, classroom_id or classrooms[0].id,
                    school_year or today.year - (today.month < 4), document_id)
    return render_template(request, "annual_library/sheet.html", user=user,
                           boot=boot, classrooms=classrooms)


@router.get("/context")
def context(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
            classroom_id: int = Query(gt=0), school_year: int = Query(ge=1900, le=2199),
            document_id: int | None = Query(default=None, gt=0),
            source_key: str | None = Query(default=None, max_length=100),
            previous_id: int | None = Query(default=None, gt=0),
            revision_id: int | None = Query(default=None, gt=0)):
    require_actor(user, request)
    if source_key and previous_id:
        raise HTTPException(422, "取り込み元は1つ選択してください")
    origin = (OriginInput(kind="source", key=source_key) if source_key else
              OriginInput(kind="previous", document_id=previous_id, revision_id=revision_id)
              if previous_id else None)
    return _context(user, repository, classroom_id, school_year, document_id, origin)


@router.post("/save")
def save(payload: SaveInput, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_can_edit(user, request)
    if not payload.owner_name.strip():
        raise HTTPException(422, "担任名を入力してください。登録がない場合は手入力できます。")
    _begin(repository, write=True)
    classroom, document = _scope(user, repository, payload.classroom_id,
                                 payload.school_year, payload.document_id)
    if document:
        if payload.document_id != document.id or not document.can_edit_body:
            raise HTTPException(409, "既存の年案を開き直してください。入力内容は保持されています")
        sheet = deepcopy(document.annual_sheet)
    else:
        if not payload.origin or payload.lock_version != 0:
            raise HTTPException(422, "既存の年案または前年の年案を選択してください")
        sheet, _ = _new_sheet(user, repository, payload.classroom_id, payload.school_year, payload.origin)
    if payload.source_digest != sheet["source_digest"]:
        raise HTTPException(409, "取り込み元が変更されています。入力内容は保持されています")
    sheet["fields"] = validate_fields(payload, sheet)
    title = f"{payload.school_year}年度 年間指導計画（{document.classroom_ref if document else classroom.name}・{sheet['age']}歳児）"
    try:
        if document:
            repository.update_document(document.id, title=title, owner_name=payload.owner_name,
                confirmation_items=confirmation_items(sheet), section_updates={},
                annual_sheet=sheet, expected_lock_version=payload.lock_version, actor_ref=user.actor_ref)
        else:
            document = repository.create(PlanDocument(id=0, document_type=DocumentType.ANNUAL_PLAN,
                title=title, status=DocumentStatus.DRAFT, nursery_ref=user.nursery_ref,
                classroom_ref=classroom.name, actor_ref=user.actor_ref, owner_name=payload.owner_name,
                sections=[], annual_sheet=sheet, school_year=payload.school_year, age_class=f"{sheet['age']}歳児",
                confirmation_items=confirmation_items(sheet)))
    except (ConcurrentUpdateError, IntegrityError) as exc:
        repository.session.rollback()
        raise HTTPException(409, "他の保存と競合しました。入力内容を保持しています。別画面で最新版を確認してください") from exc
    return _context(user, repository, payload.classroom_id, payload.school_year, document.id)
