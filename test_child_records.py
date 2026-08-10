import unittest
from datetime import date, timedelta
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from child_records.models import (
    ChildObservationLog,
    ChildObservationLogRevision,
    ChildRecordSettingVersion,
)
from child_records.router import progress_router, router, settings_router
from child_records.settings import default_config
import child_records.router as child_records_router
from models import (
    Child,
    ChildStatus,
    Classroom,
    StaffClassroomAssignment,
    StaffClassroomAssignmentRole,
    User,
)
from plan_docs.contracts import DocumentType
from plan_docs.db_models import PlanDocumentRow


class ChildRecordFeatureTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(router)
        self.app.include_router(settings_router)
        self.app.include_router(progress_router)
        self.current_user = StaffUser(
            role=Role.ADMIN,
            name="園長",
            user_id=uuid4(),
            can_manage_child_records=True,
        )

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_current_user():
            return self.current_user

        self.app.dependency_overrides[child_records_router.get_session] = override_get_session
        self.app.dependency_overrides[
            child_records_router.get_current_staff_user
        ] = override_current_user
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            other_classroom = Classroom(name="うさぎ組", display_order=2)
            session.add(classroom)
            session.add(other_classroom)
            session.flush()
            self.classroom_id = int(classroom.id or 0)
            self.other_classroom_id = int(other_classroom.id or 0)
            child = Child(
                last_name="田中",
                first_name="花",
                last_name_kana="タナカ",
                first_name_kana="ハナ",
                birth_date=date(2024, 5, 1),
                enrollment_date=date(2025, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
            )
            session.add(child)
            session.commit()
            session.refresh(child)
            self.child_id = int(child.id or 0)

    def test_default_settings_are_available_without_saved_version(self):
        response = self.client.get("/settings/child-records")
        self.assertEqual(response.status_code, 200)
        self.assertIn("児童記録の初期設定", response.text)
        self.assertIn("標準", response.text)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(ChildRecordSettingVersion)).all(), [])

    def test_admin_saves_versioned_facility_settings(self):
        response = self.client.post(
            "/settings/child-records",
            data={
                "preset_key": "simple",
                "progress_record_view_scope": "all_staff",
                "effective_from": "2026-04-01",
                "interval_age_0": "1",
                "interval_age_1": "2",
                "interval_age_2": "3",
                "interval_age_3": "4",
                "interval_age_4": "6",
                "interval_final_year": "3",
                "enabled_fields": [
                    "observed_on",
                    "child_state",
                    "reflection",
                    "sensitivity",
                ],
                "required_fields": ["observed_on", "child_state"],
                "label_reflection": "園での振り返り",
                "custom_field_labels": "園で大切にする視点\n行事への関わり",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            setting = session.exec(select(ChildRecordSettingVersion)).one()
            self.assertEqual(setting.version_no, 1)
            self.assertEqual(setting.preset_key, "simple")
            self.assertEqual(
                setting.config["access_policy"]["progress_record_view_scope"],
                "all_staff",
            )
            self.assertEqual(
                setting.config["age_rules"]["age_0"]["child_progress_record"]["interval_months"],
                1,
            )
            fields = setting.config["record_types"]["observation_log"]["fields"]
            self.assertEqual(
                next(item for item in fields if item["key"] == "reflection")["label"],
                "園での振り返り",
            )
            self.assertEqual(sum(1 for item in fields if item.get("custom")), 2)

    def test_non_admin_cannot_open_settings(self):
        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="担任",
            user_id=uuid4(),
        )
        response = self.client.get("/settings/child-records")
        self.assertEqual(response.status_code, 403)

    def test_create_correct_and_void_observation_log(self):
        created = self.client.post(
            f"/children/{self.child_id}/records",
            data={
                "observed_on": "2026-08-10",
                "child_state": "積み木を何度も積み直していた。",
                "caregiver_support": "隣に広い場所を用意した。",
                "reflection": "試しながら高さを調整している。",
                "next_focus": "友達との協同を見守る。",
                "categories": ["興味・遊び", "成長・変化"],
                "perspective_tags": ["環境"],
                "sensitivity": "normal",
            },
            follow_redirects=False,
        )
        self.assertEqual(created.status_code, 303)
        with Session(self.engine) as session:
            log = session.exec(select(ChildObservationLog)).one()
            log_id = int(log.id or 0)
            self.assertEqual(log.categories, ["興味・遊び", "成長・変化"])

        timeline = self.client.get(f"/children/{self.child_id}/records")
        self.assertEqual(timeline.status_code, 200)
        self.assertIn("積み木を何度も積み直していた。", timeline.text)

        corrected = self.client.post(
            f"/children/{self.child_id}/records/{log_id}/correct",
            data={
                "observed_on": "2026-08-10",
                "child_state": "積み木を積み直し、友達にも一つ手渡した。",
                "caregiver_support": "隣に広い場所を用意した。",
                "reflection": "友達と一緒に作る姿へ広がった。",
                "next_focus": "言葉のやり取りも見守る。",
                "categories": ["興味・遊び"],
                "perspective_tags": ["人間関係"],
                "sensitivity": "normal",
                "correction_reason": "観察後の事実を追記するため",
            },
            follow_redirects=False,
        )
        self.assertEqual(corrected.status_code, 303)
        with Session(self.engine) as session:
            log = session.get(ChildObservationLog, log_id)
            revision = session.exec(select(ChildObservationLogRevision)).one()
            self.assertIn("友達にも一つ手渡した", log.child_state)
            self.assertIn("何度も積み直していた", revision.snapshot["child_state"])
            self.assertEqual(revision.reason, "観察後の事実を追記するため")

        voided = self.client.post(
            f"/children/{self.child_id}/records/{log_id}/void",
            data={"void_reason": "別の園児の記録だったため"},
            follow_redirects=False,
        )
        self.assertEqual(voided.status_code, 303)
        timeline = self.client.get(f"/children/{self.child_id}/records")
        self.assertNotIn("友達にも一つ手渡した", timeline.text)
        with Session(self.engine) as session:
            log = session.get(ChildObservationLog, log_id)
            self.assertIsNotNone(log.voided_at)
            self.assertEqual(log.void_reason, "別の園児の記録だったため")

    def test_assigned_teacher_can_access_only_assigned_classroom(self):
        teacher_id = uuid4()
        with Session(self.engine) as session:
            session.add(
                User(
                    id=teacher_id,
                    email="teacher-records@example.com",
                    display_name="担任",
                    staff_role="can_edit",
                )
            )
            session.add(
                StaffClassroomAssignment(
                    staff_user_id=teacher_id,
                    classroom_id=self.classroom_id,
                    assignment_role=StaffClassroomAssignmentRole.primary,
                    starts_on=date.today() - timedelta(days=30),
                    is_primary=True,
                )
            )
            session.commit()
        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="担任",
            user_id=teacher_id,
        )
        allowed = self.client.get(f"/children/{self.child_id}/records")
        self.assertEqual(allowed.status_code, 200)

        with Session(self.engine) as session:
            child = Child(
                last_name="佐藤",
                first_name="空",
                last_name_kana="サトウ",
                first_name_kana="ソラ",
                birth_date=date(2023, 4, 2),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=self.other_classroom_id,
            )
            session.add(child)
            session.commit()
            session.refresh(child)
            other_child_id = int(child.id or 0)
        denied = self.client.get(
            f"/children/{other_child_id}/records",
            follow_redirects=False,
        )
        self.assertEqual(denied.status_code, 303)
        self.assertEqual(
            denied.headers["location"],
            f"/children/{other_child_id}?child_records_denied=1",
        )

        denied_progress = self.client.get(
            f"/children/{other_child_id}/progress-records",
            follow_redirects=False,
        )
        self.assertEqual(denied_progress.status_code, 303)
        self.assertEqual(
            denied_progress.headers["location"],
            f"/children/{other_child_id}?child_records_denied=1",
        )

        denied_new_progress = self.client.get(
            f"/children/{other_child_id}/progress-records/new",
            follow_redirects=False,
        )
        self.assertEqual(denied_new_progress.status_code, 303)
        self.assertEqual(
            denied_new_progress.headers["location"],
            f"/children/{other_child_id}?child_records_denied=1",
        )

    def test_progress_record_entry_shows_logs_and_creates_versioned_document(self):
        created_log = self.client.post(
            f"/children/{self.child_id}/records",
            data={
                "observed_on": "2026-08-09",
                "child_state": "水を別の容器へ移し、量の違いを何度も確かめていた。",
                "reflection": "試しながら比べる姿が見られた。",
                "categories": ["興味・遊び"],
                "sensitivity": "normal",
            },
            follow_redirects=False,
        )
        self.assertEqual(created_log.status_code, 303)

        form = self.client.get(f"/children/{self.child_id}/progress-records/new")
        self.assertEqual(form.status_code, 200)
        self.assertIn("児童票を入力", form.text)
        self.assertIn("水を別の容器へ移し", form.text)
        self.assertIn("対象期間の子どもの姿", form.text)

        with Session(self.engine) as session:
            source_log = session.exec(select(ChildObservationLog)).one()
            source_log_id = int(source_log.id or 0)

        response = self.client.post(
            f"/children/{self.child_id}/progress-records",
            data={
                "period_start": "2026-07-01",
                "period_end": "2026-09-30",
                "cycle_key": "fy2026:2026-07-01:2026-09-30",
                "source_log_ids": [str(source_log_id)],
                "body_progress_children_overview": "水や砂の量の違いに関心を持ち、繰り返し試している。",
                "body_progress_growth_changes": "自分で確かめたことを保育者へ伝えるようになった。",
                "body_progress_support_reflection": "比較できる容器を用意したことで遊びが続いた。",
                "body_progress_family_collaboration": "家庭での水遊びの様子を共有した。",
                "body_progress_next_focus": "友達と気付きを伝え合う姿を見守る。",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertRegex(response.headers["location"], r"/plans/documents/\d+")
        with Session(self.engine) as session:
            document = session.exec(
                select(PlanDocumentRow).where(
                    PlanDocumentRow.document_type
                    == DocumentType.CHILD_PROGRESS_RECORD.value
                )
            ).one()
            self.assertEqual(document.child_id, self.child_id)
            self.assertEqual(document.period_start, "2026-07-01")
            self.assertEqual(document.period_end, "2026-09-30")
            self.assertIsNotNone(document.setting_version_id)
            self.assertIn(
                "record.child_observation_log:",
                document.sections[0]["source_refs"][0],
            )

        record_list = self.client.get(f"/children/{self.child_id}/progress-records")
        self.assertEqual(record_list.status_code, 200)
        self.assertIn("現在の児童票を開く", record_list.text)
        dashboard = self.client.get("/child-records/progress")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("児童票作成状況", dashboard.text)
        self.assertIn("下書き", dashboard.text)

        duplicate = self.client.post(
            f"/children/{self.child_id}/progress-records",
            data={
                "period_start": "2026-07-01",
                "period_end": "2026-09-30",
                "cycle_key": "fy2026:2026-07-01:2026-09-30",
                "body_progress_children_overview": "重複",
            },
            follow_redirects=False,
        )
        self.assertEqual(duplicate.status_code, 409)

    def test_all_staff_scope_allows_viewing_but_not_creating_for_other_class(self):
        with Session(self.engine) as session:
            other_child = Child(
                last_name="佐藤",
                first_name="空",
                last_name_kana="サトウ",
                first_name_kana="ソラ",
                birth_date=date(2023, 4, 2),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=self.other_classroom_id,
            )
            session.add(other_child)
            config = default_config()
            config["access_policy"]["progress_record_view_scope"] = "all_staff"
            session.add(
                ChildRecordSettingVersion(
                    version_no=1,
                    status="active",
                    preset_key="standard",
                    effective_from=date(2000, 1, 1),
                    config=config,
                )
            )
            session.commit()
            session.refresh(other_child)
            other_child_id = int(other_child.id or 0)

        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="担当外職員",
            user_id=uuid4(),
        )

        dashboard = self.client.get("/child-records/progress")
        self.assertEqual(dashboard.status_code, 200)
        self.assertIn("佐藤 空", dashboard.text)
        self.assertNotIn(
            f'/children/{other_child_id}/progress-records/new',
            dashboard.text,
        )
        self.assertIn(
            f'/children/{other_child_id}/progress-records',
            dashboard.text,
        )

        record_list = self.client.get(
            f"/children/{other_child_id}/progress-records"
        )
        self.assertEqual(record_list.status_code, 200)
        self.assertIn("閲覧のみ", record_list.text)
        self.assertNotIn(
            f'/children/{other_child_id}/records',
            record_list.text,
        )

        new_form = self.client.get(
            f"/children/{other_child_id}/progress-records/new",
            follow_redirects=False,
        )
        self.assertEqual(new_form.status_code, 303)
        self.assertEqual(
            new_form.headers["location"],
            f"/children/{other_child_id}/progress-records?permission_denied=1",
        )

        create = self.client.post(
            f"/children/{other_child_id}/progress-records",
            data={
                "period_start": "2026-07-01",
                "period_end": "2026-09-30",
                "cycle_key": "fy2026:2026-07-01:2026-09-30",
                "body_progress_children_overview": "担当外からの入力",
            },
            follow_redirects=False,
        )
        self.assertEqual(create.status_code, 403)

        observation = self.client.get(
            f"/children/{other_child_id}/records",
            follow_redirects=False,
        )
        self.assertEqual(observation.status_code, 303)

    def test_progress_dashboard_filters_by_age_and_creation_status(self):
        with Session(self.engine) as session:
            older_child = Child(
                last_name="佐藤",
                first_name="空",
                last_name_kana="サトウ",
                first_name_kana="ソラ",
                birth_date=date(2020, 5, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=self.other_classroom_id,
            )
            session.add(older_child)
            session.flush()
            child = session.get(Child, self.child_id)
            self.assertIsNotNone(child)
            cycle = child_records_router._progress_cycle(
                child,
                child_records_router.default_config(),
            )
            session.add(
                PlanDocumentRow(
                    document_type=DocumentType.CHILD_PROGRESS_RECORD.value,
                    status="draft",
                    title="田中 花 児童票",
                    nursery_ref="test-nursery",
                    classroom_ref="ひよこ組",
                    owner_name="園長",
                    school_year=cycle["fiscal_year"],
                    period_start=cycle["period_start"].isoformat(),
                    period_end=cycle["period_end"].isoformat(),
                    record_cycle_key=cycle["cycle_key"],
                    age_class=cycle["age_key"],
                    child_id=self.child_id,
                    child_ref=str(self.child_id),
                    child_name="田中 花",
                )
            )
            session.commit()
            primary_age_group = cycle["age_key"]

        by_age = self.client.get(
            "/child-records/progress",
            params={"age_group": primary_age_group},
        )
        self.assertEqual(by_age.status_code, 200)
        self.assertIn("田中 花", by_age.text)
        self.assertNotIn("佐藤 空", by_age.text)

        uncreated = self.client.get(
            "/child-records/progress",
            params={"status": "uncreated"},
        )
        self.assertEqual(uncreated.status_code, 200)
        self.assertNotIn("田中 花", uncreated.text)
        self.assertIn("佐藤 空", uncreated.text)

        draft = self.client.get(
            "/child-records/progress",
            params={"status": "draft"},
        )
        self.assertEqual(draft.status_code, 200)
        self.assertIn("田中 花", draft.text)
        self.assertNotIn("佐藤 空", draft.text)

    def test_view_only_user_cannot_follow_progress_record_create_link(self):
        self.current_user = StaffUser(
            role=Role.VIEW_ONLY,
            name="閲覧担当",
            user_id=uuid4(),
            can_manage_child_records=True,
        )

        dashboard = self.client.get("/child-records/progress")
        self.assertEqual(dashboard.status_code, 200)
        self.assertNotIn(
            f'/children/{self.child_id}/progress-records/new',
            dashboard.text,
        )
        self.assertIn(
            f'/children/{self.child_id}/progress-records',
            dashboard.text,
        )
        self.assertIn("履歴を見る", dashboard.text)

        direct = self.client.get(
            f"/children/{self.child_id}/progress-records/new",
            follow_redirects=False,
        )
        self.assertEqual(direct.status_code, 303)
        self.assertEqual(
            direct.headers["location"],
            f"/children/{self.child_id}/progress-records?permission_denied=1",
        )

        redirected = self.client.get(direct.headers["location"])
        self.assertEqual(redirected.status_code, 200)
        self.assertIn("児童票を作成できる権限がありません", redirected.text)
        self.assertIn("閲覧のみ", redirected.text)


if __name__ == "__main__":
    unittest.main()
