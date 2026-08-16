import os
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import MOCK_CALENDAR_USER_COOKIE, MOCK_ROLE_COOKIE, MOCK_STAFF_NAME_COOKIE
from child_records.models import ChildRecordSettingVersion
from child_records.settings import default_config
from models import Child, ChildStatus, Classroom, User
from plan_docs.auth_adapter import DEFAULT_NURSERY_REF
from plan_docs.contracts import DocumentType
from plan_docs.db_models import (
    PlanDocumentAction,
    PlanDocumentHeadRow,
    PlanDocumentRow,
    PlanDailyReflectionRow,
    PlanExecutionChangeRow,
    PlanReviewNotificationRow,
    PlanRevisionRow,
)
from plan_docs.routers.bunrei import router as bunrei_router
from plan_docs.routers.documents import router as documents_router
from plan_docs.routers.home import router as home_router
from plan_docs.routers.plans import router as plans_router
import plan_docs.auth_adapter as plan_docs_auth
from testing_helpers import configure_test_environment


class PlanDocsIntegrationTests(unittest.TestCase):
    def setUp(self):
        configure_test_environment()
        self.corpus_directory = tempfile.TemporaryDirectory()
        self.corpus_path = Path(self.corpus_directory.name) / "daily_plan_examples.sqlite"
        self._create_example_corpus()
        self.original_corpus_path = os.environ.get(
            "HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH"
        )
        os.environ["HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH"] = str(self.corpus_path)
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        with Session(self.engine) as session:
            session.add(Classroom(name="ひよこ組", display_order=1))
            session.add(Classroom(name="うさぎ組", display_order=2))
            session.commit()

        self.app = FastAPI()
        self.app.include_router(home_router, prefix="/plans")
        self.app.include_router(plans_router, prefix="/plans")
        self.app.include_router(documents_router, prefix="/plans")
        self.app.include_router(bunrei_router, prefix="/plans")

        @self.app.get("/healthz")
        def healthz():
            return {"status": "ok"}

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[plan_docs_auth.get_session] = override_get_session
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()
        if self.original_corpus_path is None:
            os.environ.pop("HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH", None)
        else:
            os.environ["HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH"] = self.original_corpus_path
        self.corpus_directory.cleanup()

    def _create_example_corpus(self):
        with closing(sqlite3.connect(self.corpus_path)) as connection:
            connection.executescript(
                """
                create table corpus_metadata (
                    key text primary key,
                    value text not null
                );
                create table daily_plan_examples (
                    id text primary key,
                    target_date text not null,
                    month integer not null,
                    school_year integer not null,
                    age_class integer not null,
                    class_label text not null,
                    title text not null,
                    main_activity_raw text not null,
                    main_activity_normalized text not null,
                    content_text text,
                    timeline_text text,
                    child_state_text text,
                    support_text text,
                    considerations_text text,
                    reflection_text text,
                    source_ref text not null,
                    content_hash text not null,
                    quality_score real not null,
                    review_status text not null,
                    pii_review_status text not null
                );
                create table daily_plan_activity_blocks (
                    id integer primary key,
                    daily_plan_id text not null,
                    position integer not null,
                    time_label text,
                    activity_name text,
                    activity_text text,
                    child_state_text text,
                    support_text text,
                    considerations_text text
                );
                create table daily_plan_aims (
                    daily_plan_id text not null,
                    position integer not null,
                    aim_text text not null
                );
                """
            )
            connection.executemany(
                "insert into corpus_metadata(key, value) values (?, ?)",
                [("schema_version", "2-runtime"), ("corpus_version", "test-v2")],
            )
            connection.executemany(
                """
                insert into daily_plan_examples(
                    id, target_date, month, school_year, age_class, class_label,
                    title, main_activity_raw, main_activity_normalized, content_text,
                    timeline_text, child_state_text, support_text, considerations_text,
                    reflection_text, source_ref, content_hash, quality_score,
                    review_status, pii_review_status
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        "daily-001",
                        "2025-08-10",
                        8,
                        2025,
                        3,
                        "旧3歳児クラス",
                        "粘土遊びの日案",
                        "粘土遊び",
                        "粘土遊び",
                        "粘土で興味のあるものを制作する",
                        "10:00",
                        "粘土に興味を持ち、手にする",
                        "興味を持たない子どもに声をかける",
                        "用具の置き場所と誤飲に配慮する",
                        "",
                        "legacy:001",
                        "hash-001",
                        0.9,
                        "approved",
                        "approved",
                    ),
                    (
                        "daily-draft",
                        "2025-08-11",
                        8,
                        2025,
                        3,
                        "旧3歳児クラス",
                        "未確認の日案",
                        "未確認",
                        "未確認",
                        "未確認",
                        "未確認",
                        "未確認",
                        "未確認",
                        "未確認",
                        "",
                        "legacy:draft",
                        "hash-draft",
                        0.5,
                        "pending",
                        "approved",
                    ),
                    (
                        "daily-unmasked",
                        "2025-08-12",
                        8,
                        2025,
                        3,
                        "旧3歳児クラス",
                        "匿名化未確認の日案",
                        "匿名化未確認",
                        "匿名化未確認",
                        "匿名化未確認",
                        "匿名化未確認",
                        "匿名化未確認",
                        "匿名化未確認",
                        "匿名化未確認",
                        "",
                        "legacy:unmasked",
                        "hash-unmasked",
                        0.4,
                        "approved",
                        "pending",
                    ),
                ],
            )
            connection.execute(
                """
                insert into daily_plan_activity_blocks(
                    daily_plan_id, position, time_label, activity_name, activity_text,
                    child_state_text, support_text, considerations_text
                ) values (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "daily-001",
                    0,
                    "10:00〜10:45",
                    "粘土遊び",
                    "粘土で制作する",
                    "粘土に興味を持ち、手にする",
                    "興味を持たない子どもに声をかける",
                    "用具の置き場所と誤飲に配慮する",
                ),
            )
            connection.execute(
                "insert into daily_plan_aims(daily_plan_id, position, aim_text) values (?, ?, ?)",
                ("daily-001", 0, "粘土の感触を味わい、形の変化を楽しむ"),
            )
            connection.commit()

    def staff_cookies(self, *, role="admin", staff_id=None, name="Test%20Staff"):
        return {
            MOCK_ROLE_COOKIE: role,
            MOCK_STAFF_NAME_COOKIE: name,
            MOCK_CALENDAR_USER_COOKIE: str(staff_id or uuid4()),
        }

    def create_daily_plan(self, *, cookies=None):
        self.client.cookies.update(cookies or self.staff_cookies())
        response = self.client.post(
            "/plans/daily-plans",
            data={
                "target_date": "2026-08-10",
                "classroom_ref": "ひよこ組",
                "age_class": "3歳児",
                "owner_name": "Test Staff",
                "daily_aims": "水の冷たさや感触を味わう",
                "daily_content": "園庭で水遊びをする",
                "timeline_row_key": "row_1",
                "timeline_time": "10:00〜10:45",
                "timeline_activity": "水遊び",
                "timeline_children": "水に触れ、遊び方を試している",
                "timeline_support": "遊び方を見守り、必要に応じて声をかける",
                "timeline_considerations": "滑りやすい場所を確認し安全を見守る",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        return int(response.headers["location"].rstrip("/").split("/")[-1])

    def create_monthly_plan(self, *, cookies=None):
        self.client.cookies.update(cookies or self.staff_cookies())
        response = self.client.post(
            "/plans/monthly-plans",
            data={
                "target_month": "2026-08",
                "class_name": "ひよこ組",
                "classroom_ref": "ひよこ組",
                "owner_name": "月案作成者",
                "current_children_snapshot": "水遊びを繰り返し楽しんでいる。",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        return int(response.headers["location"].rstrip("/").split("/")[-1])

    def test_plan_docs_home_uses_main_mock_staff_session(self):
        self.client.cookies.update(self.staff_cookies())
        response = self.client.get("/plans/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("文書作成", response.text)
        self.assertIn("Test Staff", response.text)
        self.assertIn("/plans/annual-plans/new", response.text)
        self.assertNotIn("/staff/session", response.text)

    def test_htmx_post_without_staff_redirects_to_staff_login(self):
        response = self.client.post(
            "/plans/annual-plans",
            data={"school_year": "2026", "classroom_ref": "ひよこ組"},
            headers={"HX-Request": "true"},
        )

        self.assertEqual(response.status_code, 401)
        self.assertIn("HX-Redirect", response.headers)
        self.assertTrue(response.headers["HX-Redirect"].startswith("/staff/login?redirect="))

    def test_healthz(self):
        response = self.client.get("/healthz")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

    def test_daily_plan_is_persisted_with_head_and_immutable_revision(self):
        document_id = self.create_daily_plan()

        with Session(self.engine) as session:
            row = session.get(PlanDocumentRow, document_id)
            head = session.exec(
                select(PlanDocumentHeadRow).where(
                    PlanDocumentHeadRow.document_id == document_id
                )
            ).one()
            revisions = session.exec(
                select(PlanRevisionRow).where(PlanRevisionRow.document_id == document_id)
            ).all()

        self.assertIsNotNone(row)
        self.assertEqual(head.lock_version, 1)
        self.assertEqual(len(revisions), 1)
        self.assertEqual(head.current_revision_id, revisions[0].id)

        response = self.client.get(f"/plans/api/documents/{document_id}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["target_date"], "2026-08-10")
        self.assertEqual(response.json()["lock_version"], 1)
        self.assertEqual(
            [section["section_key"] for section in response.json()["sections"]],
            [
                "daily_goal",
                "daily_content",
            ],
        )
        section_bodies = {
            section["section_key"]: section["body"]
            for section in response.json()["sections"]
        }
        self.assertEqual(
            section_bodies["daily_goal"], "水の冷たさや感触を味わう"
        )
        self.assertEqual(section_bodies["daily_content"], "園庭で水遊びをする")
        self.assertEqual(
            [column["key"] for column in response.json()["schedule"]["columns"]],
            ["children", "support", "considerations"],
        )
        self.assertEqual(
            response.json()["schedule"]["rows"][0]["cells"]["considerations"]["body"],
            "滑りやすい場所を確認し安全を見守る",
        )

        detail = self.client.get(f"/plans/documents/{document_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        goal_position = detail.text.index("<h2>ねらい</h2>")
        content_position = detail.text.index("<h2>内容（活動）</h2>")
        timeline_position = detail.text.index("<h2>1日の流れ</h2>")
        self.assertLess(goal_position, content_position)
        self.assertLess(content_position, timeline_position)
        self.assertEqual(detail.text.count("<h2>ねらい</h2>"), 1)
        self.assertEqual(detail.text.count("<h2>内容（活動）</h2>"), 1)

    def test_daily_plan_calendar_shows_activity_and_missing_class_days(self):
        document_id = self.create_daily_plan()

        calendar_response = self.client.get("/plans/daily-plans/?year=2026&month=8")
        self.assertEqual(calendar_response.status_code, 200, calendar_response.text)
        self.assertIn("日案カレンダー", calendar_response.text)
        self.assertIn("2026年8月", calendar_response.text)
        self.assertIn("<th>月</th>", calendar_response.text)
        self.assertIn("<th>金</th>", calendar_response.text)
        self.assertNotIn("<th>土</th>", calendar_response.text)
        self.assertNotIn("<th>日</th>", calendar_response.text)
        self.assertNotIn('aria-label="8月1日', calendar_response.text)
        self.assertNotIn('aria-label="8月2日', calendar_response.text)
        self.assertIn(
            'aria-label="8月10日 ひよこ組 水遊び"',
            calendar_response.text,
        )
        self.assertIn(
            f'href="/plans/documents/{document_id}"',
            calendar_response.text,
        )
        self.assertIn(
            'aria-label="8月11日 うさぎ組 未作成"',
            calendar_response.text,
        )
        self.assertIn(
            "target_date=2026-08-11&amp;classroom_ref=%E3%81%86%E3%81%95%E3%81%8E%E7%B5%84",
            calendar_response.text,
        )

        prefilled = self.client.get(
            "/plans/daily-plans/new?target_date=2026-08-11&classroom_ref="
            "%E3%81%86%E3%81%95%E3%81%8E%E7%B5%84"
        )
        self.assertEqual(prefilled.status_code, 200, prefilled.text)
        self.assertIn(
            'name="target_date" type="date" required value="2026-08-11"',
            prefilled.text,
        )
        self.assertIn(
            'value="うさぎ組" selected',
            prefilled.text,
        )

        searched = self.client.get(
            "/plans/daily-plans/new?target_date=2026-08-11&classroom_ref="
            "%E3%81%86%E3%81%95%E3%81%8E%E7%B5%84&age_class=3%E6%AD%B3%E5%85%90&month=8"
        )
        self.assertIn(
            'name="target_date" type="hidden" value="2026-08-11"',
            searched.text,
        )
        self.assertIn(
            "example_id=daily-001&target_date=2026-08-11&classroom_ref="
            "%E3%81%86%E3%81%95%E3%81%8E%E7%B5%84",
            searched.text,
        )

        copied = self.client.get(
            "/plans/daily-plans/new?target_date=2026-08-11&classroom_ref="
            "%E3%81%86%E3%81%95%E3%81%8E%E7%B5%84&age_class=3%E6%AD%B3%E5%85%90"
            "&month=8&example_id=daily-001"
        )
        self.assertIn(
            'name="target_date" type="date" required value="2026-08-11"',
            copied.text,
        )

    def test_daily_reflection_submission_calendar_status_and_reminders(self):
        editor_id = uuid4()
        editor_cookies = self.staff_cookies(
            role="can_edit",
            staff_id=editor_id,
            name="Daily%20Owner",
        )
        document_id = self.create_daily_plan(cookies=editor_cookies)

        detail = self.client.get(f"/plans/documents/{document_id}")
        self.assertIn("その日の振り返り", detail.text)
        self.assertIn("振り返り未入力", detail.text)

        draft = self.client.post(
            f"/plans/documents/{document_id}/reflection/draft",
            data={"reflection_body": "水に触れる時間を十分に取れた。"},
        )
        self.assertEqual(draft.status_code, 200, draft.text)
        self.assertIn("振り返り下書き", draft.text)
        with Session(self.engine) as session:
            reflection = session.exec(
                select(PlanDailyReflectionRow).where(
                    PlanDailyReflectionRow.document_id == document_id
                )
            ).one()
        self.assertEqual(reflection.status, "draft")
        self.assertIsNone(reflection.submitted_at)

        calendar_response = self.client.get("/plans/daily-plans/?year=2026&month=8")
        self.assertIn("振り返り下書き", calendar_response.text)

        jst = timezone(timedelta(hours=9))
        reminder_at = datetime(2026, 8, 10, 16, 30, tzinfo=jst)
        with patch("plan_docs.routers.home.local_now", return_value=reminder_at):
            owner_home = self.client.get("/plans/")
        self.assertIn("振り返りが未提出です", owner_home.text)
        self.assertIn("本日16:30締切", owner_home.text)

        self.client.cookies.update(
            self.staff_cookies(role="admin", staff_id=uuid4(), name="Principal")
        )
        next_day = datetime(2026, 8, 11, 9, 0, tzinfo=jst)
        with patch("plan_docs.routers.home.local_now", return_value=next_day):
            admin_home = self.client.get("/plans/")
        self.assertIn("Test Staffさんの振り返りが未提出", admin_home.text)

        self.client.cookies.update(editor_cookies)
        empty_submit = self.client.post(
            f"/plans/documents/{document_id}/reflection",
            data={"reflection_body": "", "action": "submit"},
            follow_redirects=False,
        )
        self.assertEqual(empty_submit.status_code, 422)

        submitted = self.client.post(
            f"/plans/documents/{document_id}/reflection",
            data={
                "reflection_body": "水に触れる時間を十分に取れた。",
                "action": "submit",
            },
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 303, submitted.text)
        self.assertIn(
            "振り返り提出済み",
            self.client.get("/plans/daily-plans/?year=2026&month=8").text,
        )

        edited_after_submit = self.client.post(
            f"/plans/documents/{document_id}/reflection/draft",
            data={"reflection_body": "水遊びの時間配分を明日は短くする。"},
        )
        self.assertIn("振り返り下書き", edited_after_submit.text)
        with Session(self.engine) as session:
            reflection = session.exec(
                select(PlanDailyReflectionRow).where(
                    PlanDailyReflectionRow.document_id == document_id
                )
            ).one()
        self.assertEqual(reflection.status, "draft")
        self.assertIsNone(reflection.submitted_at)

    def test_daily_plan_form_can_choose_only_approved_corpus_example(self):
        self.client.cookies.update(self.staff_cookies())

        listed = self.client.get(
            "/plans/daily-plans/new?age_class=3%E6%AD%B3%E5%85%90&month=8"
        )
        self.assertEqual(listed.status_code, 200, listed.text)
        self.assertIn("粘土遊びの日案", listed.text)
        self.assertNotIn("未確認の日案", listed.text)
        self.assertNotIn("匿名化未確認の日案", listed.text)
        self.assertIn("test-v2", listed.text)

        selected = self.client.get(
            "/plans/daily-plans/new?age_class=3%E6%AD%B3%E5%85%90&month=8&example_id=daily-001"
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertIn("10:00〜10:45", selected.text)
        self.assertIn("粘土の感触を味わい、形の変化を楽しむ", selected.text)
        self.assertIn("粘土で興味のあるものを制作する", selected.text)
        self.assertIn("興味を持たない子どもに声をかける", selected.text)
        self.assertIn("用具の置き場所と誤飲に配慮する", selected.text)
        self.assertIn('name="timeline_activity" type="hidden"', selected.text)
        self.assertNotIn('textarea name="timeline_activity"', selected.text)

    def test_calendar_selection_infers_search_age_and_month_from_classroom(self):
        with Session(self.engine) as session:
            session.add(Classroom(name="りす組（1歳児）", display_order=3))
            session.commit()
        self.client.cookies.update(self.staff_cookies())

        calendar_response = self.client.get(
            "/plans/daily-plans/?year=2026&month=9&classroom_ref="
            "%E3%82%8A%E3%81%99%E7%B5%84%EF%BC%881%E6%AD%B3%E5%85%90%EF%BC%89"
        )
        self.assertEqual(calendar_response.status_code, 200, calendar_response.text)
        self.assertIn(
            "target_date=2026-09-01&amp;classroom_ref="
            "%E3%82%8A%E3%81%99%E7%B5%84%EF%BC%881%E6%AD%B3%E5%85%90%EF%BC%89"
            "&amp;age_class=1%E6%AD%B3%E5%85%90&amp;month=9",
            calendar_response.text,
        )

        selected = self.client.get(
            "/plans/daily-plans/new?target_date=2026-09-01&classroom_ref="
            "%E3%82%8A%E3%81%99%E7%B5%84%EF%BC%881%E6%AD%B3%E5%85%90%EF%BC%89"
        )
        self.assertEqual(selected.status_code, 200, selected.text)
        self.assertEqual(selected.text.count('value="1歳児" selected'), 2)
        self.assertIn('<option value="9" selected>9月</option>', selected.text)
        self.assertIn(
            'name="target_date" type="date" required value="2026-09-01"',
            selected.text,
        )

    def test_selected_corpus_timeline_is_copied_then_freely_editable(self):
        self.client.cookies.update(self.staff_cookies())

        created = self.client.post(
            "/plans/daily-plans",
            data={
                "target_date": "2026-08-13",
                "classroom_ref": "ひよこ組",
                "age_class": "3歳児",
                "owner_name": "Test Staff",
                "example_id": "daily-001",
                "example_source_ref": "client値は信用しない",
                "timeline_row_key": "corpus_1",
                "timeline_time": "10:15〜11:00",
                "timeline_activity": "粘土と自然物で制作する",
                "timeline_children": "木の実を粘土へ押し込み、模様を比べる",
                "timeline_support": "素材の違いに気づける言葉を添える",
                "timeline_considerations": "木の実の大きさと誤飲に配慮する",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        document_id = int(created.headers["location"].rstrip("/").split("/")[-1])

        copied = self.client.get(f"/plans/api/documents/{document_id}").json()
        row = copied["schedule"]["rows"][0]
        self.assertEqual(row["start_time"], "10:15〜11:00")
        self.assertEqual(row["label"], "粘土と自然物で制作する")
        self.assertEqual(
            row["cells"]["children"]["body"],
            "木の実を粘土へ押し込み、模様を比べる",
        )
        self.assertIn("legacy:001", row["cells"]["children"]["source_refs"])

        edited = self.client.post(
            f"/plans/documents/{document_id}",
            data={
                "lock_version": "1",
                "cell__corpus_1__children": "友だちの模様にも関心を向ける",
                "cell__corpus_1__support": "子ども同士の気づきをつなぐ",
            },
            follow_redirects=False,
        )
        self.assertEqual(edited.status_code, 303, edited.text)
        after_edit = self.client.get(f"/plans/api/documents/{document_id}").json()
        self.assertEqual(
            after_edit["schedule"]["rows"][0]["cells"]["children"]["body"],
            "友だちの模様にも関心を向ける",
        )

        with closing(sqlite3.connect(self.corpus_path)) as connection:
            source_text = connection.execute(
                "select child_state_text from daily_plan_activity_blocks where daily_plan_id = ?",
                ("daily-001",),
            ).fetchone()[0]
        self.assertEqual(source_text, "粘土に興味を持ち、手にする")

    def test_edit_uses_optimistic_lock_and_creates_revision(self):
        document_id = self.create_daily_plan()

        first = self.client.post(
            f"/plans/documents/{document_id}",
            data={"lock_version": "1", "title": "雨天候補を含む日案"},
            follow_redirects=False,
        )
        self.assertEqual(first.status_code, 303)

        stale = self.client.post(
            f"/plans/documents/{document_id}",
            data={"lock_version": "1", "title": "古い画面からの更新"},
            follow_redirects=False,
        )
        self.assertEqual(stale.status_code, 409)

        with Session(self.engine) as session:
            row = session.get(PlanDocumentRow, document_id)
            head = session.exec(
                select(PlanDocumentHeadRow).where(
                    PlanDocumentHeadRow.document_id == document_id
                )
            ).one()
            revisions = session.exec(
                select(PlanRevisionRow).where(PlanRevisionRow.document_id == document_id)
            ).all()
        self.assertEqual(row.title, "雨天候補を含む日案")
        self.assertEqual(head.lock_version, 2)
        self.assertEqual(len(revisions), 2)

    def test_existing_row_without_head_is_migrated_on_first_access(self):
        with Session(self.engine) as session:
            row = PlanDocumentRow(
                document_type="daily_plan",
                status="approved",
                title="既存の日案",
                nursery_ref="ひかり保育園",
                classroom_ref="ひよこ組",
                actor_ref="staff:legacy",
                owner_name="旧担当",
                target_date="2026-08-09",
                age_class="3歳児",
                sections=[],
                schedule=None,
                confirmation_items=[],
            )
            session.add(row)
            session.commit()
            session.refresh(row)
            document_id = row.id

        self.client.cookies.update(self.staff_cookies())
        response = self.client.get(f"/plans/api/documents/{document_id}")
        self.assertEqual(response.status_code, 200)

        with Session(self.engine) as session:
            head = session.exec(
                select(PlanDocumentHeadRow).where(
                    PlanDocumentHeadRow.document_id == document_id
                )
            ).one()
            revision = session.get(PlanRevisionRow, head.current_revision_id)
        self.assertEqual(head.approved_revision_id, revision.id)
        self.assertEqual(head.review_revision_id, revision.id)
        self.assertEqual(revision.reason, "migrated")

    def test_approved_plan_execution_change_preserves_approved_revision(self):
        document_id = self.create_daily_plan()

        submit = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )
        self.assertEqual(submit.status_code, 303)
        approve = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "approved", "lock_version": "2"},
            follow_redirects=False,
        )
        self.assertEqual(approve.status_code, 303)

        detail = self.client.get(f"/plans/documents/{document_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("承認者: Test Staff", detail.text)
        self.assertIn("承認日時:", detail.text)
        self.assertIn("JST", detail.text)

        with Session(self.engine) as session:
            approval_action = session.exec(
                select(PlanDocumentAction).where(
                    PlanDocumentAction.document_id == document_id,
                    PlanDocumentAction.action == "approved",
                )
            ).one()
            self.assertEqual(approval_action.actor_name, "Test Staff")

            approver_id = UUID(approval_action.actor_ref.removeprefix("staff:"))
            session.add(
                User(
                    id=approver_id,
                    email="historical-approver@example.test",
                    display_name="履歴上の園長",
                    staff_role="admin",
                )
            )
            approval_action.actor_name = None
            session.add(approval_action)
            session.commit()

        historical_detail = self.client.get(f"/plans/documents/{document_id}")
        self.assertEqual(historical_detail.status_code, 200, historical_detail.text)
        self.assertIn("承認者: 履歴上の園長", historical_detail.text)

        with Session(self.engine) as session:
            head_before = session.exec(
                select(PlanDocumentHeadRow).where(
                    PlanDocumentHeadRow.document_id == document_id
                )
            ).one()
            approved_revision_id = head_before.approved_revision_id

        changed = self.client.post(
            f"/plans/documents/{document_id}/execution-changes",
            data={
                "affected_block_key": "",
                "reason_code": "weather",
                "reason_note": "雨天のため",
                "impact_level": "significant",
                "changed_at": "2026-08-10T09:30",
                "after_heading": "遊戯室で運動遊び",
                "after_time_label": "10:00〜10:45",
                "after_details": "滑りやすい場所を避け、間隔を確保する",
            },
            follow_redirects=False,
        )
        self.assertEqual(changed.status_code, 303, changed.text)

        with Session(self.engine) as session:
            head_after = session.exec(
                select(PlanDocumentHeadRow).where(
                    PlanDocumentHeadRow.document_id == document_id
                )
            ).one()
            change = session.exec(
                select(PlanExecutionChangeRow).where(
                    PlanExecutionChangeRow.document_id == document_id
                )
            ).one()
        self.assertEqual(head_after.approved_revision_id, approved_revision_id)
        self.assertEqual(change.base_revision_id, approved_revision_id)
        self.assertEqual(change.before_snapshot["document_type"], "daily_plan")
        self.assertEqual(change.after_snapshot["heading"], "遊戯室で運動遊び")
        self.assertEqual(change.confirmation_status, "pending")

        confirmed = self.client.post(
            f"/plans/documents/{document_id}/execution-changes/{change.id}/confirm",
            data={"confirmation_comment": "安全面を確認済み"},
            follow_redirects=False,
        )
        self.assertEqual(confirmed.status_code, 303)
        payload = self.client.get(
            f"/plans/api/daily/{document_id}/execution-changes"
        ).json()["items"]
        self.assertEqual(payload[0]["confirmation_status"], "confirmed")
        self.assertEqual(payload[0]["confirmation_comment"], "安全面を確認済み")

        corrected = self.client.post(
            f"/plans/documents/{document_id}/execution-changes/{change.id}/corrections",
            data={
                "changed_at": "2026-08-10T09:35",
                "correction_note": "終了時刻の訂正",
                "after_heading": "遊戯室で運動遊び",
                "after_time_label": "10:00〜10:30",
                "after_details": "滑りやすい場所を避け、間隔を確保する",
            },
            follow_redirects=False,
        )
        self.assertEqual(corrected.status_code, 303, corrected.text)
        corrected_payload = self.client.get(
            f"/plans/api/daily/{document_id}/execution-changes"
        ).json()["items"]
        self.assertEqual(len(corrected_payload), 2)
        self.assertEqual(corrected_payload[1]["corrects_change_id"], change.id)
        self.assertEqual(corrected_payload[1]["after_snapshot"]["time_label"], "10:00〜10:30")

        detail = self.client.get(f"/plans/documents/{document_id}")
        self.assertEqual(detail.status_code, 200)
        self.assertIn("当日の実施変更", detail.text)
        self.assertIn("遊戯室で運動遊び", detail.text)
        self.assertIn("終了時刻の訂正", detail.text)

    def test_execution_change_json_api_accepts_public_id(self):
        document_id = self.create_daily_plan()
        self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )
        self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "approved", "lock_version": "2"},
            follow_redirects=False,
        )
        public_id = self.client.get(
            f"/plans/api/documents/{document_id}"
        ).json()["public_id"]

        created = self.client.post(
            f"/plans/api/daily/{public_id}/execution-changes",
            json={
                "affected_block_key": None,
                "reason_code": "weather",
                "reason_note": "小雨が続いたため",
                "impact_level": "minor",
                "changed_at": "2026-08-10T09:40:00+09:00",
                "after_heading": "室内で表現遊び",
                "after_time_label": "10:00〜10:30",
                "after_details": "換気しながら十分な間隔を確保する",
            },
        )
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["confirmation_status"], "not_required")

        listed = self.client.get(
            f"/plans/api/daily/{public_id}/execution-changes"
        )
        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.json()["items"][0]["after_snapshot"]["heading"], "室内で表現遊び")

    def test_return_requires_reason(self):
        document_id = self.create_daily_plan()
        self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )

        missing = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "rejected", "lock_version": "2"},
            follow_redirects=False,
        )
        self.assertEqual(missing.status_code, 409)

        returned = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={
                "status": "rejected",
                "lock_version": "2",
                "comment": "雨天時の安全配慮を追記してください",
            },
            follow_redirects=False,
        )
        self.assertEqual(returned.status_code, 303)

    def test_review_request_notifies_only_active_admins_and_resolves_after_review(self):
        principal_id = uuid4()
        chief_id = uuid4()
        editor_id = uuid4()
        inactive_admin_id = uuid4()
        with Session(self.engine) as session:
            session.add_all(
                [
                    User(
                        id=principal_id,
                        email="principal@example.test",
                        display_name="園長",
                        staff_role="admin",
                        staff_sort_order=1,
                    ),
                    User(
                        id=chief_id,
                        email="chief@example.test",
                        display_name="主任",
                        staff_role="admin",
                        staff_sort_order=2,
                    ),
                    User(
                        id=editor_id,
                        email="editor@example.test",
                        display_name="担任",
                        staff_role="can_edit",
                    ),
                    User(
                        id=inactive_admin_id,
                        email="inactive@example.test",
                        display_name="退職済み管理者",
                        staff_role="admin",
                        is_active=False,
                    ),
                ]
            )
            session.commit()

        editor_cookies = self.staff_cookies(
            role="can_edit",
            staff_id=editor_id,
            name="Review%20Applicant",
        )
        document_id = self.create_daily_plan(cookies=editor_cookies)
        submitted = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 303, submitted.text)

        with Session(self.engine) as session:
            notifications = session.exec(
                select(PlanReviewNotificationRow).where(
                    PlanReviewNotificationRow.document_id == document_id
                )
            ).all()
        self.assertEqual(
            {item.recipient_user_id for item in notifications},
            {principal_id, chief_id},
        )
        self.assertTrue(all(item.requested_by_name == "Review Applicant" for item in notifications))

        principal_notification = next(
            item for item in notifications if item.recipient_user_id == principal_id
        )
        self.client.cookies.update(
            self.staff_cookies(
                role="admin",
                staff_id=principal_id,
                name="Principal",
            )
        )
        home = self.client.get("/plans/")
        self.assertEqual(home.status_code, 200, home.text)
        self.assertIn("未読 1件", home.text)
        self.assertIn("Review Applicantさんからレビュー依頼", home.text)

        opened = self.client.post(
            f"/plans/notifications/{principal_notification.id}/open",
            follow_redirects=False,
        )
        self.assertEqual(opened.status_code, 303, opened.text)
        self.assertEqual(opened.headers["location"], f"/plans/documents/{document_id}")
        with Session(self.engine) as session:
            self.assertIsNotNone(
                session.get(PlanReviewNotificationRow, principal_notification.id).read_at
            )

        approved = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "approved", "lock_version": "2"},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303, approved.text)
        with Session(self.engine) as session:
            all_notifications = session.exec(
                select(PlanReviewNotificationRow).where(
                    PlanReviewNotificationRow.document_id == document_id
                )
            ).all()
        request_notifications = [
            item
            for item in all_notifications
            if item.notification_kind == "review_request"
        ]
        outcome = next(
            item
            for item in all_notifications
            if item.notification_kind == "review_outcome"
        )
        self.assertTrue(all(item.resolved_at is not None for item in request_notifications))
        self.assertEqual(outcome.recipient_user_id, editor_id)
        self.assertEqual(outcome.decision_status, "approved")
        self.assertEqual(outcome.decided_by_name, "Principal")
        self.assertIsNone(outcome.resolved_at)
        self.assertIn("新しい帳票通知はありません", self.client.get("/plans/").text)

        self.client.cookies.update(editor_cookies)
        creator_home = self.client.get("/plans/")
        self.assertEqual(creator_home.status_code, 200)
        self.assertIn("Principalさんが承認しました", creator_home.text)
        opened_outcome = self.client.post(
            f"/plans/notifications/{outcome.id}/open",
            follow_redirects=False,
        )
        self.assertEqual(opened_outcome.status_code, 303)
        with Session(self.engine) as session:
            self.assertIsNotNone(
                session.get(PlanReviewNotificationRow, outcome.id).read_at
            )
        dismissed_outcome = self.client.post(
            f"/plans/notifications/{outcome.id}/dismiss",
            data={"redirect_to": "/plans/"},
            follow_redirects=False,
        )
        self.assertEqual(dismissed_outcome.status_code, 303)
        self.assertEqual(dismissed_outcome.headers["location"], "/plans/")
        with Session(self.engine) as session:
            dismissed = session.get(PlanReviewNotificationRow, outcome.id)
            self.assertIsNotNone(dismissed.resolved_at)
        self.assertNotIn("Principalさんが承認しました", self.client.get("/plans/").text)

    def test_review_notification_is_hidden_across_nurseries(self):
        principal_id = uuid4()
        editor_id = uuid4()
        with Session(self.engine) as session:
            session.add(
                User(
                    id=principal_id,
                    email="tenant-principal@example.test",
                    display_name="園長",
                    staff_role="admin",
                )
            )
            session.add(
                User(
                    id=editor_id,
                    email="tenant-editor@example.test",
                    display_name="担任",
                    staff_role="can_edit",
                )
            )
            session.commit()
        document_id = self.create_daily_plan(
            cookies=self.staff_cookies(
                role="can_edit",
                staff_id=editor_id,
                name="Tenant%20Editor",
            )
        )
        self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )
        with Session(self.engine) as session:
            notification = session.exec(
                select(PlanReviewNotificationRow).where(
                    PlanReviewNotificationRow.document_id == document_id
                )
            ).one()
            notification.nursery_ref = "別の保育園"
            session.add(notification)
            session.commit()
            notification_id = notification.id

        self.client.cookies.update(
            self.staff_cookies(
                role="admin",
                staff_id=principal_id,
                name="Principal",
            )
        )
        self.assertIn("新しい帳票通知はありません", self.client.get("/plans/").text)
        denied = self.client.post(
            f"/plans/notifications/{notification_id}/open",
            follow_redirects=False,
        )
        self.assertEqual(denied.status_code, 404)
        denied_dismiss = self.client.post(
            f"/plans/notifications/{notification_id}/dismiss",
            data={"redirect_to": "/"},
            follow_redirects=False,
        )
        self.assertEqual(denied_dismiss.status_code, 404)

    def test_rejected_monthly_plan_notifies_original_creator(self):
        principal_id = uuid4()
        creator_id = uuid4()
        with Session(self.engine) as session:
            session.add_all(
                [
                    User(
                        id=principal_id,
                        email="monthly-principal@example.test",
                        display_name="園長",
                        staff_role="admin",
                    ),
                    User(
                        id=creator_id,
                        email="monthly-creator@example.test",
                        display_name="ひよこ組担任",
                        staff_role="can_edit",
                    ),
                ]
            )
            session.commit()
        creator_cookies = self.staff_cookies(
            role="can_edit",
            staff_id=creator_id,
            name="Monthly%20Creator",
        )
        document_id = self.create_monthly_plan(cookies=creator_cookies)
        submitted = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 303, submitted.text)
        self.client.cookies.update(
            self.staff_cookies(
                role="admin",
                staff_id=principal_id,
                name="Principal",
            )
        )
        rejected = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={
                "status": "rejected",
                "lock_version": "2",
                "comment": "家庭連携欄を追記してください。",
            },
            follow_redirects=False,
        )
        self.assertEqual(rejected.status_code, 303, rejected.text)
        with Session(self.engine) as session:
            outcome = session.exec(
                select(PlanReviewNotificationRow).where(
                    PlanReviewNotificationRow.document_id == document_id,
                    PlanReviewNotificationRow.notification_kind == "review_outcome",
                )
            ).one()
        self.assertEqual(outcome.recipient_user_id, creator_id)
        self.assertEqual(outcome.decision_status, "rejected")
        self.assertEqual(outcome.decision_comment, "家庭連携欄を追記してください。")

        self.client.cookies.update(creator_cookies)
        creator_home = self.client.get("/plans/")
        self.assertEqual(creator_home.status_code, 200)
        self.assertIn("Principalさんが却下（差戻し）しました", creator_home.text)
        self.assertIn("家庭連携欄を追記してください。", creator_home.text)

    def test_all_staff_can_view_other_class_progress_record_but_cannot_edit_it(self):
        staff_id = uuid4()
        config = default_config()
        config["access_policy"]["progress_record_view_scope"] = "all_staff"
        with Session(self.engine) as session:
            classroom = session.exec(
                select(Classroom).where(Classroom.name == "うさぎ組")
            ).one()
            child = Child(
                last_name="佐藤",
                first_name="空",
                last_name_kana="サトウ",
                first_name_kana="ソラ",
                birth_date=date(2023, 4, 2),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            session.add(child)
            session.flush()
            session.add(
                ChildRecordSettingVersion(
                    version_no=1,
                    status="active",
                    preset_key="standard",
                    effective_from=date(2000, 1, 1),
                    config=config,
                )
            )
            document = PlanDocumentRow(
                document_type=DocumentType.CHILD_PROGRESS_RECORD.value,
                status="draft",
                title="佐藤 空 児童票",
                nursery_ref=DEFAULT_NURSERY_REF,
                classroom_ref=classroom.name,
                owner_name="うさぎ組担任",
                school_year=2026,
                period_start="2026-07-01",
                period_end="2026-09-30",
                record_cycle_key="fy2026:2026-07-01:2026-09-30",
                child_id=child.id,
                child_ref=str(child.id),
                child_name=child.full_name,
                sections=[
                    {
                        "section_key": "progress_children_overview",
                        "title": "対象期間の子どもの姿",
                        "body": "友達との遊びが広がった。",
                        "evidence_tags": ["入力"],
                    }
                ],
            )
            session.add(document)
            session.commit()
            session.refresh(document)
            document_id = int(document.id or 0)

        self.client.cookies.update(
            self.staff_cookies(
                role="can_edit",
                staff_id=staff_id,
                name="Other%20Class%20Staff",
            )
        )

        detail = self.client.get(f"/plans/documents/{document_id}")
        self.assertEqual(detail.status_code, 200, detail.text)
        self.assertIn("友達との遊びが広がった。", detail.text)
        self.assertNotIn(">入力</b>", detail.text)
        self.assertNotIn(
            f'href="/plans/documents/{document_id}/edit"',
            detail.text,
        )
        edit = self.client.get(f"/plans/documents/{document_id}/edit")
        self.assertEqual(edit.status_code, 403)
        status_change = self.client.post(
            f"/plans/documents/{document_id}/status",
            data={"status": "in_review", "lock_version": "1"},
            follow_redirects=False,
        )
        self.assertEqual(status_change.status_code, 403)


if __name__ == "__main__":
    unittest.main()
