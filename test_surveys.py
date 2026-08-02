import unittest
from datetime import date, datetime, timezone

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    Child,
    ChildStatus,
    Classroom,
    Family,
    ParentAccount,
    ParentAccountStatus,
    QuestionType,
    Survey,
    SurveyAnswer,
    SurveyAnswerUnit,
    SurveyAudienceType,
    SurveyQuestion,
    SurveyResponse,
    SurveyStatus,
    SurveyTarget,
    SurveyTargetType,
    User,
)
from survey_service import eligible_staff_users_for_survey
from survey_service import survey_effective_status_label
from survey_service import survey_is_open
from time_utils import utc_now
from survey_service import unanswered_parent_survey_count
import routers.parent_portal as parent_portal_module
import routers.staff_auth as staff_auth_module
import routers.staff_surveys as staff_surveys_module
import routers.surveys as surveys_module


class SurveyFeatureTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(parent_portal_module.router)
        self.app.include_router(staff_auth_module.router)
        self.app.include_router(staff_surveys_module.router)
        self.app.include_router(surveys_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[parent_portal_module.get_session] = override_get_session
        self.app.dependency_overrides[staff_auth_module.get_session] = override_get_session
        self.app.dependency_overrides[staff_surveys_module.get_session] = override_get_session
        self.app.dependency_overrides[surveys_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.flush()
            self.classroom_id = classroom.id
            family = Family(family_name="田中家")
            session.add(family)
            session.flush()
            child = Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2021, 5, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family.id,
            )
            session.add(child)
            session.flush()
            parent = ParentAccount(
                display_name="田中 花",
                email="tanaka@example.com",
                status=ParentAccountStatus.active,
                family_id=family.id,
            )
            staff = User(
                email="staff@example.com",
                display_name="佐藤先生",
                staff_role="can_edit",
                staff_sort_order=10,
                is_active=True,
            )
            duplicate_staff = User(
                email="zz-staff-duplicate@example.com",
                display_name="佐藤先生",
                staff_role="can_edit",
                staff_sort_order=10,
                is_active=True,
            )
            late_staff = User(
                email="late-staff@example.com",
                display_name="遅番パート",
                staff_role="view_only",
                staff_sort_order=150,
                is_active=True,
            )
            session.add(parent)
            session.add(staff)
            session.add(duplicate_staff)
            session.add(late_staff)
            session.flush()
            self.parent_account_id = parent.id
            self.family_id = family.id
            self.staff_user_id = staff.id
            self.duplicate_staff_user_id = duplicate_staff.id
            self.late_staff_user_id = late_staff.id

            parent_survey = Survey(
                title="保護者アンケート",
                status=SurveyStatus.published,
                audience_type=SurveyAudienceType.parent,
                answer_unit=SurveyAnswerUnit.family,
            )
            staff_survey = Survey(
                title="職員アンケート",
                status=SurveyStatus.published,
                audience_type=SurveyAudienceType.staff,
                answer_unit=SurveyAnswerUnit.staff_user,
            )
            session.add(parent_survey)
            session.add(staff_survey)
            session.flush()
            self.parent_survey_id = parent_survey.id
            self.staff_survey_id = staff_survey.id
            session.add(SurveyTarget(survey_id=parent_survey.id, target_type=SurveyTargetType.all))
            session.add(SurveyTarget(survey_id=staff_survey.id, target_type=SurveyTargetType.all_staff))
            parent_question = SurveyQuestion(
                survey_id=parent_survey.id,
                order=1,
                question_type=QuestionType.text_short,
                label="好きな行事",
                is_required=True,
            )
            staff_question = SurveyQuestion(
                survey_id=staff_survey.id,
                order=1,
                question_type=QuestionType.yes_no,
                label="参加できますか",
                is_required=True,
            )
            session.add(parent_question)
            session.add(staff_question)
            session.flush()
            self.parent_question_id = parent_question.id
            self.staff_question_id = staff_question.id
            session.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _login_parent(self):
        response = self.client.post(
            "/parent-portal/login",
            data={"parent_account_id": self.parent_account_id},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def _login_staff(self, user_id=None):
        response = self.client.post(
            "/staff/login",
            data={"user_id": str(user_id or self.staff_user_id), "redirect_to": "/staff-surveys/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_parent_can_answer_family_survey_and_update_existing_answer(self):
        self._login_parent()

        list_response = self.client.get("/parent-portal/surveys")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("保護者アンケート", list_response.text)

        response = self.client.post(
            f"/parent-portal/surveys/{self.parent_survey_id}",
            data={f"q{self.parent_question_id}": "運動会"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        response = self.client.post(
            f"/parent-portal/surveys/{self.parent_survey_id}",
            data={f"q{self.parent_question_id}": "遠足"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            answers = session.exec(select(SurveyAnswer).where(SurveyAnswer.survey_id == self.parent_survey_id)).all()
            responses = session.exec(select(SurveyResponse)).all()
            survey = session.get(Survey, self.parent_survey_id)
            unanswered_count = unanswered_parent_survey_count(session, survey)

        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0].family_id, self.family_id)
        self.assertEqual(responses[0].value_text, "遠足")
        self.assertEqual(unanswered_count, 0)

    def test_parent_survey_appears_as_new_home_update_until_answered(self):
        self._login_parent()

        home_response = self.client.get("/parent-portal/")

        self.assertEqual(home_response.status_code, 200)
        self.assertIn("保護者アンケート", home_response.text)
        self.assertIn("未回答", home_response.text)
        self.assertIn(f'/parent-portal/surveys/{self.parent_survey_id}', home_response.text)

        answer_response = self.client.post(
            f"/parent-portal/surveys/{self.parent_survey_id}",
            data={f"q{self.parent_question_id}": "夏祭り"},
            follow_redirects=False,
        )
        self.assertEqual(answer_response.status_code, 303)

        answered_home_response = self.client.get("/parent-portal/")
        self.assertNotIn("保護者アンケート", answered_home_response.text)

    def test_parent_unanswered_count_deduplicates_accounts_in_same_family(self):
        with Session(self.engine) as session:
            session.add(
                ParentAccount(
                    display_name="田中 太郎",
                    email="tanaka-father@example.com",
                    status=ParentAccountStatus.active,
                    family_id=self.family_id,
                )
            )
            session.commit()
            survey = session.get(Survey, self.parent_survey_id)

            self.assertEqual(unanswered_parent_survey_count(session, survey), 1)

    def test_staff_survey_requires_real_staff_user_id_and_can_be_answered(self):
        redirect_response = self.client.get("/staff-surveys/", follow_redirects=False)
        self.assertEqual(redirect_response.status_code, 303)
        self.assertIn("/staff/login", redirect_response.headers["location"])

        self._login_staff()
        list_response = self.client.get("/staff-surveys/")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("職員アンケート", list_response.text)

        response = self.client.post(
            f"/staff-surveys/{self.staff_survey_id}",
            data={f"q{self.staff_question_id}": "true"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            answer = session.exec(select(SurveyAnswer).where(SurveyAnswer.survey_id == self.staff_survey_id)).first()
            response_row = session.exec(select(SurveyResponse).where(SurveyResponse.answer_id == answer.id)).first()

        self.assertIsNotNone(answer)
        self.assertEqual(answer.staff_user_id, self.staff_user_id)
        self.assertEqual(answer.created_by_staff_user_id, self.staff_user_id)
        self.assertTrue(response_row.value_bool)

    def test_staff_survey_answer_status_is_per_staff_user(self):
        self._login_staff(self.staff_user_id)
        response = self.client.post(
            f"/staff-surveys/{self.staff_survey_id}",
            data={f"q{self.staff_question_id}": "true"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        answered_list_response = self.client.get("/staff-surveys/")
        self.assertEqual(answered_list_response.status_code, 200)
        self.assertIn("職員アンケート", answered_list_response.text)
        self.assertIn("回答済み", answered_list_response.text)

        self._login_staff(self.late_staff_user_id)
        unanswered_list_response = self.client.get("/staff-surveys/")
        self.assertEqual(unanswered_list_response.status_code, 200)
        self.assertIn("職員アンケート", unanswered_list_response.text)
        self.assertIn("未回答", unanswered_list_response.text)

    def test_staff_survey_answer_detail_displays_staff_name(self):
        self._login_staff(self.staff_user_id)
        response = self.client.post(
            f"/staff-surveys/{self.staff_survey_id}",
            data={f"q{self.staff_question_id}": "true"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        detail_response = self.client.get(f"/surveys/{self.staff_survey_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("職員: 佐藤先生", detail_response.text)
        self.assertNotIn("職員ID", detail_response.text)
        self.assertNotIn(str(self.staff_user_id), detail_response.text)

    def test_staff_lists_deduplicate_logical_staff_users(self):
        login_response = self.client.get("/staff/login")
        self.assertEqual(login_response.status_code, 200)
        self.assertEqual(login_response.text.count("佐藤先生"), 1)

        form_response = self.client.get("/surveys/new")
        self.assertEqual(form_response.status_code, 200)
        self.assertEqual(form_response.text.count("佐藤先生"), 1)

    def test_management_form_uses_guided_delivery_target_picker(self):
        response = self.client.get("/surveys/new")

        self.assertEqual(response.status_code, 200)
        self.assertIn('id="delivery-step-audience"', response.text)
        self.assertIn('id="delivery-step-unit"', response.text)
        self.assertIn('id="delivery-step-scope"', response.text)
        self.assertIn('id="delivery-step-detail"', response.text)
        self.assertIn('id="delivery-summary"', response.text)
        self.assertIn("最初からやり直す", response.text)
        self.assertIn('data-parent-targets', response.text)
        self.assertIn('data-staff-targets', response.text)

    def test_parent_survey_can_be_created_for_selected_classroom(self):
        response = self.client.post(
            "/surveys/",
            data={
                "title": "ひよこ組アンケート",
                "audience_type": "parent",
                "answer_unit": "child",
                "target_type": "classroom",
                "target_classroom_id": str(self.classroom_id),
                "q1_label": "園で好きな遊び",
                "q1_type": "text_short",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            survey = session.exec(select(Survey).where(Survey.title == "ひよこ組アンケート")).first()
            target = session.exec(select(SurveyTarget).where(SurveyTarget.survey_id == survey.id)).first()
            unanswered_count = unanswered_parent_survey_count(session, survey)

        self.assertEqual(survey.audience_type, SurveyAudienceType.parent)
        self.assertEqual(survey.answer_unit, SurveyAnswerUnit.child)
        self.assertEqual(target.target_type, SurveyTargetType.classroom)
        self.assertEqual(target.target_value, str(self.classroom_id))
        self.assertEqual(unanswered_count, 1)

    def test_duplicate_staff_answer_counts_for_canonical_staff_user(self):
        self._login_staff(self.duplicate_staff_user_id)
        response = self.client.post(
            f"/staff-surveys/{self.staff_survey_id}",
            data={f"q{self.staff_question_id}": "true"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

        self._login_staff(self.staff_user_id)
        list_response = self.client.get("/staff-surveys/")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("職員アンケート", list_response.text)
        self.assertIn("回答済み", list_response.text)

    def test_duplicate_staff_can_open_survey_targeted_to_canonical_user(self):
        with Session(self.engine) as session:
            survey = Survey(
                title="佐藤先生だけのアンケート",
                status=SurveyStatus.published,
                audience_type=SurveyAudienceType.staff,
                answer_unit=SurveyAnswerUnit.staff_user,
            )
            session.add(survey)
            session.flush()
            session.add(
                SurveyTarget(
                    survey_id=survey.id,
                    target_type=SurveyTargetType.staff_user,
                    target_value=str(self.staff_user_id),
                )
            )
            session.add(
                SurveyQuestion(
                    survey_id=survey.id,
                    order=1,
                    question_type=QuestionType.yes_no,
                    label="確認しましたか",
                    is_required=True,
                )
            )
            session.commit()
            targeted_survey_id = survey.id

        self._login_staff(self.duplicate_staff_user_id)
        list_response = self.client.get("/staff-surveys/")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("佐藤先生だけのアンケート", list_response.text)

        detail_response = self.client.get(f"/staff-surveys/{targeted_survey_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("確認しましたか", detail_response.text)

    def test_staff_can_create_survey_from_management_form(self):
        response = self.client.post(
            "/surveys/",
            data={
                "title": "新しい職員アンケート",
                "description": "説明文",
                "status": "published",
                "audience_type": "staff",
                "answer_unit": "staff_user",
                "target_type": "all_staff",
                "q1_label": "満足度",
                "q1_type": "scale",
                "q1_required": "on",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            survey = session.exec(select(Survey).where(Survey.title == "新しい職員アンケート")).first()

        self.assertIsNotNone(survey)
        self.assertEqual(survey.audience_type, SurveyAudienceType.staff)
        self.assertEqual(survey.answer_unit, SurveyAnswerUnit.staff_user)

    def test_staff_audience_default_all_target_is_normalized_to_all_staff(self):
        response = self.client.post(
            "/surveys/",
            data={
                "title": "職員向けデフォルト対象",
                "status": "published",
                "audience_type": "staff",
                "answer_unit": "family",
                "target_type": "all",
                "q1_label": "共有事項はありますか",
                "q1_type": "text_short",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            survey = session.exec(select(Survey).where(Survey.title == "職員向けデフォルト対象")).first()
            target = session.exec(select(SurveyTarget).where(SurveyTarget.survey_id == survey.id)).first()

        self.assertIsNotNone(survey)
        self.assertEqual(survey.audience_type, SurveyAudienceType.staff)
        self.assertEqual(survey.answer_unit, SurveyAnswerUnit.staff_user)
        self.assertEqual(target.target_type, SurveyTargetType.all_staff)

        self._login_staff()
        list_response = self.client.get("/staff-surveys/")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("職員向けデフォルト対象", list_response.text)

    def test_legacy_staff_survey_with_all_target_is_visible_to_staff(self):
        with Session(self.engine) as session:
            survey = Survey(
                title="旧形式の職員アンケート",
                status=SurveyStatus.published,
                audience_type=SurveyAudienceType.staff,
                answer_unit=SurveyAnswerUnit.staff_user,
            )
            session.add(survey)
            session.flush()
            session.add(SurveyTarget(survey_id=survey.id, target_type=SurveyTargetType.all))
            session.add(
                SurveyQuestion(
                    survey_id=survey.id,
                    order=1,
                    question_type=QuestionType.text_short,
                    label="確認事項",
                )
            )
            session.commit()

        self._login_staff()
        list_response = self.client.get("/staff-surveys/")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("旧形式の職員アンケート", list_response.text)

    def test_all_staff_target_counts_loginable_staff_users(self):
        with Session(self.engine) as session:
            survey = session.get(Survey, self.staff_survey_id)
            eligible_users = eligible_staff_users_for_survey(session, survey)

        self.assertEqual(
            {user.id for user in eligible_users},
            {self.staff_user_id, self.late_staff_user_id},
        )

    def test_survey_open_start_uses_local_datetime_input(self):
        survey = Survey(
            title="公開時刻テスト",
            status=SurveyStatus.published,
            audience_type=SurveyAudienceType.staff,
            answer_unit=SurveyAnswerUnit.staff_user,
            opens_at=datetime(2026, 5, 18, 4, 23),
            closes_at=datetime(2026, 5, 18, 5, 23),
        )

        before_local_start = datetime(2026, 5, 17, 19, 0, tzinfo=timezone.utc)
        after_local_start = datetime(2026, 5, 17, 20, 0, tzinfo=timezone.utc)
        after_local_end = datetime(2026, 5, 17, 20, 24, tzinfo=timezone.utc)

        self.assertFalse(survey_is_open(survey, before_local_start))
        self.assertTrue(survey_is_open(survey, after_local_start))
        self.assertFalse(survey_is_open(survey, after_local_end))
        self.assertEqual(survey_effective_status_label(survey, before_local_start), "公開前")
        self.assertEqual(survey_effective_status_label(survey, after_local_start), "公開中")
        self.assertEqual(survey_effective_status_label(survey, after_local_end), "公開終了")

    def test_expired_published_survey_is_displayed_and_filtered_as_closed(self):
        with Session(self.engine) as session:
            survey = session.get(Survey, self.parent_survey_id)
            survey.opens_at = datetime(2020, 1, 1, 9, 0)
            survey.closes_at = datetime(2020, 1, 1, 10, 0)
            session.add(survey)
            session.commit()

        list_response = self.client.get("/surveys/")
        closed_filter_response = self.client.get("/surveys/?status=closed")
        published_filter_response = self.client.get("/surveys/?status=published")
        detail_response = self.client.get(f"/surveys/{self.parent_survey_id}")
        edit_response = self.client.get(f"/surveys/{self.parent_survey_id}/edit")

        self.assertIn("保護者アンケート", list_response.text)
        self.assertIn("公開終了", list_response.text)
        self.assertIn("保護者アンケート", closed_filter_response.text)
        self.assertNotIn("保護者アンケート", published_filter_response.text)
        self.assertIn("公開終了", detail_response.text)
        self.assertIn('value="closed" selected', edit_response.text)

    def test_survey_form_normalizes_offset_datetime_to_jst(self):
        response = self.client.post(
            "/surveys/",
            data={
                "title": "JST公開期間テスト",
                "status": "published",
                "audience_type": "staff",
                "answer_unit": "staff_user",
                "target_type": "all_staff",
                "opens_at": "2026-07-26T00:00:00+00:00",
                "closes_at": "2026-07-26T01:00:00+00:00",
                "q1_label": "確認しましたか",
                "q1_type": "yes_no",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            survey = session.exec(select(Survey).where(Survey.title == "JST公開期間テスト")).first()

        self.assertEqual(survey.opens_at, datetime(2026, 7, 26, 9, 0))
        self.assertEqual(survey.closes_at, datetime(2026, 7, 26, 10, 0))
        self.assertFalse(survey_is_open(survey, datetime(2026, 7, 25, 23, 59, tzinfo=timezone.utc)))
        self.assertTrue(survey_is_open(survey, datetime(2026, 7, 26, 0, 30, tzinfo=timezone.utc)))
        self.assertFalse(survey_is_open(survey, datetime(2026, 7, 26, 1, 1, tzinfo=timezone.utc)))


if __name__ == "__main__":
    unittest.main()
