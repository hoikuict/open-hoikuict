import unittest
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role
from models import (
    Child,
    ChildStatus,
    Classroom,
    Notice,
    NoticeAttachment,
    NoticePriority,
    NoticeStatus,
    NoticeTarget,
    NoticeTargetType,
    NoticeWorkflowAction,
)
import notice_content
import routers.notices as notices_module
from testing_helpers import authenticate_mock_staff
from time_utils import utc_now


class NoticeRouterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(notices_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[notices_module.get_session] = override_get_session
        self.client = TestClient(self.app)
        authenticate_mock_staff(self.client)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_list_tolerates_invalid_target_value(self):
        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            child = Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2021, 5, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=None,
            )
            notice = Notice(title="確認", body="本文")
            session.add(classroom)
            session.add(child)
            session.add(notice)
            session.flush()
            session.add(
                NoticeTarget(
                    notice_id=notice.id,
                    target_type=NoticeTargetType.classroom,
                    target_value="not-a-number",
                )
            )
            session.commit()

        response = self.client.get("/notices/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("クラス指定", response.text)

    def test_publish_end_must_not_be_before_start(self):
        response = self.client.post(
            "/notices/",
            data={
                "title": "期間エラー",
                "body": "本文",
                "publish_start_at": "2026-04-02T10:00",
                "publish_end_at": "2026-04-01T10:00",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 400)

    def test_publish_window_is_entered_in_jst_and_saved_as_utc(self):
        response = self.client.post(
            "/notices/",
            data={
                "title": "JST確認",
                "body": "本文",
                "publish_start_at": "2026-07-26T08:22",
                "publish_end_at": "2026-07-26T09:22",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            notice = session.exec(select(Notice).where(Notice.title == "JST確認")).one()
            self.assertEqual(notice.publish_start_at, datetime(2026, 7, 25, 23, 22))
            self.assertEqual(notice.publish_end_at, datetime(2026, 7, 26, 0, 22))
            notice_id = notice.id

        edit_response = self.client.get(f"/notices/{notice_id}/edit")
        self.assertEqual(edit_response.status_code, 200)
        self.assertIn('value="2026-07-26T08:22"', edit_response.text)
        self.assertIn("公開開始（JST）", edit_response.text)

    def test_list_can_search_filter_and_sort_notices(self):
        now = utc_now()
        with Session(self.engine) as session:
            important_published = Notice(
                title="避難訓練のお知らせ",
                body="防災頭巾を持参してください。",
                status=NoticeStatus.published,
                priority=NoticePriority.high,
                created_by="園長",
                updated_at=now - timedelta(days=2),
            )
            normal_draft = Notice(
                title="来月の予定",
                body="行事予定を確認中です。",
                status=NoticeStatus.draft,
                priority=NoticePriority.normal,
                created_by="主任",
                updated_at=now,
            )
            important_draft = Notice(
                title="緊急連絡網",
                body="連絡先を再確認します。",
                status=NoticeStatus.draft,
                priority=NoticePriority.high,
                created_by="事務",
                updated_at=now - timedelta(days=1),
            )
            session.add(important_published)
            session.add(normal_draft)
            session.add(important_draft)
            session.commit()
            session.refresh(important_published)

        body_search = self.client.get("/notices/?q=防災頭巾")
        author_search = self.client.get("/notices/?q=主任")
        id_search = self.client.get(f"/notices/?q={important_published.id}")
        published_only = self.client.get("/notices/?status=published")
        high_only = self.client.get("/notices/?priority=high")
        priority_sorted = self.client.get("/notices/?sort=priority_desc")
        status_sorted = self.client.get("/notices/?sort=status_published")

        self.assertIn("避難訓練のお知らせ", body_search.text)
        self.assertNotIn("来月の予定", body_search.text)
        self.assertIn("来月の予定", author_search.text)
        self.assertIn("避難訓練のお知らせ", id_search.text)
        self.assertIn("避難訓練のお知らせ", published_only.text)
        self.assertNotIn("緊急連絡網", published_only.text)
        self.assertIn("避難訓練のお知らせ", high_only.text)
        self.assertIn("緊急連絡網", high_only.text)
        self.assertNotIn("来月の予定", high_only.text)
        self.assertLess(priority_sorted.text.index("緊急連絡網"), priority_sorted.text.index("来月の予定"))
        self.assertLess(status_sorted.text.index("避難訓練のお知らせ"), status_sorted.text.index("来月の予定"))

    def test_rich_text_and_image_pdf_attachments_are_sanitized_and_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            upload_root = Path(directory) / "notice-attachments"
            with patch.object(notice_content, "NOTICE_UPLOAD_ROOT", upload_root):
                response = self.client.post(
                    "/notices/",
                    data={
                        "title": "装飾付きのお知らせ",
                        "body": "重要なお知らせ",
                        "body_html": (
                            '<h2>重要なお知らせ</h2><b><font color="#ff0000" size="5">確認</font></b>'
                            '<span style="background-color: #fff3bf">してください</span>'
                            '<a href="javascript:alert(1)" onclick="alert(1)">危険なリンク</a>'
                            '<script>alert(1)</script>'
                        ),
                        "new_image_size": "large",
                    },
                    files=[
                        ("attachments", ("photo.png", b"\x89PNG\r\n\x1a\nimage-data", "image/png")),
                        ("attachments", ("guide.pdf", b"%PDF-1.7\nnotice", "application/pdf")),
                    ],
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303, response.text)

                with Session(self.engine) as session:
                    notice = session.exec(
                        select(Notice).where(Notice.title == "装飾付きのお知らせ")
                    ).one()
                    attachments = session.exec(
                        select(NoticeAttachment)
                        .where(NoticeAttachment.notice_id == notice.id)
                        .order_by(NoticeAttachment.display_order)
                    ).all()
                    notice_id = notice.id
                    image_id = attachments[0].id
                    pdf_id = attachments[1].id
                    self.assertIn('<font color="#ff0000" size="5">', notice.body_html)
                    self.assertIn("<b>", notice.body_html)
                    self.assertIn("background-color: #fff3bf", notice.body_html)
                    self.assertNotIn("javascript:", notice.body_html)
                    self.assertNotIn("onclick", notice.body_html)
                    self.assertNotIn("alert(1)", notice.body_html)
                    self.assertEqual(notice.body, "重要なお知らせ\n確認してください危険なリンク")
                    self.assertEqual(len(attachments), 2)
                    self.assertEqual(attachments[0].display_size, "large")
                    self.assertTrue(attachments[0].is_image)
                    self.assertEqual(attachments[1].content_type, "application/pdf")

                edit_page = self.client.get(f"/notices/{notice_id}/edit")
                self.assertEqual(edit_page.status_code, 200, edit_page.text)
                self.assertIn("文字色", edit_page.text)
                self.assertIn("背景色", edit_page.text)
                self.assertIn("photo.png", edit_page.text)

                image_response = self.client.get(f"/notices/attachments/{image_id}")
                pdf_response = self.client.get(f"/notices/attachments/{pdf_id}?download=true")
                self.assertEqual(image_response.status_code, 200)
                self.assertEqual(image_response.headers["content-type"], "image/png")
                self.assertIn("attachment", pdf_response.headers["content-disposition"])

                updated = self.client.post(
                    f"/notices/{notice_id}/edit",
                    data={
                        "title": "装飾付きのお知らせ",
                        "body": "更新本文",
                        "body_html": "<p>更新本文</p>",
                        "attachment_size_ids": str(image_id),
                        "attachment_sizes": "small",
                        "remove_attachment_ids": str(pdf_id),
                    },
                    follow_redirects=False,
                )
                self.assertEqual(updated.status_code, 303, updated.text)
                with Session(self.engine) as session:
                    remaining = session.exec(
                        select(NoticeAttachment).where(
                            NoticeAttachment.notice_id == notice_id
                        )
                    ).all()
                self.assertEqual(len(remaining), 1)
                self.assertEqual(remaining[0].display_size, "small")
                self.assertFalse((upload_root / attachments[1].storage_path).exists())

    def test_notice_attachment_rejects_unsupported_file_content(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                notice_content,
                "NOTICE_UPLOAD_ROOT",
                Path(directory) / "notice-attachments",
            ):
                response = self.client.post(
                    "/notices/",
                    data={"title": "不正添付", "body": "本文", "body_html": "<p>本文</p>"},
                    files={"attachments": ("malware.pdf", b"not-a-real-pdf", "application/pdf")},
                    follow_redirects=False,
                )
        self.assertEqual(response.status_code, 400)
        self.assertIn("PDF・JPEG・PNG・WebP", response.text)

    def test_notice_requires_admin_approval_before_publishing(self):
        created = self.client.post(
            "/notices/",
            data={
                "title": "承認対象のお知らせ",
                "body": "確認してから公開します。",
                "body_html": "<p>確認してから公開します。</p>",
                "status": "published",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303, created.text)
        notice_id = int(created.headers["location"].split("/")[2])
        with Session(self.engine) as session:
            notice = session.get(Notice, notice_id)
            self.assertEqual(notice.status, NoticeStatus.draft)

        preview = self.client.get(created.headers["location"])
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertIn("承認申請する", preview.text)

        submitted = self.client.post(
            f"/notices/{notice_id}/submit",
            follow_redirects=False,
        )
        self.assertEqual(submitted.status_code, 303, submitted.text)
        with Session(self.engine) as session:
            notice = session.get(Notice, notice_id)
            self.assertEqual(notice.status, NoticeStatus.pending_approval)

        editor_approval = self.client.post(
            f"/notices/{notice_id}/approve",
            follow_redirects=False,
        )
        editor_edit = self.client.get(f"/notices/{notice_id}/edit")
        editor_direct_update = self.client.post(
            f"/notices/{notice_id}/edit",
            data={"title": "迂回更新", "body": "本文"},
            follow_redirects=False,
        )
        self.assertEqual(editor_approval.status_code, 403)
        self.assertEqual(editor_edit.status_code, 409)
        self.assertEqual(editor_direct_update.status_code, 409)

        authenticate_mock_staff(
            self.client,
            role=Role.ADMIN,
            name="承認者 園長",
        )
        admin_preview = self.client.get(f"/notices/{notice_id}/preview")
        self.assertIn("承認して公開", admin_preview.text)
        approved = self.client.post(
            f"/notices/{notice_id}/approve",
            data={"comment": "内容を確認しました。"},
            follow_redirects=False,
        )
        self.assertEqual(approved.status_code, 303, approved.text)

        with Session(self.engine) as session:
            notice = session.get(Notice, notice_id)
            actions = session.exec(
                select(NoticeWorkflowAction)
                .where(NoticeWorkflowAction.notice_id == notice_id)
                .order_by(NoticeWorkflowAction.id)
            ).all()
        self.assertEqual(notice.status, NoticeStatus.published)
        self.assertEqual([action.action for action in actions], ["submitted", "approved"])
        self.assertEqual(actions[0].actor_name, "テスト職員")
        self.assertEqual(actions[1].actor_name, "承認者 園長")
        self.assertEqual(actions[1].comment, "内容を確認しました。")

        approved_preview = self.client.get(f"/notices/{notice_id}/preview")
        self.assertIn("申請・承認履歴", approved_preview.text)
        self.assertIn("承認者 園長", approved_preview.text)
        self.assertIn("内容を確認しました。", approved_preview.text)
        self.assertEqual(self.client.get(f"/notices/{notice_id}/edit").status_code, 409)

        unpublished = self.client.post(
            f"/notices/{notice_id}/unpublish",
            data={"reason": "内容を更新するため"},
            follow_redirects=False,
        )
        self.assertEqual(unpublished.status_code, 303)
        with Session(self.engine) as session:
            notice = session.get(Notice, notice_id)
            latest_action = session.exec(
                select(NoticeWorkflowAction)
                .where(NoticeWorkflowAction.notice_id == notice_id)
                .order_by(NoticeWorkflowAction.id.desc())
            ).first()
        self.assertEqual(notice.status, NoticeStatus.draft)
        self.assertEqual(latest_action.action, "unpublished")
        self.assertEqual(self.client.get(f"/notices/{notice_id}/edit").status_code, 200)

    def test_admin_rejection_requires_reason_and_returns_notice_to_draft(self):
        created = self.client.post(
            "/notices/",
            data={"title": "差戻し対象", "body": "確認本文"},
            follow_redirects=False,
        )
        notice_id = int(created.headers["location"].split("/")[2])
        self.client.post(f"/notices/{notice_id}/submit", follow_redirects=False)
        authenticate_mock_staff(self.client, role=Role.ADMIN, name="主任")

        missing_reason = self.client.post(
            f"/notices/{notice_id}/reject",
            follow_redirects=False,
        )
        rejected = self.client.post(
            f"/notices/{notice_id}/reject",
            data={"reason": "公開対象クラスを確認してください。"},
            follow_redirects=False,
        )
        self.assertEqual(missing_reason.status_code, 400)
        self.assertEqual(rejected.status_code, 303)

        with Session(self.engine) as session:
            notice = session.get(Notice, notice_id)
            rejection = session.exec(
                select(NoticeWorkflowAction).where(
                    NoticeWorkflowAction.notice_id == notice_id,
                    NoticeWorkflowAction.action == "rejected",
                )
            ).one()
        self.assertEqual(notice.status, NoticeStatus.draft)
        self.assertEqual(rejection.actor_name, "主任")
        self.assertEqual(rejection.comment, "公開対象クラスを確認してください。")
        preview = self.client.get(f"/notices/{notice_id}/preview")
        self.assertIn("公開対象クラスを確認してください。", preview.text)


if __name__ == "__main__":
    unittest.main()
