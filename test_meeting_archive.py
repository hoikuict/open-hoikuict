import base64
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlmodel import Session, select, create_engine
from auth import Role, StaffUser
from models import (MeetingNote, MeetingNoteAction, RecordHighlight, HighlightSourceType,
                    InstitutionalRecordOrigin, EventSeries, EventSeriesMember,
                    EventSeriesMemberTargetType, InstitutionalRecord, InstitutionalRecordLink,
                    RecordLinkTargetType, InstitutionalRecordVisibility)
from test_meeting_notes import MeetingNoteRouterTests
from meeting_note_lifecycle import relations
from institutional_record_service import create_highlight, add_highlight_comment, add_link, add_series_member


class MeetingArchiveTests(unittest.TestCase):
    setUp = MeetingNoteRouterTests.setUp
    tearDown = MeetingNoteRouterTests.tearDown

    def create(self):
        response=self.client.post('/meeting-notes/', follow_redirects=False)
        return int(response.headers['location'].rsplit('/',1)[1])

    def state(self, note_id):
        response=self.client.get(f'/meeting-notes/api/{note_id}/lifecycle')
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def change(self,note_id,action,**overrides):
        s=self.state(note_id)
        payload={'expected_version':s['version'],'expected_revision':s['revision'],'reason':''}
        payload.update(overrides)
        return self.client.post(f'/meeting-notes/api/{note_id}/lifecycle/{action}',json=payload)

    def admin(self):
        self.current_user=StaffUser(role=Role.ADMIN,name='架空管理者')

    def test_archive_restore_keeps_content_and_update_time(self):
        n=self.create()
        with Session(self.engine) as s:
            note=s.get(MeetingNote,n);note.content=b'table-image-body';note.search_text='保管する本文';s.add(note);s.commit();before=note.updated_at
        response=self.change(n,'archive');self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['allowed_actions'],['restore'])
        self.assertNotIn(f'href="/meeting-notes/{n}"',self.client.get('/meeting-notes/').text)
        self.assertIn(f'href="/meeting-notes/{n}"',self.client.get('/meeting-notes/?state=archived&q=保管').text)
        self.assertEqual(self.change(n,'restore').status_code,200)
        with Session(self.engine) as s:
            note=s.get(MeetingNote,n);self.assertEqual((note.content,note.updated_at,note.lifecycle_version),(b'table-image-body',before,2))
            self.assertEqual([a.action for a in s.exec(select(MeetingNoteAction).order_by(MeetingNoteAction.id)).all()],['archive','restore'])

    def test_trash_is_admin_only_and_restores_to_archive(self):
        n=self.create();self.change(n,'archive')
        self.assertEqual(self.change(n,'trash').status_code,403)
        self.admin();self.assertEqual(self.change(n,'trash',reason='重複の見本').status_code,200)
        s=self.state(n);self.assertEqual(s['status'],'trashed');self.assertEqual(s['history'][0]['reason'],'重複の見本')
        self.assertEqual(s['history'][0]['actor'],'架空管理者')
        self.assertEqual(self.client.get(f'/meeting-notes/{n}').status_code,200)
        self.current_user=StaffUser(role=Role.CAN_EDIT,name='架空職員')
        for url in [f'/meeting-notes/{n}',f'/meeting-notes/api/{n}/content',f'/meeting-notes/api/{n}/lifecycle']:
            self.assertEqual(self.client.get(url).status_code,404,url)
        self.assertEqual(self.client.post(f'/meeting-notes/{n}/export/md',json={'title':'x','ops':[]}).status_code,404)
        self.assertEqual(self.client.get('/meeting-notes/?state=trashed').status_code,403)
        self.admin();self.assertEqual(self.change(n,'untrash').json()['status'],'archived')

    def test_viewer_cannot_change_and_archived_can_export(self):
        n=self.create();self.change(n,'archive');self.current_user=StaffUser(role=Role.VIEW_ONLY,name='架空閲覧者')
        self.assertEqual(self.state(n)['allowed_actions'],[])
        self.assertEqual(self.change(n,'restore').status_code,403)
        self.assertEqual(self.client.get(f'/meeting-notes/{n}').status_code,200)
        self.assertEqual(self.client.post(f'/meeting-notes/{n}/export/md',json={'title':'見本','ops':[{'insert':'本文\n'}]}).status_code,200)

    def test_stale_repeated_and_invalid_transitions_do_not_create_history(self):
        n=self.create();stale=self.state(n)
        self.assertEqual(self.change(n,'archive').status_code,200)
        self.assertEqual(self.change(n,'archive',expected_version=stale['version'],expected_revision=stale['revision']).status_code,409)
        self.assertEqual(self.change(n,'delete').status_code,404)
        self.assertEqual(len(self.state(n)['history']),1)
        self.assertEqual(self.change(n,'restore',expected_version=99).status_code,409)
        self.assertEqual(self.state(n)['status'],'archived')

    def test_archive_checks_latest_saved_revision(self):
        n=self.create();stale=self.state(n)
        with Session(self.engine) as s:
            note=s.get(MeetingNote,n);note.title='別職員の新しいタイトル';s.add(note);s.commit()
        r=self.change(n,'archive',expected_revision=stale['revision']);self.assertEqual(r.status_code,409)
        self.assertEqual(self.state(n)['status'],'active');self.assertEqual(self.state(n)['history'],[])

    def test_archived_save_is_rejected_without_losing_content(self):
        n=self.create();self.change(n,'archive')
        r=self.client.post(f'/meeting-notes/api/{n}/save',json={'title':'上書きしない','content_base64':base64.b64encode(b'new').decode(),'editor_version':2})
        self.assertEqual(r.status_code,409);self.assertEqual(r.json()['status'],'state_changed')
        self.assertNotEqual(self.client.get(f'/meeting-notes/api/{n}/content').json()['title'],'上書きしない')

    def test_archiving_and_restoring_invalidates_old_content_revision(self):
        n=self.create();old=self.client.get(f'/meeting-notes/api/{n}/content').json()['revision']
        self.change(n,'archive');self.change(n,'restore')
        r=self.client.post(f'/meeting-notes/api/{n}/save',json={'title':'古いタブ','content_base64':'','editor_version':2,'base_revision':old})
        self.assertEqual(r.status_code,409);self.assertEqual(r.json()['status'],'conflict')

    def test_highlights_and_comments_block_trash(self):
        n=self.create()
        with Session(self.engine) as s:
            h=create_highlight(s,self.current_user,source_type=HighlightSourceType.meeting_note,source_id=n,excerpt='残す根拠',origin=InstitutionalRecordOrigin.operational,comment='残すコメント');s.commit();hid=h.id
        self.change(n,'archive');self.admin();self.assertEqual(self.change(n,'trash').status_code,409)
        with Session(self.engine) as s:
            with self.assertRaises(HTTPException) as error:add_highlight_comment(s,self.current_user,hid,body='不可')
            self.assertEqual(error.exception.status_code,409)
        self.assertEqual(self.state(n)['status'],'archived')

    def test_series_and_record_links_each_block_trash(self):
        for kind in ('series','link'):
            with self.subTest(kind=kind):
                n=self.create()
                with Session(self.engine) as s:
                    if kind=='series':
                        series=EventSeries(name='架空行事');s.add(series);s.flush();s.add(EventSeriesMember(series_id=series.id,target_type=EventSeriesMemberTargetType.meeting_note,target_id=str(n),fiscal_year=2026))
                    else:
                        record=InstitutionalRecord(title='架空経緯',origin=InstitutionalRecordOrigin.operational,background='根拠',purpose='目的');s.add(record);s.flush();s.add(InstitutionalRecordLink(record_id=record.id,target_type=RecordLinkTargetType.meeting_note,target_id=str(n),target_label='見本'))
                    s.commit()
                self.change(n,'archive');self.admin();self.assertEqual(self.change(n,'trash').status_code,409)

    def test_archived_source_rejects_new_references_and_markings(self):
        n=self.create();self.change(n,'archive')
        with Session(self.engine) as s:
            with self.assertRaises(HTTPException) as error:create_highlight(s,self.current_user,source_type=HighlightSourceType.meeting_note,source_id=n,excerpt='不可',origin=InstitutionalRecordOrigin.operational)
            self.assertEqual(error.exception.status_code,409)
            s.rollback()
            self.assertEqual(s.exec(select(RecordHighlight)).all(),[])

    def test_reason_limit_and_version_are_validated(self):
        n=self.create();self.change(n,'archive');self.admin()
        self.assertEqual(self.change(n,'trash',reason='a'*501).status_code,422)
        self.assertEqual(self.change(n,'trash',expected_version=-1).status_code,422)
        self.assertEqual(self.state(n)['status'],'archived')

    def test_new_notes_start_active(self):
        n=self.create();s=self.state(n)
        self.assertEqual((s['status'],s['version'],s['history']),('active',0,[]))

    def test_additive_migration_repeated_preserves_old_rows(self):
        import database
        with tempfile.TemporaryDirectory() as folder:
            engine=create_engine('sqlite:///'+str(Path(folder)/'fixture.sqlite'))
            with engine.begin() as c:
                c.exec_driver_sql('CREATE TABLE meeting_notes (id INTEGER PRIMARY KEY,title VARCHAR,content BLOB)')
                c.exec_driver_sql("INSERT INTO meeting_notes VALUES (1,'架空データ',X'010203')")
            with patch.object(database,'engine',engine):
                database._migrate_add_meeting_note_columns();database._migrate_add_meeting_note_columns()
            with engine.connect() as c:
                self.assertEqual(tuple(c.exec_driver_sql('SELECT title,content,lifecycle_status,lifecycle_version FROM meeting_notes').one()),('架空データ',b'\x01\x02\x03','active',0))
            engine.dispose()


if __name__=='__main__': unittest.main()
