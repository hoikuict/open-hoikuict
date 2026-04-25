import unittest
from datetime import date

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
from time_utils import utc_now
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
            session.add(parent)
            session.add(staff)
            session.flush()
            self.parent_account_id = parent.id
            self.family_id = family.id
            self.staff_user_id = staff.id

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

    def _login_staff(self):
        response = self.client.post(
            "/staff/login",
            data={"user_id": str(self.staff_user_id), "redirect_to": "/staff-surveys/"},
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

        self.assertEqual(len(answers), 1)
        self.assertEqual(answers[0].family_id, self.family_id)
        self.assertEqual(responses[0].value_text, "遠足")

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


if __name__ == "__main__":
    unittest.main()
