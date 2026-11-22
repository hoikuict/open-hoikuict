"""Daily plan approval corrections through the same routes used by staff."""
import unittest
from uuid import uuid4

from sqlmodel import Session, select

import test_plan_docs as fixtures
from models import User
from plan_docs.db_models import (
    PlanDocumentAction,
    PlanDocumentRow,
    PlanReviewNotificationRow,
    PlanRevisionRow,
)


class DailyPlanReapprovalTests(unittest.TestCase):
    tearDown = fixtures.PlanDocsIntegrationTests.tearDown
    staff_cookies = fixtures.PlanDocsIntegrationTests.staff_cookies
    create_daily_plan = fixtures.PlanDocsIntegrationTests.create_daily_plan
    _create_example_corpus = fixtures.PlanDocsIntegrationTests._create_example_corpus

    def setUp(self):
        fixtures.PlanDocsIntegrationTests.setUp(self)
        self.author_id, self.chief_id = uuid4(), uuid4()
        self.author = self.staff_cookies(role="can_edit", staff_id=self.author_id, name="Author")
        self.chief = self.staff_cookies(role="admin", staff_id=self.chief_id, name="Chief")
        with Session(self.engine) as db:
            db.add_all([
                User(id=self.author_id, email="author@example.test", display_name="Author", staff_role="can_edit"),
                User(id=self.chief_id, email="chief@example.test", display_name="Chief", staff_role="admin"),
            ])
            db.commit()
        self.document_id = self.create_daily_plan(cookies=self.author)
        self.url = f"/plans/documents/{self.document_id}"

    def post(self, cookies, suffix, **fields):
        self.client.cookies.update(cookies)
        return self.client.post(self.url + suffix, data=fields, follow_redirects=False)

    def state(self):
        response = self.client.get(f"/plans/api/documents/{self.document_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def transition(self, who, status, lock, comment=""):
        response = self.post(who, "/status", status=status, lock_version=lock, comment=comment)
        self.assertEqual(response.status_code, 303, response.text)

    def approve_first(self):
        self.transition(self.author, "in_review", 1)
        self.transition(self.chief, "approved", 2, "初回の承認")
        return self.state()["approved_revision_id"]

    def reopen(self, lock, reason="活動場所の修正"):
        response = self.post(self.chief, "/reopen", lock_version=lock, reason=reason)
        self.assertEqual(response.status_code, 303, response.text)

    def revision(self, revision_id):
        with Session(self.engine) as db:
            return db.get(PlanRevisionRow, revision_id).snapshot

    def notifications(self, who):
        with Session(self.engine) as db:
            return db.exec(select(PlanReviewNotificationRow).where(
                PlanReviewNotificationRow.document_id == self.document_id,
                PlanReviewNotificationRow.recipient_user_id == who,
                PlanReviewNotificationRow.resolved_at.is_(None),
            ).order_by(PlanReviewNotificationRow.id)).all()

    def open_notification(self, who, notification_id):
        self.client.cookies.update(who)
        opened = self.client.post(f"/plans/notifications/{notification_id}/open", follow_redirects=False)
        self.assertEqual(opened.status_code, 303)
        self.assertEqual(opened.headers["location"], self.url)
        return self.client.get(self.url).text

    def test_from_request_through_reapproval_and_second_reopen(self):
        self.assertIn("レビュー依頼", self.client.get(self.url).text)
        self.transition(self.author, "in_review", 1)
        first_request, = self.notifications(self.chief_id)
        self.open_notification(self.chief, first_request.id)
        self.transition(self.chief, "approved", 2, "最初の計画を確認")
        old_id = self.state()["approved_revision_id"]
        old_snapshot = self.revision(old_id)
        self.assertFalse(self.notifications(self.chief_id))

        self.reopen(3)
        repair_notice = self.notifications(self.author_id)[-1]
        self.assertEqual(repair_notice.decision_comment, "活動場所の修正")
        detail = self.open_notification(self.author, repair_notice.id)
        self.assertIn("修正中・再承認が必要", detail)
        self.assertIn("修正中・再承認が必要", self.client.get("/plans/documents/").text)
        saved = self.post(self.author, "", lock_version=4, body_daily_content="室内の水遊びに変更")
        self.assertEqual(saved.status_code, 303, saved.text)
        self.assertFalse(self.notifications(self.chief_id))
        self.transition(self.author, "in_review", 5)
        second_request, = self.notifications(self.chief_id)
        detail = self.open_notification(self.chief, second_request.id)
        self.assertIn("再承認待ち", detail)
        self.assertIn("園庭で水遊びをする", detail)
        self.assertIn("室内の水遊びに変更", detail)
        self.transition(self.chief, "approved", 6, "変更を確認しました")
        current_id = self.state()["approved_revision_id"]
        self.assertNotEqual(current_id, old_id)
        self.assertEqual(self.revision(old_id), old_snapshot)
        self.assertIn("室内の水遊びに変更", [s["body"] for s in self.revision(current_id)["sections"]])
        self.assertFalse(self.notifications(self.chief_id))
        result = self.notifications(self.author_id)[-1]
        self.assertEqual(result.decision_status, "reapproved")
        detail = self.open_notification(self.author, result.id)
        for text in ("最初の計画を確認", "活動場所の修正", "変更を確認しました"):
            self.assertIn(text, detail)

        self.reopen(7, "もう一度担当者を確認")
        self.transition(self.author, "in_review", 8)
        self.transition(self.chief, "approved", 9)
        self.assertEqual(self.revision(old_id), old_snapshot)
        self.assertEqual(self.state()["lock_version"], 10)

    def test_browser_form_posts_and_calendar_follow_same_plan(self):
        steps = [
            (self.author, "/status", {"status": "in_review"}, "in_review", None),
            (self.chief, "/status", {"status": "approved"}, "approved", None),
            (self.chief, "/reopen", {"reason": "活動場所を修正してください"}, "draft", "修正中・再承認が必要"),
            (self.author, "", {"title": "修正した日案"}, "draft", "修正中・再承認が必要"),
            (self.author, "/status", {"status": "in_review"}, "in_review", "再承認待ち"),
            (self.chief, "/status", {"status": "approved"}, "approved", "承認済み（再承認）"),
        ]
        for version, (who, suffix, fields, status, label) in enumerate(steps, start=1):
            with self.subTest(version=version):
                self.client.cookies.update(who)
                response = self.client.post(
                    self.url + suffix, headers={"Accept": "application/json"},
                    data={"lock_version": version, **fields}, follow_redirects=False,
                )
                self.assertEqual(response.status_code, 200, response.text)
                self.assertEqual(response.json(), {
                    "document_id": self.document_id, "status": status, "lock_version": version + 1,
                })
                if label:
                    self.assertIn(label, self.client.get("/plans/daily-plans/?year=2026&month=8").text)
                    self.assertIn(label, self.client.get("/plans/documents/").text)

    def test_permissions_stale_forms_and_validation_leave_state_intact(self):
        self.approve_first()
        before = self.state()
        for reason in ("", "  ", "あ" * 501):
            with self.subTest(reason=reason[:4]):
                response = self.post(self.chief, "/reopen", reason=reason, lock_version=3)
                self.assertIn(response.status_code, (409, 422))
                self.assertEqual(self.state(), before)
        response = self.post(self.author, "/reopen", reason="直してください", lock_version=3)
        self.assertEqual(response.status_code, 403)
        self.reopen(3, "あ" * 500)
        count = len(self.notifications(self.author_id))
        stale = self.post(self.chief, "/reopen", reason="二重送信", lock_version=3)
        self.assertEqual(stale.status_code, 409)
        self.assertEqual(len(self.notifications(self.author_id)), count)
        other_staff = self.staff_cookies(role="can_edit")
        for other in (other_staff, self.chief):
            self.client.cookies.update(other)
            self.assertEqual(self.client.get(self.url + "/edit").status_code, 403)
            self.assertEqual(self.post(other, "", lock_version=4, title="上書き不可").status_code, 403)
            self.assertEqual(self.post(other, "/status", lock_version=4, status="in_review").status_code, 403)
        self.transition(self.author, "in_review", 4)
        self.assertEqual(self.post(self.author, "", lock_version=4, title="古い入力").status_code, 409)
        self.assertEqual(self.post(other_staff, "/status", status="draft", lock_version=5).status_code, 403)
        self.assertEqual(self.post(self.author, "/status", status="approved", lock_version=5).status_code, 403)
        self.transition(self.chief, "approved", 5)
        replay = self.post(self.chief, "/status", status="approved", lock_version=5)
        self.assertEqual(replay.status_code, 409)
        self.assertEqual(self.state()["lock_version"], 6)

    def test_reopen_is_limited_to_approved_daily_plans_at_this_nursery(self):
        before = self.state()
        refused = self.post(self.chief, "/reopen", lock_version=1, reason="未承認")
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.state(), before)
        self.approve_first()
        with Session(self.engine) as db:
            row = db.get(PlanDocumentRow, self.document_id)
            row.nursery_ref = "別の園"
            db.commit()
        cross_nursery = self.post(self.chief, "/reopen", lock_version=3, reason="修正理由")
        self.assertEqual(cross_nursery.status_code, 404)
        with Session(self.engine) as db:
            row = db.get(PlanDocumentRow, self.document_id)
            self.assertEqual(row.status, "approved")
            row.nursery_ref = before["nursery_ref"]
            row.document_type = "weekly_plan"
            db.commit()
        other_document = self.post(self.chief, "/reopen", lock_version=3, reason="対象外")
        self.assertEqual(other_document.status_code, 404)
        self.assertEqual(self.state()["lock_version"], 3)

    def test_withdrawal_and_return_preserve_repair_reason_and_last_approval(self):
        first_id = self.approve_first()
        first_snapshot = self.revision(first_id)
        self.reopen(3)
        self.transition(self.author, "in_review", 4)
        self.transition(self.author, "draft", 5)
        withdrawn, = self.notifications(self.chief_id)
        self.assertEqual(withdrawn.decision_status, "reapproval_withdrawn")
        self.assertIn("修正中・再承認が必要", self.client.get(self.url).text)
        self.transition(self.author, "in_review", 6)
        invalid = self.post(self.chief, "/status", status="rejected", lock_version=7, comment=" ")
        self.assertIn(invalid.status_code, (409, 422))
        self.transition(self.chief, "rejected", 7, "時刻も直してください")
        self.assertEqual([item.id for item in self.notifications(self.chief_id)], [withdrawn.id])
        self.client.cookies.update(self.author)
        detail = self.client.get(self.url).text
        for reason in ("活動場所の修正", "時刻も直してください"):
            self.assertIn(reason, detail)
        self.assertEqual(self.client.get(self.url + "/edit").status_code, 200)
        self.transition(self.author, "in_review", 8)
        self.transition(self.chief, "approved", 9)
        self.assertEqual(self.revision(first_id), first_snapshot)

    def test_preexisting_approved_daily_without_head_or_actions_keeps_its_body(self):
        with Session(self.engine) as db:
            original = db.get(PlanDocumentRow, self.document_id)
            # A separate row predating revision heads and approval action records.
            data = original.model_dump(exclude={"id"})
            data.update(target_date="2026-08-11", status="approved", title="以前の承認日案")
            row = PlanDocumentRow(**data)
            db.add(row)
            db.commit()
            db.refresh(row)
            self.document_id = row.id
        self.url = f"/plans/documents/{self.document_id}"
        self.reopen(1)
        legacy_revision = self.state()["approved_revision_id"]
        self.assertEqual(self.revision(legacy_revision)["title"], "以前の承認日案")
        self.transition(self.author, "in_review", 2)
        self.transition(self.chief, "approved", 3)
        with Session(self.engine) as db:
            actions = db.exec(select(PlanDocumentAction).where(
                PlanDocumentAction.document_id == self.document_id,
                PlanDocumentAction.action == "approved",
            )).all()
            self.assertEqual(len(actions), 1)
        self.assertNotEqual(self.state()["approved_revision_id"], legacy_revision)

    def test_old_approval_action_is_linked_to_the_reviewed_version_on_reopening(self):
        first_id = self.approve_first()
        with Session(self.engine) as db:
            approval = db.exec(select(PlanDocumentAction).where(
                PlanDocumentAction.document_id == self.document_id,
                PlanDocumentAction.action == "approved",
            )).one()
            approval_id = approval.id
            approval.revision_id = None
            approval.actor_name = None
            db.commit()
        self.reopen(3)
        with Session(self.engine) as db:
            previous = db.get(PlanDocumentAction, approval_id)
            self.assertEqual(previous.revision_id, first_id)
            self.assertEqual(previous.actor_ref, f"staff:{self.chief_id}")
        history = self.client.get(self.url).context["daily_revision"]["history"]
        original_approval, = [event for event in history if event["label"] == "承認"]
        self.assertEqual(original_approval["actor"], "Chief")
        self.assertIn("園庭で水遊びをする", [field["value"] for field in original_approval["fields"]])

    def test_missing_recipients_roll_back_lock_status_and_history(self):
        self.approve_first()
        approved = self.state()
        with Session(self.engine) as db:
            db.get(User, self.author_id).is_active = False
            db.commit()
        refused = self.post(self.chief, "/reopen", reason="内容を確認", lock_version=3)
        self.assertEqual(refused.status_code, 409)
        self.assertEqual(self.state(), approved)
        with Session(self.engine) as db:
            self.assertFalse(db.exec(select(PlanDocumentAction).where(
                PlanDocumentAction.document_id == self.document_id,
                PlanDocumentAction.action == "reopened",
            )).first())
            db.get(User, self.author_id).is_active = True
            db.commit()
        self.reopen(3)
        before_request = self.state()
        with Session(self.engine) as db:
            db.get(User, self.chief_id).is_active = False
            db.commit()
        self.client.cookies.update(self.author)
        response = self.client.post(self.url + "/status", data={"status": "in_review", "lock_version": 4},
                                    headers={"Accept": "application/json"})
        self.assertIn(response.status_code, (409, 422))
        self.assertEqual(self.state(), before_request)
        self.assertFalse(self.notifications(self.chief_id))
