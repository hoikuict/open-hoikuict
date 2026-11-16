"""Age-specific weekly sheets; all source references are read-only."""
from copy import deepcopy
from datetime import date, timedelta
import calendar
import json
import os
from pathlib import Path

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from ..contracts import DocumentStatus, DocumentType
from ..models import PlanDocument, PlanSchedule, ScheduleCell, ScheduleColumn, ScheduleRow, SectionBlock

VERSION = 1
DAY_NAMES = ['月', '火', '水', '木', '金', '土']
CONTEXT_LABELS = {
    'related_monthly_summary': '月案から今週へつなぐ文脈',
    'previous_week_reflection': '前週の振り返り',
    'current_children_snapshot': '現在の子どもの姿',
    'weekly_activities_note': '今週の主な活動・経験',
    'seasonal_context': '季節・行事・生活の流れ',
    'family_context': '家庭からの情報',
    'class_notes': '担任間で共有したい配慮',
}


class DayInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    activity: str = Field(default='', max_length=20000)
    support: str = Field(default='', max_length=20000)
    preparation: str = Field(default='', max_length=20000)


class SheetInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    aim: str = Field(default='', max_length=20000)
    activity: str = Field(default='', max_length=20000)
    support_preparation: str = Field(default='', max_length=20000)
    reflection: str = Field(default='', max_length=20000)
    days: list[DayInput] = Field(min_length=6, max_length=6)
    context: dict[str, str] = Field(default_factory=dict, max_length=7)
    include_saturday: bool = True
    parent_document_id: int | None = Field(default=None, gt=0)
    source_ids: list[str] = Field(default_factory=list, max_length=50)


class SaveItem(BaseModel):
    model_config = ConfigDict(extra='forbid')
    week_start: str
    document_id: int | None = Field(default=None, gt=0)
    lock_version: int = Field(ge=0)
    sheet: SheetInput
    owner_name: str = Field(min_length=1, max_length=200)


class SaveInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    classroom_id: int
    month: str
    age: int = Field(ge=0, le=5)
    items: list[SaveItem] = Field(min_length=1, max_length=6)


def parse_month(value):
    try:
        if len(value) != 7:
            raise ValueError()
        result = date.fromisoformat(value + '-01')
        if not 1900 <= result.year <= 2199:
            raise ValueError()
        return result
    except (TypeError, ValueError):
        raise HTTPException(422, '対象月を正しく指定してください')


def month_weeks(value):
    month = parse_month(value)
    return [days[0] for days in calendar.Calendar(firstweekday=0).monthdatescalendar(month.year, month.month)]


def week_date(value):
    try:
        result = date.fromisoformat(value)
        if result.weekday() != 0 or not 1900 <= result.year <= 2199:
            raise ValueError()
        return result
    except (ValueError, TypeError):
        raise HTTPException(422, '対象週は月曜日の日付で指定してください')


def sheet_key(nursery, classroom_id, start, age):
    return json.dumps([nursery, classroom_id, start, age], ensure_ascii=False)


def blank_sheet():
    return SheetInput(days=[DayInput() for _ in DAY_NAMES], context={key: '' for key in CONTEXT_LABELS}).model_dump()


def to_document(user, classroom, age, item):
    start = week_date(item.week_start)
    sheet = item.sheet.model_dump() | {'version': VERSION, 'classroom_id': classroom.id, 'age': age}
    sheet['context'] = {key: sheet['context'].get(key, '') for key in CONTEXT_LABELS}
    sections = [SectionBlock('weekly_goal', '今週のねらい', sheet['aim'], ['form.weekly'], ['入力']),
                SectionBlock('weekly_reflection', '評価・反省', sheet['reflection'], ['form.weekly'], ['入力'])]
    if age < 3:
        sections[1:1] = [SectionBlock('weekly_activity', '活動', sheet['activity'], ['form.weekly'], ['入力']),
                        SectionBlock('weekly_support_preparation', '配慮・援助すること／準備', sheet['support_preparation'], ['form.weekly'], ['入力'])]
    sections += [SectionBlock(key, label, sheet['context'].get(key, ''), ['form.weekly'], ['入力'])
                 for key, label in CONTEXT_LABELS.items()]
    schedule = None
    if age >= 3:
        columns = [ScheduleColumn('activity', '子どもの主な活動'), ScheduleColumn('support', '援助・配慮事項'), ScheduleColumn('preparation', '準備')]
        schedule = PlanSchedule('weekly_grid', columns, [ScheduleRow(
            row_key=['mon','tue','wed','thu','fri','sat'][i], label=f'{(start + timedelta(days=i)).strftime("%m/%d")}（{DAY_NAMES[i]}）', order=i,
            cells={c.key: ScheduleCell(body=sheet['days'][i][c.key]) for c in columns})
            for i in range(6 if sheet['include_saturday'] else 5)])
    return PlanDocument(id=0, document_type=DocumentType.WEEKLY_PLAN, status=DocumentStatus.DRAFT,
        title=f'{start.isoformat()}週 週案（{classroom.name}・{age}歳児）', nursery_ref=user.nursery_ref,
        classroom_ref=classroom.name, actor_ref=user.actor_ref, owner_name=item.owner_name.strip(),
        sections=sections, schedule=schedule, school_year=start.year - (start.month < 4),
        target_week=f'{start.isocalendar().year}-W{start.isocalendar().week:02}', week_start_date=start.isoformat(),
        age_class=f'{age}歳児', parent_document_id=sheet['parent_document_id'], weekly_sheet=sheet)


def examples(nursery, age=None, month=None, keyword='', *, limit=100):
    """A facility-scoped, reviewed JSON corpus; never write source workbooks."""
    configured = os.getenv('HOIKU_WEEKLY_LIBRARY_SOURCES', '{}')
    try:
        source = json.loads(configured).get(nursery)
        if not source:
            return []
        data = json.loads(Path(source['path']).read_text(encoding='utf-8'))
        if data.get('schema_version') != VERSION:
            raise ValueError('schema')
        rows = data['examples']
        tokens = keyword.casefold().split()
        matches = [r for r in rows if (age is None or r['age'] == age) and (month is None or r['month'] == month)
                   and all(t in json.dumps([r['title'],r['aim'],r['activity'],r['support_preparation'],r['days']], ensure_ascii=False).casefold() for t in tokens)]
        return deepcopy(matches if limit is None else matches[:limit])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise HTTPException(503, '参考例を読み込めません。入力内容は保持されています') from exc
