from copy import deepcopy
from datetime import timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlmodel import select

from models import Classroom
from time_utils import local_today
from ..auth_adapter import CurrentUser, require_actor, require_can_edit, require_classroom_access
from ..contracts import DocumentStatus, DocumentType
from ..db_models import PlanDocumentRow
from ..services.weekly_library import (VERSION, CONTEXT_LABELS, SaveInput, blank_sheet, examples,
    month_weeks, parse_month, sheet_key, to_document, week_date)
from ..store import ConcurrentUpdateError, DocumentRepositoryDep
from ..templating import render_template

router = APIRouter(tags=['weekly-library'])


def _classrooms(user, repository):
    return [c for c in repository.session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
            if user.can_access_classroom(c.name)]


def _classroom(user, repository, classroom_id):
    classroom = repository.session.get(Classroom, classroom_id)
    if classroom is None:
        raise HTTPException(404, 'クラスが見つかりません')
    require_classroom_access(user, classroom.name)
    return classroom


def _scope(user, repository, classroom_id, start, age, document_id=None):
    week_date(start)
    classroom = _classroom(user, repository, classroom_id)
    key = sheet_key(user.nursery_ref, classroom_id, start, age)
    row = repository.session.exec(select(PlanDocumentRow).where(PlanDocumentRow.weekly_sheet_key == key)).first()
    if document_id is not None and (row is None or row.id != document_id):
        raise HTTPException(404, '週案が見つかりません')
    document = repository.get(row.id) if row else None
    if row and document is None:
        raise HTTPException(409, 'この週案は削除されています。文書一覧を確認してください')
    if document and document.weekly_sheet.get('version') != VERSION:
        raise HTTPException(409, 'この週案の形式は対応していません')
    return classroom, document


def _record(user, repository, classroom_id, start, age):
    _, document = _scope(user, repository, classroom_id, start, age)
    sheet = deepcopy(document.weekly_sheet) if document else blank_sheet()
    for key in ('version', 'age', 'classroom_id'):
        sheet.pop(key, None)
    return {'week_start': start, 'document_id': document.id if document else None,
            'lock_version': repository.lock_version(document.id) if document else 0,
            'sheet': sheet, 'owner_name': document.owner_name if document else user.name,
            'status': document.status.value if document else 'empty',
            'status_label': document.status_label if document else '未作成',
            'editable': user.can_edit and (document is None or document.can_edit_body)}


def _context(user, repository, classroom_id, month, age):
    classroom = _classroom(user, repository, classroom_id)
    starts = month_weeks(month)
    records = [_record(user, repository, classroom_id, d.isoformat(), age) for d in starts]
    monthly = repository.list(nursery_ref=user.nursery_ref, classroom_refs=(classroom.name,), document_type=DocumentType.MONTHLY_PLAN)
    return {'classroom_id': classroom_id, 'classroom_name': classroom.name, 'month': month, 'age': age,
            'records': records, 'editable': user.can_edit,
            'monthly_documents': [{'id': d.id, 'title': d.title, 'month': d.target_month,
                 'url': f'/plans/monthly-library?document_id={d.id}'} for d in monthly
                 if d.monthly_sheet and d.status != DocumentStatus.ARCHIVED]}


@router.get('/weekly-library')
def page(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
         classroom_id: int | None = None, month: str | None = None, age: int = Query(default=0, ge=0, le=5),
         week_start: str | None = None, document_id: int | None = None):
    require_actor(user, request)
    classrooms = _classrooms(user, repository)
    if not classrooms:
        raise HTTPException(403, '参照できるクラスがありません')
    if document_id is not None:
        document = repository.get(document_id)
        if not document or not document.weekly_sheet or document.nursery_ref != user.nursery_ref:
            raise HTTPException(404, '週案が見つかりません')
        classroom_id, age, week_start = document.weekly_sheet['classroom_id'], document.weekly_sheet['age'], document.week_start_date
        if not month or week_date(week_start) not in month_weeks(month):
            month = (week_date(week_start) + timedelta(days=3)).strftime('%Y-%m')
    month = month or local_today().strftime('%Y-%m')
    boot = _context(user, repository, classroom_id or classrooms[0].id, month, age)
    if week_start and week_date(week_start) not in month_weeks(month):
        raise HTTPException(422, '対象週が表示月に含まれていません')
    boot['selected_week'] = week_start or boot['records'][0]['week_start']
    return render_template(request, 'weekly_library/sheet.html', user=user, classrooms=classrooms,
                           boot=boot, context_labels=CONTEXT_LABELS)


@router.get('/weekly-library/context')
def context(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
            classroom_id: int, month: str, age: int = Query(ge=0, le=5)):
    require_actor(user, request)
    return _context(user, repository, classroom_id, month, age)


@router.get('/weekly-library/candidates')
def candidates(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
               classroom_id: int, age: int | None = Query(default=None, ge=0, le=5),
               month: int | None = Query(default=None, ge=1, le=12), keyword: str = Query(default='', max_length=200)):
    require_actor(user, request)
    _classroom(user, repository, classroom_id)
    return {'items': examples(user.nursery_ref, age, month, keyword)}


@router.post('/weekly-library/save')
def save(payload: SaveInput, request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    require_can_edit(user, request)
    _classroom(user, repository, payload.classroom_id)
    allowed = {d.isoformat() for d in month_weeks(payload.month)}
    starts = [i.week_start for i in payload.items]
    if len(set(starts)) != len(starts) or not set(starts) <= allowed:
        raise HTTPException(422, '対象週が重複しているか表示月の範囲外です')
    try:
        connection = repository.session.connection()
        if connection.dialect.name == 'sqlite' and not connection.connection.driver_connection.in_transaction:
            connection.exec_driver_sql('BEGIN IMMEDIATE')
        plans = []
        for item in payload.items:
            classroom, document = _scope(user, repository, payload.classroom_id, item.week_start, payload.age, item.document_id)
            if (document is not None and item.document_id is None) or (document and not document.can_edit_body):
                raise HTTPException(409, 'この週案は作成済み、または閲覧のみです。入力を保持したまま再確認してください')
            if not item.owner_name.strip():
                raise HTTPException(422, '作成者を入力してください')
            if set(item.sheet.context) - set(CONTEXT_LABELS) or any(len(v) > 20000 for v in item.sheet.context.values()):
                raise HTTPException(422, '入力欄または文字数を確認してください')
            if item.sheet.parent_document_id:
                parent = repository.get(item.sheet.parent_document_id)
                if not parent or not parent.monthly_sheet or parent.nursery_ref != user.nursery_ref or parent.classroom_ref != classroom.name or parent.status == DocumentStatus.ARCHIVED:
                    raise HTTPException(422, '接続する月案をこのクラスの新しい月案帳票から選択してください')
            # References are checked against this facility's corpus, never trusted from the browser.
            if item.sheet.source_ids:
                known = {r['id'] for r in examples(user.nursery_ref, limit=None)}
                if not set(item.sheet.source_ids) <= known:
                    raise HTTPException(422, '参考例が変更されています。参照元を確認してください')
            plans.append((item, document, to_document(user, classroom, payload.age, item)))
        for item, document, replacement in plans:
            if document:
                repository.update_document(document.id, title=document.title, owner_name=replacement.owner_name,
                    confirmation_items=[], section_updates={}, weekly_document=replacement,
                    expected_lock_version=item.lock_version, actor_ref=user.actor_ref, commit=False)
            else:
                if item.lock_version != 0:
                    raise HTTPException(409, '新規週案の版が一致しません')
                repository.create(replacement, commit=False)
        repository.session.commit()
    except (ConcurrentUpdateError, IntegrityError, OperationalError) as exc:
        repository.session.rollback()
        raise HTTPException(409, '他の職員が保存したか、保存が混み合っています。入力は保持しています。再確認してください') from exc
    except Exception:
        repository.session.rollback()
        raise
    return _context(user, repository, payload.classroom_id, payload.month, payload.age)


@router.get('/weekly-plans/')
@router.get('/monthly-plans/')
def calendar_page(request: Request, user: CurrentUser, repository: DocumentRepositoryDep,
                  classroom_id: int | None = None, month: str | None = None,
                  year: int | None = Query(default=None, ge=1900, le=2198), age: int = Query(default=0, ge=0, le=5)):
    require_actor(user, request)
    classrooms = _classrooms(user, repository)
    if not classrooms:
        raise HTTPException(403, '参照できるクラスがありません')
    classroom = _classroom(user, repository, classroom_id or classrooms[0].id)
    month = month or local_today().strftime('%Y-%m')
    target = parse_month(month)
    year = year or (target.year - (target.month < 4))
    monthly = request.url.path.rstrip('/').endswith('monthly-plans')
    kind = DocumentType.MONTHLY_PLAN if monthly else DocumentType.WEEKLY_PLAN
    documents = repository.list(nursery_ref=user.nursery_ref, classroom_refs=(classroom.name,), document_type=kind)
    documents = [d for d in documents if d.age_class == f'{age}歳児' and
                 (d.status != DocumentStatus.ARCHIVED or d.weekly_sheet or d.monthly_sheet)]
    cards = []
    if monthly:
        for i in range(12):
            m = f'{year + (i >= 9)}-{(i+3)%12+1:02}'
            matches = [d for d in documents if d.monthly_sheet and d.target_month == m]
            link = '/plans/monthly-library?' + urlencode({'classroom_id': classroom.id, 'target_month': m, 'age': age})
            cards.append({'label': f'{int(m[5:])}月', 'key': m, 'documents': matches, 'url': link})
    else:
        for start in month_weeks(month):
            matches = [d for d in documents if d.week_start_date == start.isoformat()]
            params = {'classroom_id': classroom.id, 'month': month, 'age': age, 'week_start': start.isoformat()}
            current = next((d for d in matches if d.weekly_sheet), None)
            if current:
                params['document_id'] = current.id
            cards.append({'label': f'{start.month}/{start.day}（月）〜{(start+timedelta(days=6)).month}/{(start+timedelta(days=6)).day}（日）',
                          'key': start.isoformat(), 'documents': matches, 'url': '/plans/weekly-library?' + urlencode(params),
                          'plan': current.weekly_sheet if current else None,
                          'days': [{'label': f'{(start+timedelta(days=i)).month}/{(start+timedelta(days=i)).day} {"月火水木金土日"[i]}',
                              'outside': (start+timedelta(days=i)).strftime('%Y-%m') != month,
                              'activity': current.weekly_sheet['days'][i]['activity'] if current and age >= 3 and i < (6 if current.weekly_sheet['include_saturday'] else 5) else ''}
                              for i in range(7)]})
    previous = (target - timedelta(days=1)).strftime('%Y-%m')
    following = (target.replace(day=28) + timedelta(days=4)).replace(day=1).strftime('%Y-%m')
    path = '/plans/monthly-plans/' if monthly else '/plans/weekly-plans/'
    def link(m, y):
        return path + '?' + urlencode({'classroom_id': classroom.id, 'month': m, 'year': y, 'age': age})
    return render_template(request, 'weekly_library/calendar.html', user=user, classrooms=classrooms,
        classroom=classroom, age=age, month=month, year=year, monthly=monthly, cards=cards,
        previous_url=link(month, year-1) if monthly else link(previous, year),
        next_url=link(month, year+1) if monthly else link(following, year))
