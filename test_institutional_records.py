import unittest
from datetime import datetime
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import inspect
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from institutional_record_service import (
    add_review,
    add_series_member,
    add_link,
    change_record_visibility,
    create_event_series,
    create_highlight,
    create_record,
    fiscal_year_for_datetime,
    highlights_for_series,
    load_record_for_view,
    promote_highlight,
    record_visible_to,
    records_for_series_of,
    remove_link,
    retire_record,
    update_record,
)
from models import (
    Calendar,
    CalendarMember,
    CalendarMemberRole,
    CalendarType,
    Event,
    EventKind,
    EventSeriesMemberTargetType,
    EventVisibility,
    HighlightSourceType,
    HighlightStatus,
    InstitutionalRecord,
    InstitutionalRecordLink,
    InstitutionalRecordOrigin,
    InstitutionalRecordRevision,
    InstitutionalRecordReview,
    InstitutionalRecordSeriesLink,
    InstitutionalRecordStatus,
    InstitutionalRecordVisibility,
    RecordLinkTargetType,
    RecordHighlight,
    RecordHighlightComment,
    RecordReviewDecision,
    RecordRevisionKind,
    MeetingNote,
    User,
)
import routers.institutional_records as records_router
from testing_helpers import authenticate_mock_staff


EDITOR_ID = UUID("00000000-0000-0000-0000-000000000101")
ADMIN_ID = UUID("00000000-0000-0000-0000-000000000102")


def editor() -> StaffUser:
    return StaffUser(role=Role.CAN_EDIT, name="編集職員", user_id=EDITOR_ID)


def admin() -> StaffUser:
    return StaffUser(role=Role.ADMIN, name="管理者", user_id=ADMIN_ID)


class InstitutionalRecordServiceTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def _create(self, session: Session, **overrides) -> InstitutionalRecord:
        values = {
            "title": "遠足の人数確認",
            "origin": InstitutionalRecordOrigin.safety_incident,
            "background": "過去の遠足で集合時の人数確認に時間差があった。",
            "purpose": "出発時の確認漏れを防ぐ。",
            "revisit_condition": "自動照合が導入され、同等以上の安全性を確認できたとき。",
        }
        values.update(overrides)
        return create_record(session, editor(), **values)

    def test_create_saves_record_and_revision_one_together(self):
        with Session(self.engine) as session:
            record = self._create(session)
            session.commit()
            record_id = record.id

        with Session(self.engine) as session:
            stored = session.get(InstitutionalRecord, record_id)
            revisions = session.exec(
                select(InstitutionalRecordRevision).where(
                    InstitutionalRecordRevision.record_id == record_id
                )
            ).all()
            self.assertEqual(stored.revision_no, 1)
            self.assertEqual(len(revisions), 1)
            self.assertEqual(revisions[0].kind, RecordRevisionKind.created)
            self.assertEqual(revisions[0].background, stored.background)

    def test_update_preserves_old_body_and_rejects_stale_revision(self):
        with Session(self.engine) as session:
            record = self._create(session)
            session.commit()
            record_id = record.id

        with Session(self.engine) as session:
            updated = update_record(
                session,
                editor(),
                record_id,
                expected_revision_no=1,
                change_note="手順を具体化したため",
                title="遠足の二重人数確認",
                origin=InstitutionalRecordOrigin.safety_incident,
                background="集合時の人数確認に時間差があった。",
                purpose="出発前に二人で照合して確認漏れを防ぐ。",
            )
            session.commit()
            self.assertEqual(updated.revision_no, 2)

        with Session(self.engine) as session:
            revisions = session.exec(
                select(InstitutionalRecordRevision)
                .where(InstitutionalRecordRevision.record_id == record_id)
                .order_by(InstitutionalRecordRevision.revision_no)
            ).all()
            self.assertEqual([item.revision_no for item in revisions], [1, 2])
            self.assertIn("過去の遠足", revisions[0].background)
            self.assertEqual(revisions[1].change_note, "手順を具体化したため")

            with self.assertRaises(HTTPException) as caught:
                update_record(
                    session,
                    editor(),
                    record_id,
                    expected_revision_no=1,
                    change_note="古い画面から更新",
                    title="競合する題名",
                    origin=InstitutionalRecordOrigin.safety_incident,
                    background="競合する背景",
                    purpose="競合する目的",
                )
            self.assertEqual(caught.exception.status_code, 409)

    def test_retire_keeps_record_and_adds_immutable_revision(self):
        with Session(self.engine) as session:
            record = self._create(session)
            session.commit()
            record_id = record.id

        with Session(self.engine) as session:
            retired = retire_record(
                session,
                editor(),
                record_id,
                expected_revision_no=1,
                change_note="自動照合へ移行したため",
            )
            session.commit()
            self.assertEqual(retired.status, InstitutionalRecordStatus.retired)
            self.assertEqual(retired.revision_no, 2)
            revision = session.exec(
                select(InstitutionalRecordRevision).where(
                    InstitutionalRecordRevision.record_id == record_id,
                    InstitutionalRecordRevision.revision_no == 2,
                )
            ).one()
            self.assertEqual(revision.kind, RecordRevisionKind.retired)
            self.assertEqual(revision.change_note, "自動照合へ移行したため")

    def test_external_link_can_be_removed_and_reactivated_without_duplicate(self):
        with Session(self.engine) as session:
            record = self._create(
                session,
                visibility=InstitutionalRecordVisibility.linked_targets,
                initial_target_type=RecordLinkTargetType.external,
                initial_target_label="紙の安全管理規程",
            )
            session.commit()
            record_id = record.id
            link = session.exec(
                select(InstitutionalRecordLink).where(
                    InstitutionalRecordLink.record_id == record_id
                )
            ).one()
            link_id = link.id

        with Session(self.engine) as session:
            record = load_record_for_view(session, editor(), record_id)
            self.assertTrue(record_visible_to(session, editor(), record))
            remove_link(session, editor(), record_id, link_id)
            session.commit()

        with Session(self.engine) as session:
            isolated = session.get(InstitutionalRecord, record_id)
            self.assertFalse(record_visible_to(session, editor(), isolated))
            self.assertTrue(record_visible_to(session, admin(), isolated))
            restored = add_link(
                session,
                admin(),
                record_id,
                target_type=RecordLinkTargetType.external,
                target_id=None,
                target_label=" 紙の安全管理規程 ",
            )
            session.commit()
            self.assertEqual(restored.id, link_id)
            self.assertIsNone(restored.removed_at)
            count = len(
                session.exec(
                    select(InstitutionalRecordLink).where(
                        InstitutionalRecordLink.record_id == record_id
                    )
                ).all()
            )
            self.assertEqual(count, 1)

    def test_visibility_expansion_requires_admin_and_creates_revision(self):
        with Session(self.engine) as session:
            record = self._create(
                session,
                visibility=InstitutionalRecordVisibility.linked_targets,
                initial_target_type=RecordLinkTargetType.external,
                initial_target_label="限定手順書",
            )
            session.commit()
            record_id = record.id

        with Session(self.engine) as session:
            with self.assertRaises(HTTPException) as caught:
                change_record_visibility(
                    session,
                    editor(),
                    record_id,
                    new_visibility=InstitutionalRecordVisibility.staff,
                    expected_revision_no=1,
                    change_note="全職員で共有するため",
                )
            self.assertEqual(caught.exception.status_code, 403)

        with Session(self.engine) as session:
            changed = change_record_visibility(
                session,
                admin(),
                record_id,
                new_visibility=InstitutionalRecordVisibility.staff,
                expected_revision_no=1,
                change_note="全職員で共有してよいことを確認したため",
            )
            session.commit()
            self.assertEqual(changed.visibility, InstitutionalRecordVisibility.staff)
            revision = session.exec(
                select(InstitutionalRecordRevision).where(
                    InstitutionalRecordRevision.record_id == record_id,
                    InstitutionalRecordRevision.revision_no == 2,
                )
            ).one()
            self.assertEqual(revision.kind, RecordRevisionKind.visibility_changed)

    def test_remove_link_rejects_child_id_from_another_record(self):
        with Session(self.engine) as session:
            first = self._create(session, title="一件目")
            second = self._create(
                session,
                title="二件目",
                initial_target_type=RecordLinkTargetType.external,
                initial_target_label="別の規程",
            )
            session.commit()
            link = session.exec(
                select(InstitutionalRecordLink).where(
                    InstitutionalRecordLink.record_id == second.id
                )
            ).one()
            with self.assertRaises(HTTPException) as caught:
                remove_link(session, editor(), first.id, link.id)
            self.assertEqual(caught.exception.status_code, 404)

    def test_highlight_promotion_creates_the_vertical_record_bundle_idempotently(self):
        with Session(self.engine) as session:
            note = MeetingNote(title="運動会反省会", created_by="編集職員")
            session.add(note)
            session.flush()
            series = create_event_series(session, editor(), name="運動会")
            highlight = create_highlight(
                session,
                editor(),
                source_type=HighlightSourceType.meeting_note,
                source_id=note.id,
                excerpt="受付開始直後に入口が混雑した。",
                origin=InstitutionalRecordOrigin.retrospective,
                series_id=series.id,
                fiscal_year=2025,
                comment="次年度は受付を二列にする",
            )
            record = promote_highlight(
                session,
                editor(),
                highlight.id,
                title="運動会受付の二列化",
                purpose="受付の滞留を防ぐ。",
            )
            session.commit()
            record_id = record.id
            highlight_id = highlight.id

        with Session(self.engine) as session:
            stored_highlight = session.get(RecordHighlight, highlight_id)
            stored_record = session.get(InstitutionalRecord, record_id)
            revisions = session.exec(
                select(InstitutionalRecordRevision).where(
                    InstitutionalRecordRevision.record_id == record_id
                )
            ).all()
            source_links = session.exec(
                select(InstitutionalRecordLink).where(
                    InstitutionalRecordLink.record_id == record_id,
                    InstitutionalRecordLink.target_type == RecordLinkTargetType.meeting_note,
                )
            ).all()
            series_links = session.exec(
                select(InstitutionalRecordSeriesLink).where(
                    InstitutionalRecordSeriesLink.record_id == record_id
                )
            ).all()
            comments = session.exec(
                select(RecordHighlightComment).where(
                    RecordHighlightComment.highlight_id == highlight_id
                )
            ).all()
            self.assertEqual(stored_highlight.status, HighlightStatus.promoted)
            self.assertEqual(stored_highlight.promoted_record_id, record_id)
            self.assertEqual(stored_record.source_highlight_id, highlight_id)
            self.assertEqual(stored_record.background, "受付開始直後に入口が混雑した。")
            self.assertEqual(len(revisions), 1)
            self.assertEqual(len(source_links), 1)
            self.assertEqual(len(series_links), 1)
            self.assertEqual(series_links[0].fiscal_year, 2025)
            self.assertEqual(len(comments), 1)

            same_record = promote_highlight(
                session,
                editor(),
                highlight_id,
                title="重複しない",
                purpose="重複しない",
            )
            self.assertEqual(same_record.id, record_id)
            self.assertEqual(
                len(session.exec(select(InstitutionalRecord)).all()),
                1,
            )

    def test_series_carries_prior_record_and_highlight_into_next_year_review(self):
        with Session(self.engine) as session:
            user = User(
                id=EDITOR_ID,
                email="editor@example.test",
                display_name="編集職員",
                staff_role="can_edit",
            )
            calendar = Calendar(
                owner_user_id=EDITOR_ID,
                name="園行事",
                calendar_type=CalendarType.facility_shared,
            )
            session.add(user)
            session.add(calendar)
            session.flush()
            session.add(
                CalendarMember(
                    calendar_id=calendar.id,
                    user_id=EDITOR_ID,
                    role=CalendarMemberRole.owner,
                )
            )
            event_2025 = Event(
                calendar_id=calendar.id,
                created_by_user_id=EDITOR_ID,
                kind=EventKind.single,
                title="運動会2025",
                start_at=datetime(2025, 9, 10, 0, 0),
                end_at=datetime(2025, 9, 10, 6, 0),
                visibility=EventVisibility.normal,
            )
            event_2026 = Event(
                calendar_id=calendar.id,
                created_by_user_id=EDITOR_ID,
                kind=EventKind.single,
                title="運動会2026",
                start_at=datetime(2026, 9, 10, 0, 0),
                end_at=datetime(2026, 9, 10, 6, 0),
                visibility=EventVisibility.normal,
            )
            note = MeetingNote(title="運動会反省会")
            session.add(event_2025)
            session.add(event_2026)
            session.add(note)
            session.flush()
            series = create_event_series(session, editor(), name="運動会")
            add_series_member(
                session,
                editor(),
                series.id,
                target_type=EventSeriesMemberTargetType.event,
                target_id=event_2025.id,
                fiscal_year=2025,
            )
            current_member = add_series_member(
                session,
                editor(),
                series.id,
                target_type=EventSeriesMemberTargetType.event,
                target_id=event_2026.id,
                fiscal_year=2026,
            )
            promoted_highlight = create_highlight(
                session,
                editor(),
                source_type=HighlightSourceType.meeting_note,
                source_id=note.id,
                excerpt="集合案内が二か所に分かれて混乱した。",
                origin=InstitutionalRecordOrigin.retrospective,
                series_id=series.id,
                fiscal_year=2025,
            )
            record = promote_highlight(
                session,
                editor(),
                promoted_highlight.id,
                title="集合案内の一本化",
                purpose="案内場所の認識違いを防ぐ。",
            )
            active_highlight = create_highlight(
                session,
                editor(),
                source_type=HighlightSourceType.meeting_note,
                source_id=note.id,
                excerpt="日除け用テントを増やしたい。",
                origin=InstitutionalRecordOrigin.retrospective,
                series_id=series.id,
                fiscal_year=2025,
            )
            event_2026_id = event_2026.id
            series_id = series.id
            record_id = record.id
            current_member_id = current_member.id
            active_highlight_id = active_highlight.id
            session.commit()

        with Session(self.engine) as session:
            views = records_for_series_of(
                session,
                editor(),
                EventSeriesMemberTargetType.event,
                event_2026_id,
            )
            past_highlights = highlights_for_series(
                session,
                editor(),
                series_id,
                before_fiscal_year=2026,
            )
            self.assertEqual([item.record.id for item in views], [record_id])
            self.assertEqual([item.id for item in past_highlights], [active_highlight_id])

            review = add_review(
                session,
                editor(),
                record_id,
                series_member_id=current_member_id,
                review_cycle_fiscal_year=2026,
                decision=RecordReviewDecision.keep,
            )
            duplicate = add_review(
                session,
                editor(),
                record_id,
                series_member_id=current_member_id,
                review_cycle_fiscal_year=2026,
                decision=RecordReviewDecision.keep,
            )
            session.commit()
            self.assertEqual(review.id, duplicate.id)
            self.assertIsNotNone(session.get(InstitutionalRecord, record_id).review_due_on)
            self.assertEqual(
                len(session.exec(select(InstitutionalRecordReview)).all()),
                1,
            )

    def test_recurring_event_cannot_be_a_series_member(self):
        with Session(self.engine) as session:
            user = User(
                id=EDITOR_ID,
                email="repeat@example.test",
                display_name="編集職員",
                staff_role="can_edit",
            )
            calendar = Calendar(owner_user_id=EDITOR_ID, name="個人予定")
            session.add(user)
            session.add(calendar)
            session.flush()
            session.add(
                CalendarMember(
                    calendar_id=calendar.id,
                    user_id=EDITOR_ID,
                    role=CalendarMemberRole.owner,
                )
            )
            recurring = Event(
                calendar_id=calendar.id,
                created_by_user_id=EDITOR_ID,
                kind=EventKind.series_master,
                title="毎週の行事",
                start_at=datetime(2026, 5, 1, 0, 0),
                end_at=datetime(2026, 5, 1, 1, 0),
            )
            session.add(recurring)
            session.flush()
            series = create_event_series(session, editor(), name="定例行事")
            with self.assertRaises(HTTPException) as caught:
                add_series_member(
                    session,
                    editor(),
                    series.id,
                    target_type=EventSeriesMemberTargetType.event,
                    target_id=recurring.id,
                    fiscal_year=2026,
                )
            self.assertEqual(caught.exception.status_code, 400)

    def test_fiscal_year_uses_japan_boundary(self):
        self.assertEqual(
            fiscal_year_for_datetime(datetime(2026, 3, 31, 14, 59), "Asia/Tokyo"),
            2025,
        )
        self.assertEqual(
            fiscal_year_for_datetime(datetime(2026, 3, 31, 15, 0), "Asia/Tokyo"),
            2026,
        )

    def test_schema_contains_both_highlight_foreign_keys(self):
        db_inspector = inspect(self.engine)
        record_fks = db_inspector.get_foreign_keys("institutional_records")
        highlight_fks = db_inspector.get_foreign_keys("record_highlights")
        self.assertTrue(
            any(
                fk["referred_table"] == "record_highlights"
                and fk["constrained_columns"] == ["source_highlight_id"]
                for fk in record_fks
            )
        )
        self.assertTrue(
            any(
                fk["referred_table"] == "institutional_records"
                and fk["constrained_columns"] == ["promoted_record_id"]
                for fk in highlight_fks
            )
        )


class InstitutionalRecordRouterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(records_router.router)
        self.app.include_router(records_router.highlights_router)
        self.app.include_router(records_router.event_series_router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[records_router.get_session] = override_get_session
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_login_is_required(self):
        response = self.client.get("/records/", headers={"accept": "application/json"})
        self.assertEqual(response.status_code, 401)

    def test_editor_can_create_and_view_record(self):
        authenticate_mock_staff(self.client, user_id=EDITOR_ID)
        response = self.client.post(
            "/records/",
            data={
                "title": "避難経路の確認",
                "origin": "administrative",
                "background": "監査で経路表示の確認方法を見直した。",
                "purpose": "避難誘導時の迷いを防ぐ。",
                "visibility": "staff",
                # Chromeが以前の選択値だけ復元しても、明示チェックなしなら無視する。
                "initial_target_type": "survey",
                "initial_target_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        detail = self.client.get(response.headers["location"])
        self.assertEqual(detail.status_code, 200)
        self.assertIn("避難経路の確認", detail.text)
        self.assertIn("監査で経路表示", detail.text)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(InstitutionalRecordLink)).all()), 0)

    def test_view_only_staff_cannot_create(self):
        authenticate_mock_staff(self.client, role=Role.VIEW_ONLY, user_id=EDITOR_ID)
        response = self.client.post(
            "/records/",
            data={
                "title": "作成不可",
                "origin": "operational",
                "background": "背景",
                "purpose": "目的",
                "visibility": "staff",
            },
        )
        self.assertEqual(response.status_code, 403)

    def test_event_series_page_and_routes_are_registered(self):
        authenticate_mock_staff(self.client, user_id=EDITOR_ID)
        response = self.client.get("/event-series/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("行事シリーズ", response.text)
        route_paths = {route.path for route in self.app.routes}
        self.assertIn("/highlights/", route_paths)
        self.assertIn("/event-series/{series_id}/members", route_paths)


if __name__ == "__main__":
    unittest.main()
