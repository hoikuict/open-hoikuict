import html
from concurrent.futures import ThreadPoolExecutor, TimeoutError
import re
import sqlite3
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlmodel import Session, create_engine, select

import database
from auth import Role, StaffUser
from csrf import CSRF_COOKIE_NAME
from data_transfer_service import (
    build_csv_content,
    commit_import,
    export_rows,
    preview_import,
    template_rows,
)
from family_archive import archive_blockers
from family_support import bootstrap_family_data
from models import (
    Child,
    ChildStatus,
    Family,
    FamilyArchiveLog,
    FamilyBillingProfile,
    ParentAccount,
    ParentAccountStatus,
    ParentEnrollment,
    ParentRegistrationRequest,
    Survey,
    SurveyAnswer,
    User,
)
import routers.data_transfers as transfers
import test_family_deletion as fixtures
from time_utils import utc_now


class FamilyArchiveTests(unittest.TestCase):
    def test_child_registration_and_archive_are_serialized(self):
        review = self.token()
        inserting, release, archive_attempted = (
            threading.Event(),
            threading.Event(),
            threading.Event(),
        )

        def pause_insert(connection, cursor, statement, parameters, context, many):
            if statement.startswith("INSERT INTO children"):
                inserting.set()
                if not release.wait(5):
                    raise AssertionError(
                        "Concurrent archive did not reach the writer lock"
                    )
            elif statement == "BEGIN IMMEDIATE" and inserting.is_set():
                archive_attempted.set()

        def register_child():
            with Session(self.engine) as session:
                session.add(self.child(status=ChildStatus.enrolled))
                session.commit()

        event.listen(self.engine, "before_cursor_execute", pause_insert)
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                child_write = pool.submit(register_child)
                self.assertTrue(inserting.wait(5))
                archive_write = pool.submit(self.submit, review)
                try:
                    self.assertTrue(archive_attempted.wait(5))
                    with self.assertRaises(TimeoutError):
                        archive_write.result(timeout=0.15)
                finally:
                    release.set()
                child_write.result(timeout=5)
                self.assertEqual(archive_write.result(timeout=5).status_code, 409)
        finally:
            release.set()
            event.remove(self.engine, "before_cursor_execute", pause_insert)
        with Session(self.engine) as session:
            self.assertFalse(session.get(Family, 101).is_archived)
            self.assertEqual(session.exec(select(Child)).one().family_id, 101)

    def setUp(self):
        fixtures.FamilyDeletionTests.setUp(self)
        self.app.include_router(transfers.router)
        self.preview_env = patch.object(
            transfers, "PREVIEW_DIR", Path(self.tmp.name) / "previews"
        )
        self.preview_env.start()

    def tearDown(self):
        self.preview_env.stop()
        fixtures.FamilyDeletionTests.tearDown(self)

    def token(self, action="archive", family_id=101):
        response = self.client.get(f"/families/{family_id}/{action}")
        self.assertEqual(response.status_code, 200, response.text)
        match = re.search(r'name="review_token" value="([^"]+)"', response.text)
        self.assertIsNotNone(match, response.text)
        return html.unescape(match.group(1))

    def submit(self, token, action="archive", family_id=101, **fields):
        values = {
            "review_token": token,
            "reason": "整理中・判断を保留",
            "note": "確認して戻せる",
            "csrf_token": self.client.cookies.get(CSRF_COOKIE_NAME),
        }
        values.update(fields)
        return self.client.post(
            f"/families/{family_id}/{action}", data=values, follow_redirects=False
        )

    def archive(self, family_id=101):
        response = self.submit(self.token(family_id=family_id), family_id=family_id)
        self.assertEqual(response.status_code, 303, response.text)

    def child(self, status=ChildStatus.graduated):
        return fixtures.FamilyDeletionTests.child(status=status)

    def content(self, *rows):
        headers = template_rows("families")[0]
        return build_csv_content(
            [headers, *[[row.get(h, "") for h in headers] for row in rows]]
        )

    def test_records_history_billing_and_restore_are_preserved(self):
        with Session(self.engine) as s:
            survey = Survey(title="架空調査")
            s.add(survey)
            s.flush()
            s.add_all(
                [
                    SurveyAnswer(family_id=101, survey_id=survey.id),
                    self.child(),
                    ParentAccount(
                        family_id=101,
                        display_name="保存保護者",
                        email="old@example.invalid",
                        status=ParentAccountStatus.inactive,
                    ),
                    FamilyBillingProfile(family_id=101, customer_number="test-archive"),
                ]
            )
            s.commit()
            before = s.get(Family, 101).model_dump(
                exclude={"archived_at", "updated_at"}
            )
        self.archive()
        self.assertNotIn("F-00101", self.client.get("/families/").text)
        page = self.client.get("/families/?scope=archived&q=F-00101")
        self.assertIn("元に戻す", page.text)
        self.assertIn("確認して戻せる", page.text)
        records = self.client.get("/families/101/records")
        self.assertIn("アンケート回答（回答番号", records.text)
        self.assertIn("アーカイブ・復帰の履歴", records.text)
        with Session(self.engine) as s:
            bootstrap_family_data(s)
            s.commit()
            self.assertEqual(
                s.get(Family, 101).model_dump(exclude={"archived_at", "updated_at"}),
                before,
            )
            self.assertEqual(len(s.exec(select(SurveyAnswer)).all()), 1)
            self.assertEqual(len(s.exec(select(FamilyBillingProfile)).all()), 1)
        self.assertEqual(self.submit(self.token("restore"), "restore").status_code, 303)
        with Session(self.engine) as s:
            self.assertFalse(s.get(Family, 101).is_archived)
            self.assertEqual(s.exec(select(Child)).one().status, ChildStatus.graduated)
            self.assertEqual(
                s.exec(select(ParentAccount)).one().status, ParentAccountStatus.inactive
            )
            self.assertEqual(
                [
                    x.action
                    for x in s.exec(
                        select(FamilyArchiveLog).order_by(FamilyArchiveLog.id)
                    ).all()
                ],
                ["archive", "restore"],
            )

    def test_active_children_and_race_after_review_block_archive(self):
        token = self.token()
        with Session(self.engine) as s:
            s.add(self.child(ChildStatus.enrolled))
            s.commit()
        result = self.submit(token)
        self.assertEqual(result.status_code, 409)
        self.assertIn("在園中の園児", result.text)
        self.assertNotIn('name="review_token"', result.text)
        with Session(self.engine) as s:
            self.assertFalse(s.get(Family, 101).is_archived)

    def test_active_parent_blocker(self):
        with Session(self.engine) as s:
            s.add(
                ParentAccount(
                    family_id=101,
                    display_name="架空保護者",
                    email="live@example.invalid",
                )
            )
            s.commit()
        page = self.client.get("/families/101/archive")
        self.assertIn("有効な保護者アカウント", page.text)
        self.assertNotIn('name="review_token"', page.text)

    def test_pending_intake_blocks_but_completed_record_does_not(self):
        with Session(self.engine) as s:
            parent = ParentAccount(display_name="初回", email="intake@example.invalid")
            s.add(parent)
            s.flush()
            registration = ParentRegistrationRequest(
                parent_account_id=parent.id, email_normalized_snapshot=parent.email
            )
            s.add(registration)
            s.flush()
            entry = ParentEnrollment(
                registration_request_id=registration.id,
                child_name="架空園児",
                source_snapshot={"family_id": 101},
            )
            s.add(entry)
            s.commit()
            self.assertTrue(archive_blockers(s, s.get(Family, 101)))
            entry.applied_at = utc_now()
            s.add(entry)
            s.commit()
            self.assertFalse(archive_blockers(s, s.get(Family, 101)))
        self.archive()
        self.assertIn("反映済み", self.client.get("/families/101/records").text)

    def test_csrf_owner_action_permission_and_replay(self):
        token = self.token()
        self.assertEqual(self.submit(token, csrf_token="bad").status_code, 403)
        self.assertEqual(self.submit(token, action="restore").status_code, 409)
        self.assertEqual(self.submit(token, family_id=102).status_code, 409)
        self.assertEqual(self.submit(token + "x").status_code, 409)
        self.current_user = StaffUser(role=Role.VIEW_ONLY, user_id=self.user_id)
        self.assertEqual(self.submit(token).status_code, 403)
        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            user_id=self.user_id,
            name="架空の台帳担当",
            can_manage_child_records=True,
        )
        self.assertEqual(self.submit(token).status_code, 303)
        self.assertEqual(self.submit(token).status_code, 409)

    def test_live_permission_revocation_and_expiration(self):
        token = self.token()
        with patch("family_deletion.time", return_value=10**11):
            self.assertEqual(self.submit(token).status_code, 409)
        with Session(self.engine) as s:
            user = s.get(User, self.user_id)
            user.can_manage_child_records = False
            s.add(user)
            s.commit()
        self.assertEqual(self.submit(token).status_code, 403)

    def test_failed_save_keeps_note_without_state_or_history(self):
        token = self.token()
        with patch.object(
            Session,
            "commit",
            side_effect=OperationalError("COMMIT", {}, Exception("synthetic")),
        ):
            response = self.submit(token, note="保持するメモ")
        self.assertEqual(response.status_code, 503)
        self.assertIn("保持するメモ", response.text)
        with Session(self.engine) as s:
            self.assertFalse(s.get(Family, 101).is_archived)
            self.assertEqual(s.exec(select(FamilyArchiveLog)).all(), [])

    def test_archived_family_write_and_association_guards(self):
        with Session(self.engine) as s:
            s.add(self.child())
            s.commit()
        self.archive()
        self.assertEqual(
            self.client.get("/families/101/edit", follow_redirects=False).headers[
                "location"
            ],
            "/families/101/records",
        )
        self.assertEqual(
            self.client.post(
                "/families/101/edit",
                data={
                    "family_name": "変更",
                    "csrf_token": self.client.cookies.get(CSRF_COOKIE_NAME),
                },
            ).status_code,
            409,
        )
        for kind in ("child", "family", "move"):
            with self.subTest(kind=kind), Session(self.engine) as s:
                if kind == "child":
                    s.add(self.child())
                elif kind == "family":
                    s.get(Family, 101).home_address = "変更"
                else:
                    s.exec(select(Child)).one().family_id = 102
                with self.assertRaises(HTTPException):
                    s.commit()
                s.rollback()

    def test_csv_archive_matching_export_scopes_and_exclusion(self):
        self.archive()
        content = self.content(
            {"ID": "101", "家庭名": "あおぞら家", "住所": "変更"},
            {"ID": "102", "住所": "架空更新住所"},
        )
        with Session(self.engine) as s:
            result = preview_import(s, "families", "sample.csv", content)
            self.assertEqual(result.errors[0].family_id, 101)
            self.assertEqual(result.update_count, 1)
            self.assertEqual(len(export_rows(s, "families")), 2)
            self.assertEqual(len(export_rows(s, "families", archive_scope="all")), 3)
            self.assertEqual(
                len(export_rows(s, "families", archive_scope="archived")), 2
            )
            self.assertEqual(
                len(export_rows(s, "families", archive_scope="all")[0]), 24
            )
            unknown = self.content({"家庭名": "あおぞら家", "電話番号": "別の電話"})
            self.assertTrue(preview_import(s, "families", "sample.csv", unknown).errors)
            result = preview_import(
                s, "families", "sample.csv", content, excluded_rows=[2]
            )
            self.assertFalse(result.errors)
            self.assertEqual(result.total_rows, 1)
            applied = commit_import(
                s,
                "families",
                "sample.csv",
                content,
                actor_name="架空",
                expected_revision=result.revision,
                excluded_rows=[2],
            )
            self.assertFalse(applied.errors)
            self.assertEqual(s.get(Family, 102).home_address, "架空更新住所")
            self.assertNotEqual(s.get(Family, 101).home_address, "変更")

    def test_archive_invalidates_old_preview_and_restore_requires_revalidation(self):
        content = self.content({"ID": "102", "住所": "架空更新住所"})
        with Session(self.engine) as s:
            result = preview_import(s, "families", "sample.csv", content)
        self.archive()
        with Session(self.engine) as s:
            self.assertTrue(
                commit_import(
                    s,
                    "families",
                    "sample.csv",
                    content,
                    actor_name="架空",
                    expected_revision=result.revision,
                ).errors
            )

    def test_preview_resume_exclusions_and_token_owner(self):
        self.archive()
        content = self.content(
            {"ID": "101", "住所": "変更"}, {"ID": "102", "住所": "架空更新住所"}
        )
        headers = {"X-CSRF-Token": self.client.cookies.get(CSRF_COOKIE_NAME)}
        response = self.client.post(
            "/data-transfers/import/families/preview",
            files={"file": ("sample.csv", content, "text/csv")},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        token = re.search('name="preview_token" value="([^"]+)"', response.text).group(
            1
        )
        resumed = self.client.get("/data-transfers/", params={"preview": token})
        self.assertIn("対象行を再検証", resumed.text)
        self.assertNotIn(
            "data-import-commit", resumed.text.split("{%")[0].split("<script>")[0]
        )
        response = self.client.post(
            "/data-transfers/import/families/repreview",
            data={"preview_token": token, "excluded_rows": "2"},
            headers=headers,
        )
        self.assertEqual(response.status_code, 200, response.text)
        newtoken = re.search(
            'name="preview_token" value="([^"]+)"', response.text
        ).group(1)
        self.assertNotEqual(token, newtoken)
        response = self.client.post(
            "/data-transfers/import/families/commit",
            data={"preview_token": newtoken},
            headers=headers,
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303, response.text)
        with Session(self.engine) as s:
            self.assertEqual(s.get(Family, 102).home_address, "架空更新住所")
            self.assertTrue(s.get(Family, 101).is_archived)
        self.assertEqual(
            self.client.post(
                "/data-transfers/import/families/commit",
                data={"preview_token": newtoken},
                headers=headers,
            ).status_code,
            400,
        )

    def test_migration_and_sqlite_backup_keep_archive_state(self):
        old_engine = create_engine(
            "sqlite:///" + (Path(self.tmp.name) / "old.db").as_posix()
        )
        with old_engine.begin() as conn:
            conn.exec_driver_sql(
                "CREATE TABLE families (id INTEGER PRIMARY KEY, family_name TEXT)"
            )
            conn.exec_driver_sql("INSERT INTO families VALUES (1, '架空')")
        with patch.object(database, "engine", old_engine):
            database._migrate_family_archive()
            database._migrate_family_archive()
        with old_engine.connect() as conn:
            self.assertEqual(
                conn.execute(text("SELECT archived_at FROM families")).scalar_one(),
                None,
            )
        old_engine.dispose()
        self.archive()
        source = sqlite3.connect(str(Path(self.tmp.name) / "test.sqlite"))
        target = sqlite3.connect(str(Path(self.tmp.name) / "backup.sqlite"))
        try:
            source.backup(target)
            self.assertIsNotNone(
                target.execute(
                    "SELECT archived_at FROM families WHERE id=101"
                ).fetchone()[0]
            )
            self.assertEqual(
                target.execute("SELECT COUNT(*) FROM family_archive_logs").fetchone()[
                    0
                ],
                1,
            )
            self.assertEqual(target.execute("PRAGMA foreign_key_check").fetchall(), [])
        finally:
            source.close()
            target.close()
