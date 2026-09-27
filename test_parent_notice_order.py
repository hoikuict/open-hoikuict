"""Regression checks for the approved mixed parent notice ordering."""
from datetime import datetime, timedelta, timezone
import unittest

from sqlmodel import Session, select

from models import (
    Notice, NoticePriority, NoticeRead, NoticeStatus, NoticeTarget, NoticeTargetType,
    ParentNotification, ParentNotificationKind, Survey, SurveyStatus, SurveyTarget, SurveyTargetType,
)
import test_parent_portal as fixtures
from time_utils import utc_now


class ParentNoticeOrderTests(unittest.TestCase):
    setUp = fixtures.ParentPortalTests.setUp
    tearDown = fixtures.ParentPortalTests.tearDown
    _login_parent = fixtures.ParentPortalTests._login_parent

    def seed_updates(self):
        now = utc_now().replace(microsecond=0)
        with Session(self.engine) as session:
            for notice in session.exec(select(Notice)).all():
                notice.status = NoticeStatus.draft
                session.add(notice)
            records = [
                ('new-unread', 1, False, False, False),
                ('older-attendance-unread', 3, False, True, True),
                ('old-important-unread', 4, False, False, True),
                ('new-read', 0, True, False, False),
                ('older-attendance-read', 2, True, True, True),
                ('old-read', 5, True, False, False),
            ]
            urls = {}
            for title, hours, read, attendance, important in records:
                at = now - timedelta(hours=hours)
                if attendance:
                    record = ParentNotification(
                        parent_account_id=self.parent_account_id, child_id=self.child_id,
                        kind=ParentNotificationKind.attendance_confirmation_request,
                        title=title, body='架空の出欠確認', is_read=read, created_at=at,
                        source_type='notice-order-test', source_id=title,
                    )
                    session.add(record)
                    session.flush()
                    urls[title] = f'/parent-portal/notifications/{record.id}'
                else:
                    record = Notice(title=title, body='架空のお知らせ', status=NoticeStatus.published,
                                    priority=NoticePriority.high if important else NoticePriority.normal,
                                    created_at=at, publish_start_at=None)
                    session.add(record)
                    session.flush()
                    session.add(NoticeTarget(notice_id=record.id, target_type=NoticeTargetType.all))
                    if read:
                        session.add(NoticeRead(notice_id=record.id, parent_account_id=self.parent_account_id))
                    urls[title] = f'/parent-portal/notices/{record.id}'
            session.commit()
        self._login_parent(self.parent_account_id)
        return urls

    def titles(self, path):
        response = self.client.get(path)
        self.assertEqual(response.status_code, 200)
        key = 'latest_updates' if path == '/parent-portal/' else 'updates'
        titles = [item['title'] for item in response.context[key]]
        positions = [response.text.index('>' + title + '<') for title in titles]
        self.assertEqual(positions, sorted(positions), 'Rendered cards must follow the same order')
        return titles

    def test_home_and_list_mix_kinds_by_unread_then_date(self):
        self.seed_updates()
        expected = ['new-unread', 'older-attendance-unread', 'old-important-unread',
                    'new-read', 'older-attendance-read', 'old-read']
        self.assertEqual(self.titles('/parent-portal/notices'), expected)
        self.assertEqual(self.titles('/parent-portal/'), expected[:5])
        self.assertEqual(self.titles('/parent-portal/attention'), expected[:3])
        response = self.client.get('/parent-portal/notices')
        self.assertIn('重要', response.text)
        self.assertIn('既読', response.text)
        self.assertIn('架空の出欠確認', response.text)

    def test_reading_each_kind_moves_it_to_read_group_without_changing_its_date(self):
        urls = self.seed_updates()
        for title in ('new-unread', 'older-attendance-unread'):
            with self.subTest(kind=title):
                before = {item['title']: item['sort_at'] for item in self.client.get('/parent-portal/notices').context['updates']}
                self.assertEqual(self.client.get(urls[title]).status_code, 200)
                updates = self.client.get('/parent-portal/notices').context['updates']
                self.assertEqual(before, {item['title']: item['sort_at'] for item in updates})
                self.assertFalse(next(item for item in updates if item['title'] == title)['is_unread'])
                self.assertNotIn(title, self.titles('/parent-portal/attention'))
        self.assertEqual(self.titles('/parent-portal/notices'),
                         ['old-important-unread', 'new-read', 'new-unread',
                          'older-attendance-read', 'older-attendance-unread', 'old-read'])

    def test_all_read_or_all_unread_are_date_ordered(self):
        urls = self.seed_updates()
        for url in urls.values():
            self.assertEqual(self.client.get(url).status_code, 200)
        expected = ['new-read', 'new-unread', 'older-attendance-read',
                    'older-attendance-unread', 'old-important-unread', 'old-read']
        self.assertEqual(self.titles('/parent-portal/notices'), expected)
        self.assertEqual(self.titles('/parent-portal/attention'), [])
        with Session(self.engine) as session:
            for read in session.exec(select(NoticeRead)).all():
                session.delete(read)
            for notification in session.exec(select(ParentNotification)).all():
                notification.is_read = False
                session.add(notification)
            session.commit()
        self.assertEqual(self.titles('/parent-portal/notices'), expected)
        self.assertEqual(self.titles('/parent-portal/'), expected[:5])

    def test_publication_date_and_local_survey_time_are_compared_in_same_timezone(self):
        self.seed_updates()
        with Session(self.engine) as session:
            item = session.exec(select(Notice).where(Notice.title == 'new-unread')).one()
            item.publish_start_at = utc_now() - timedelta(days=2)
            session.add(item)
            local_now = datetime.now(timezone(timedelta(hours=9))).replace(tzinfo=None)
            survey = Survey(title='unanswered-survey', status=SurveyStatus.published,
                            opens_at=local_now - timedelta(hours=2))
            session.add(survey)
            session.flush()
            session.add(SurveyTarget(survey_id=survey.id, target_type=SurveyTargetType.all))
            session.commit()
        self.assertEqual(self.titles('/parent-portal/'),
                         ['unanswered-survey', 'older-attendance-unread', 'old-important-unread', 'new-unread', 'new-read'])
        self.assertNotIn('unanswered-survey', self.titles('/parent-portal/notices'))
        self.assertEqual(self.client.get('/parent-portal/').context['unread_notice_count'], 4)


if __name__ == '__main__':
    unittest.main()
