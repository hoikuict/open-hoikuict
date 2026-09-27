"""Read-only list projection and navigation across the existing reply workflow."""
from datetime import timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from sqlalchemy import event
from sqlmodel import Session, select

from auth import Role
from models import AttendanceRecord, Child, ChildStatus, DailyContactEntry, DailyContactReply, DailyContactReplyStatus, ParentContactType
from routers import daily_contacts
from test_spec_changes_20260917 import workbench


def add_contact(w, **values):
    with Session(w.engine) as session:
        entry = DailyContactEntry(child_id=w.child, parent_account_id=w.parent, target_date=w.day, **values)
        session.add(entry)
        session.commit()


def child_row(response, child_id):
    return response.text.split(f'<tr data-child-id="{child_id}">', 1)[1].split('</tr>', 1)[0]


def test_content_all_fields_zero_long_text_escape_and_no_writes(workbench):
    w = workbench
    note = '<script>unexpected()</script>\n' + '長文の連絡事項。' * 100
    add_contact(w, temperature='36.6', mood='元気', sleep_notes='夜中の目覚め', breakfast_status='完食',
                bowel_movement_status='前日夕方からなし', cough='少し', runny_nose='なし', medication='朝に服用',
                condition_note='元気に過ごしました', contact_note=note,
                extra_data={'bedtime':'20:15','wakeup_time':'06:30','breakfast_contents':'ごはんと卵',
                            'stool_consistency':'none','stool_count':0})
    statements = []
    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)
    event.listen(w.engine, 'before_cursor_execute', record)
    try:
        response = w.client.get(f'/daily-contacts/?date={w.day}')
    finally:
        event.remove(w.engine, 'before_cursor_execute', record)
    assert response.status_code == 200
    assert response.headers['cache-control'] == 'private, no-store'
    row = child_row(response, w.child)
    for value in ['36.6℃', '20:15', '06:30', '（0回）', 'ごはんと卵', '夜中の目覚め', '前日夕方からなし', '朝に服用', '元気に過ごしました']:
        assert value in row
    assert '<script>unexpected()' not in row and '&lt;script&gt;unexpected()&lt;/script&gt;' in row
    assert '長文の連絡事項。' * 100 in row
    assert not any(s.lstrip().upper().startswith(('INSERT','UPDATE','DELETE')) for s in statements)
    assert response.context['contact_counts'] == dict(total=2, submitted=1, missing=1, absent=0)
    assert '保護者からの連絡は未提出です' in child_row(response, w.other)


@pytest.mark.parametrize('confirmed,required,expected', [(False,False,'—'),(False,True,'—'),(True,False,'不要'),(True,True,'必要')])
def test_pickup_is_independent_scoped_by_day_and_snack_confirmation(workbench, confirmed, required, expected):
    w = workbench
    with Session(w.engine) as session:
        session.add_all([
            AttendanceRecord(child_id=w.child, attendance_date=w.day, planned_pickup_time='16:45', pickup_person='祖母',
                             pickup_snack_confirmed=confirmed, snack_required=required),
            AttendanceRecord(child_id=w.child, attendance_date=w.day-timedelta(days=1), planned_pickup_time='11:11',pickup_person='過去日'),
        ])
        session.commit()
    response = w.client.get(f'/daily-contacts/?date={w.day}&classroom_id={w.classroom}')
    row = child_row(response, w.child)
    assert '未提出' in row and '16:45' in row and '祖母' in row and '予定のみ登録あり' in row
    assert expected in row.split('補食：',1)[1].split('</span>',1)[0]
    assert '過去日' not in row and '11:11' not in row
    assert set(response.context['pickup_by_child_id']) == {w.child}


@pytest.mark.parametrize('kind', [ParentContactType.absent_sick, ParentContactType.absent_private])
def test_absence_does_not_show_obsolete_present_fields(workbench, kind):
    w = workbench
    add_contact(w, contact_type=kind, absence_temperature='38.1', absence_symptoms='発熱、咳',
                absence_diagnosis='診断名の見本', absence_note='欠席の備考', contact_note='古い出席連絡',
                extra_data={'breakfast_contents':'古い朝食'})
    response = w.client.get(f'/daily-contacts/?date={w.day}')
    row = child_row(response, w.child)
    assert '欠席の備考' in row and '対象外' in row
    assert '古い出席連絡' not in row and '古い朝食' not in row
    assert ('38.1℃' in row) == (kind == ParentContactType.absent_sick)
    assert ('診断名の見本' in row) == (kind == ParentContactType.absent_sick)
    assert response.context['contact_counts']['absent'] == 1


def test_partial_legacy_and_empty_class(workbench):
    w = workbench
    add_contact(w, sleep_notes='従来の睡眠メモ', bowel_movement_status='従来の排便メモ', extra_data=None)
    row = child_row(w.client.get(f'/daily-contacts/?date={w.day}'),w.child)
    assert '従来の睡眠メモ' in row and '従来の排便メモ' in row
    assert '（0回）' not in row and '未提出' not in row
    response = w.client.get(f'/daily-contacts/?date={w.day}&classroom_id=999999')
    assert response.context['contact_counts']['total'] == 0
    assert '対象の園児が見つかりません' in response.text


def test_archived_and_other_class_entries_are_excluded(workbench):
    w = workbench
    add_contact(w, contact_note='表示対象')
    with Session(w.engine) as session:
        child = session.get(Child,w.other)
        child.status = ChildStatus.graduated
        session.add(child)
        session.add(DailyContactEntry(child_id=w.other,parent_account_id=w.parent,target_date=w.day,contact_note='退園済みの連絡'))
        session.commit()
    response = w.client.get(f'/daily-contacts/?date={w.day}')
    assert response.context['contact_counts']['total'] == 1
    assert '退園済みの連絡' not in response.text


def test_status_view_links_sort_and_reply_navigation(workbench):
    w = workbench
    query = f'date={w.day}&classroom_id={w.classroom}&sort=unsent_first&view=status'
    response = w.client.get('/daily-contacts/?'+query)
    assert response.context['selected_view'] == 'status'
    assert 'contact-content-table' not in response.text
    for key in ('detail_query_string',):
        assert parse_qs(response.context[key])['view'] == ['status']
    detail = w.client.get(f'/daily-contacts/{w.child}?'+query)
    for key in ('list_url','previous_url','next_url','history_url'):
        assert parse_qs(urlparse(detail.context[key]).query)['view'] == ['status']
    assert 'name="view" value="status"' in detail.text
    history = w.client.get(detail.context['history_url'])
    assert all('view=status' in row['url'] for row in history.context['rows'])
    saved = w.client.post(f'/daily-contacts/{w.child}/reply',data=dict(date=str(w.day),classroom_id=w.classroom,
        sort='unsent_first',view='status',action='draft',reply_message='返信の見本'),follow_redirects=False)
    assert saved.status_code == 303 and 'view=status' in saved.headers['location']
    error = w.client.post(f'/daily-contacts/{w.child}/reply',data=dict(date=str(w.day),view='status',action='publish',reply_message=''))
    assert error.status_code == 400 and error.context['selected_view'] == 'status'


def test_all_sort_modes_and_unpublished_changes(workbench):
    w = workbench
    add_contact(w)
    with Session(w.engine) as session:
        session.add_all([
            DailyContactReply(child_id=w.child,target_date=w.day,status=DailyContactReplyStatus.published,staff_name='架空職員'),
            DailyContactReply(child_id=w.other,target_date=w.day,status=DailyContactReplyStatus.published,
                              pending_draft={'message':'変更中'},staff_name='架空職員'),
        ])
        session.commit()
    for sort, first in [('submitted_first',w.child),('unsubmitted_first',w.other),('unsent_first',w.other),('classroom',w.child)]:
        response=w.client.get(f'/daily-contacts/?date={w.day}&sort={sort}')
        assert response.context['children'][0].id == first
        assert '未送信の変更あり' in child_row(response,w.other)


def test_viewer_can_read_but_cannot_reply_and_invalid_date_rejected(workbench):
    w = workbench
    w.actor.role = Role.VIEW_ONLY
    assert w.client.get(f'/daily-contacts/?date={w.day}&view=invalid').context['selected_view'] == 'content'
    assert w.client.post(f'/daily-contacts/{w.child}/reply',data=dict(date=str(w.day),reply_message='不可')).status_code == 403
    assert w.client.get('/daily-contacts/?date=invalid').status_code == 400


@pytest.mark.parametrize('raw,expected', [('36.7','36.7℃'),('３６．７','36.7℃'),('36.7℃','36.7°C'),('', ''), (None, '')])
def test_temperature_unit_does_not_duplicate(raw, expected):
    assert daily_contacts._temperature_display(raw) == expected
