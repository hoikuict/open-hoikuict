"""Regression coverage for writing and editing a completed period's child record."""
from datetime import date
from html.parser import HTMLParser
from unittest.mock import patch
import unittest
from uuid import uuid4

from sqlmodel import Session, select

from auth import Role, StaffUser
from child_records.models import ChildObservationLog, ChildRecordSettingVersion
from child_records.settings import default_config
from models import Child, ChildStatus
from plan_docs.db_models import PlanDocumentRow, PlanRevisionRow
import test_child_records as fixtures


class FormInputs(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.values = {}
        self.checked = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "input" and attrs.get("name"):
            self.values[attrs["name"]] = attrs.get("value", "")
            if attrs.get("name") == "source_log_ids" and "checked" in attrs:
                self.checked.append(attrs["value"])


class ChildProgressPeriodTests(unittest.TestCase):
    def setUp(self):
        fixtures.ChildRecordFeatureTests.setUp(self)
        self.clock = patch("child_records.router.local_today", return_value=date(2026, 10, 8))
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.addCleanup(self.engine.dispose)
        self.addCleanup(self.client.close)
        self.config = default_config()
        for rule in self.config["age_rules"].values():
            rule["child_progress_record"]["interval_months"] = 1
        self.set_config(self.config)
        self.url = f"/children/{self.child_id}/progress-records"

    def set_config(self, config):
        with Session(self.engine) as session:
            setting = session.exec(select(ChildRecordSettingVersion)).first()
            if setting is None:
                setting = ChildRecordSettingVersion(version_no=1, effective_from=date(2000, 1, 1), config=config)
            else:
                setting.config = config
            session.add(setting)
            session.commit()

    def form(self, **params):
        response = self.client.get(self.url + "/new", params=params, follow_redirects=False)
        self.assertEqual(response.status_code, 200)
        return response, FormInputs(response.text)

    def payload(self, fields, **extra):
        data = {k: v for k, v in fields.values.items() if k in {
            "period_start", "period_end", "cycle_key", "document_id", "lock_version", "continue_url"}}
        return {**data, "body_progress_children_overview": "調査用の子どもの姿", **extra}

    def save(self, fields, **extra):
        return self.client.post(self.url, data=self.payload(fields, **extra), follow_redirects=False)

    def rows(self):
        with Session(self.engine) as session:
            return session.exec(select(PlanDocumentRow)).all()

    def log(self, day, body):
        with Session(self.engine) as session:
            log = ChildObservationLog(child_id=self.child_id, observed_on=day, child_state=body,
                visibility="shared", sensitivity="normal", created_by_name="調査用")
            session.add(log)
            session.commit()
            session.refresh(log)
            return log.id

    def test_monthly_defaults_follow_the_previous_month_across_years(self):
        for today, start, end in [(date(2026, 10, 8), "2026-09-01", "2026-09-30"),
                                 (date(2027, 1, 8), "2026-12-01", "2026-12-31"),
                                 (date(2027, 4, 8), "2027-03-01", "2027-03-31")]:
            with self.subTest(today=today), patch("child_records.router.local_today", return_value=today):
                _, fields = self.form()
                self.assertEqual((fields.values["period_start"], fields.values["period_end"]), (start, end))

    def test_quarterly_waits_for_the_whole_period_to_finish(self):
        self.set_config(default_config())
        for today, start, end in [(date(2026, 10, 8), "2026-07-01", "2026-09-30"),
                                 (date(2026, 11, 8), "2026-07-01", "2026-09-30"),
                                 (date(2027, 4, 8), "2027-01-01", "2027-03-31")]:
            with self.subTest(today=today), patch("child_records.router.local_today", return_value=today):
                _, fields = self.form()
                self.assertEqual((fields.values["period_start"], fields.values["period_end"]), (start, end))

    def test_selected_month_controls_form_logs_dashboard_and_filters(self):
        self.log(date(2026, 9, 3), "SEPTEMBER_LOG")
        self.log(date(2026, 10, 3), "OCTOBER_LOG")
        response, fields = self.form()
        self.assertIn("SEPTEMBER_LOG", response.text)
        self.assertNotIn("OCTOBER_LOG", response.text)
        october, selected = self.form(target_month="2026-10")
        self.assertEqual(selected.values["period_start"], "2026-10-01")
        self.assertIn("OCTOBER_LOG", october.text)
        self.assertNotIn("SEPTEMBER_LOG", october.text)
        self.assertEqual(self.save(fields).status_code, 303)
        dashboard = self.client.get("/child-records/progress", params={"target_month": "2026-09", "status": "draft"})
        self.assertIn("続きを入力", dashboard.text)
        self.assertIn('name="target_month" value="2026-09"', dashboard.text)
        october_dash = self.client.get("/child-records/progress", params={"target_month": "2026-10", "status": "draft"})
        self.assertIn("条件に一致する園児はいません", october_dash.text)

    def test_legacy_manual_record_is_opened_and_updated_without_duplicate(self):
        _, fields = self.form()
        self.save(fields)
        with Session(self.engine) as session:
            row = session.exec(select(PlanDocumentRow)).one()
            original_id, created = row.id, row.created_at
            row.record_cycle_key = "manual:2026-09-01:2026-09-30"
            session.add(row)
            session.commit()
        response, fields = self.form(period_start="2026-09-01", period_end="2026-09-30")
        self.assertIn("保存済みの下書き", response.text)
        self.assertEqual(fields.values["document_id"], str(original_id))
        saved = self.save(fields, body_progress_children_overview="追記した子どもの姿")
        self.assertEqual(saved.status_code, 303)
        rows = self.rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].created_at, created)
        self.assertEqual(rows[0].period_start, "2026-09-01")
        self.assertEqual(rows[0].sections[0]["body"], "追記した子どもの姿")
        self.assertIn("続きを入力", self.client.get("/child-records/progress").text)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(PlanRevisionRow)).all()), 2)

    def test_client_cycle_key_is_ignored_and_second_create_preserves_input(self):
        log_id = self.log(date(2026, 9, 10), "根拠の記録")
        _, fields = self.form()
        self.assertEqual(self.save(fields, cycle_key="arbitrary-input").status_code, 303)
        self.assertEqual(self.rows()[0].record_cycle_key, "fy2026:2026-09-01:2026-09-30")
        duplicate = self.save(fields, cycle_key="manual:2026-09-01:2026-09-30", source_log_ids=[str(log_id)],
                              body_progress_children_overview="保持する新規入力")
        self.assertEqual(duplicate.status_code, 409)
        self.assertIn("保持する新規入力", duplicate.text)
        self.assertIn(str(log_id), FormInputs(duplicate.text).checked)
        self.assertEqual(len(self.rows()), 1)

    def test_concurrent_edit_does_not_overwrite_the_first_save(self):
        _, fields = self.form()
        self.save(fields)
        _, opened = self.form()
        self.assertEqual(self.save(opened, body_progress_children_overview="先に保存").status_code, 303)
        stale = self.save(opened, body_progress_children_overview="あとから保存")
        self.assertEqual(stale.status_code, 409)
        self.assertIn("あとから保存", stale.text)
        self.assertIn("他の職員が先に更新", stale.text)
        self.assertEqual(self.rows()[0].sections[0]["body"], "先に保存")

    def test_review_status_cannot_be_bypassed_by_the_new_form(self):
        _, fields = self.form()
        self.save(fields)
        _, opened = self.form()
        with Session(self.engine) as session:
            row = session.exec(select(PlanDocumentRow)).one()
            row.status = "approved"
            session.add(row)
            session.commit()
        denied = self.save(opened, body_progress_children_overview="上書き不可")
        self.assertEqual(denied.status_code, 409)
        self.assertEqual(self.rows()[0].sections[0]["body"], "調査用の子どもの姿")
        self.assertEqual(self.client.get(self.url + "/new", follow_redirects=False).status_code, 303)

    def test_log_selection_is_retained_on_validation_and_can_be_changed_on_edit(self):
        first = self.log(date(2026, 9, 3), "最初の根拠")
        second = self.log(date(2026, 9, 10), "次の根拠")
        outside = self.log(date(2026, 10, 1), "対象外")
        _, fields = self.form()
        invalid = self.save(fields, body_progress_children_overview="", body_progress_growth_changes="消さない入力", source_log_ids=[str(first)])
        self.assertEqual(invalid.status_code, 422)
        self.assertIn("消さない入力", invalid.text)
        self.assertEqual(FormInputs(invalid.text).checked, [str(first)])
        self.save(fields, source_log_ids=[str(first)])
        response, opened = self.form()
        self.assertEqual(opened.checked, [str(first)])
        self.assertEqual(self.save(opened, source_log_ids=[str(second), str(outside)]).status_code, 303)
        _, reopened = self.form()
        self.assertEqual(reopened.checked, [str(second)])
        self.assertEqual(len(self.rows()[0].sections[0]["source_refs"]), 1)

    def test_leaving_children_remain_visible_only_for_their_enrollment_period(self):
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            child.status = ChildStatus.withdrawn
            child.withdrawal_date = date(2026, 9, 30)
            session.add(child)
            session.commit()
        self.assertIn("田中 花", self.client.get("/child-records/progress").text)
        _, fields = self.form()
        self.assertEqual(self.save(fields).status_code, 303)
        october = self.client.get("/child-records/progress", params={"target_month": "2026-10"})
        self.assertNotIn("田中 花", october.text)
        denied, _ = self.form(target_month="2026-10")
        self.assertIn("対象期間に在籍していません", denied.text)
        self.assertNotIn('data-progress-body', denied.text)
        self.assertEqual(self.client.post(self.url, data={"period_start": "2026-10-01", "period_end": "2026-10-31"}, follow_redirects=False).status_code, 422)

    def test_graduated_children_can_have_march_record_created_in_april(self):
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            child.status = ChildStatus.graduated
            child.withdrawal_date = date(2027, 3, 31)
            session.add(child)
            session.commit()
        with patch("child_records.router.local_today", return_value=date(2027, 4, 8)):
            self.assertIn("田中 花", self.client.get("/child-records/progress").text)
            _, fields = self.form()
            self.assertEqual(fields.values["period_start"], "2027-03-01")
            self.assertEqual(self.save(fields).status_code, 303)
            self.assertEqual(self.rows()[0].school_year, 2026)
            self.assertEqual(self.rows()[0].age_class, "age_1")

    def test_newly_enrolled_child_is_not_shown_before_enrollment(self):
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            child.enrollment_date = date(2026, 10, 1)
            session.add(child)
            session.commit()
        self.assertNotIn("田中 花", self.client.get("/child-records/progress").text)
        self.assertIn("田中 花", self.client.get("/child-records/progress", params={"target_month": "2026-10"}).text)

    def test_existing_duplicate_records_are_preserved_and_each_can_be_opened(self):
        _, fields = self.form()
        self.save(fields)
        with Session(self.engine) as session:
            original = session.exec(select(PlanDocumentRow)).one()
            duplicate = PlanDocumentRow(**original.model_dump(exclude={"id", "record_cycle_key"}),
                                        record_cycle_key="manual:2026-09-01:2026-09-30")
            session.add(duplicate)
            session.commit()
        response, _ = self.form()
        self.assertIn("同じ期間の児童票が2件", response.text)
        for row in self.rows():
            _, fields = self.form(document_id=row.id)
            self.assertEqual(fields.values["document_id"], str(row.id))
        self.assertEqual(len(self.rows()), 2)

    def test_saved_period_and_child_identity_cannot_be_changed(self):
        _, fields = self.form()
        self.save(fields)
        _, opened = self.form()
        self.assertEqual(self.save(opened, period_start="2026-08-01").status_code, 422)
        self.assertEqual(self.save(opened, document_id="999999").status_code, 404)
        self.assertEqual(self.rows()[0].period_start, "2026-09-01")

    def test_save_and_move_only_accepts_internal_progress_pages(self):
        _, fields = self.form()
        bad = self.save(fields, continue_url="https://example.com/")
        self.assertEqual(bad.status_code, 422)
        self.assertEqual(len(self.rows()), 0)
        destination = self.url + "/new?target_month=2026-10"
        result = self.save(fields, continue_url=destination)
        self.assertEqual(result.status_code, 303)
        self.assertEqual(result.headers["location"], destination)
        self.assertEqual(self.rows()[0].period_start, "2026-09-01")

    def test_bad_months_and_partial_period_queries_are_rejected(self):
        for target in ("2026-13", "2026-9", "bad", "9999-12"):
            self.assertEqual(self.client.get(self.url + "/new", params={"target_month": target}).status_code, 422)
        self.assertEqual(self.client.get(self.url + "/new", params={"period_start": "2026-09-01"}).status_code, 422)

    def test_unauthorized_teacher_cannot_edit_saved_record(self):
        _, fields = self.form()
        self.save(fields)
        _, opened = self.form()
        self.current_user = StaffUser(role=Role.CAN_EDIT, name="担当外", user_id=uuid4())
        self.assertEqual(self.save(opened).status_code, 403)

    def test_default_period_uses_the_previous_fiscal_year_age_rule(self):
        config = default_config()
        config["age_rules"]["age_0"]["child_progress_record"]["interval_months"] = 1
        self.set_config(config)
        with patch("child_records.router.local_today", return_value=date(2026, 4, 8)):
            _, fields = self.form()
            self.assertEqual(fields.values["period_start"], "2026-03-01")
            self.assertEqual(fields.values["period_end"], "2026-03-31")

    def test_short_final_cycle_and_different_age_intervals(self):
        config = default_config()
        config["age_rules"]["age_1"]["child_progress_record"]["interval_months"] = 5
        self.set_config(config)
        with patch("child_records.router.local_today", return_value=date(2027, 4, 8)):
            _, fields = self.form()
            self.assertEqual(fields.values["period_start"], "2027-02-01")
            self.assertEqual(fields.values["period_end"], "2027-03-31")
        config["age_rules"]["age_1"]["child_progress_record"]["interval_months"] = 1
        self.set_config(config)
        with Session(self.engine) as session:
            session.add(Child(last_name="別周期", first_name="園児", last_name_kana="ベツ", first_name_kana="エンジ",
                birth_date=date(2020, 5, 1), enrollment_date=date(2025, 4, 1), classroom_id=self.other_classroom_id))
            session.commit()
        with patch("child_records.router.local_today", return_value=date(2026, 11, 8)):
            dashboard = self.client.get("/child-records/progress")
            self.assertIn("2026/10/01〜2026/10/31", dashboard.text)
            self.assertIn("2026/07/01〜2026/09/30", dashboard.text)

    def test_error_page_marks_submitted_content_as_unsaved(self):
        _, fields = self.form()
        invalid = self.save(fields, body_progress_children_overview="", body_progress_growth_changes="保持する内容")
        self.assertEqual(invalid.status_code, 422)
        self.assertIn('data-progress-has-unsaved="true"', invalid.text)


if __name__ == "__main__":
    unittest.main()
