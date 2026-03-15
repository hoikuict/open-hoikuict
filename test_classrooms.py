import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from models import Child, ChildStatus, Classroom, Family
import routers.children as children_module
import routers.classrooms as classrooms_module


class ClassroomManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(classrooms_module.router)
        self.app.include_router(children_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[classrooms_module.get_session] = override_get_session
        self.app.dependency_overrides[children_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            family = Family(family_name="田中家")
            session.add(family)
            session.flush()

            hiyoko = Classroom(name="ひよこ組", display_order=1)
            usagi = Classroom(name="うさぎ組", display_order=2)
            session.add(hiyoko)
            session.add(usagi)
            session.flush()

            child = Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2021, 4, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=hiyoko.id,
                family_id=family.id,
                extra_data={"allergy": [], "medical_notes": ""},
            )
            session.add(child)
            session.flush()

            self.family_id = family.id
            self.child_id = child.id
            self.hiyoko_id = hiyoko.id
            self.usagi_id = usagi.id
            session.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_staff_can_create_and_edit_classroom(self):
        create_response = self.client.post(
            "/classrooms/",
            data={"name": "うさぎ2組", "display_order": "2"},
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        with Session(self.engine) as session:
            classroom = session.exec(select(Classroom).where(Classroom.name == "うさぎ2組")).first()

        self.assertIsNotNone(classroom)

        update_response = self.client.post(
            f"/classrooms/{classroom.id}/edit",
            data={"name": "うさぎ青組", "display_order": "3"},
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 303)

        with Session(self.engine) as session:
            updated = session.get(Classroom, classroom.id)

        self.assertEqual(updated.name, "うさぎ青組")
        self.assertEqual(updated.display_order, 3)

    def test_child_edit_form_can_change_classroom_from_list(self):
        form_response = self.client.get(f"/children/{self.child_id}/edit")

        self.assertEqual(form_response.status_code, 200)
        self.assertIn('name="classroom_id"', form_response.text)
        self.assertIn("ひよこ組", form_response.text)
        self.assertIn("うさぎ組", form_response.text)

        update_response = self.client.post(
            f"/children/{self.child_id}/edit",
            data={
                "last_name": "田中",
                "first_name": "さくら",
                "last_name_kana": "タナカ",
                "first_name_kana": "サクラ",
                "birth_date": "2021-04-05",
                "enrollment_date": "2024-04-01",
                "withdrawal_date": "",
                "status": "enrolled",
                "classroom_id": str(self.usagi_id),
                "allergy": "",
                "medical_notes": "",
                "family_selection": str(self.family_id),
                "family_name": "田中家",
                "home_address": "",
                "home_phone": "",
                "g1_last_name": "",
                "g1_first_name": "",
                "g1_last_name_kana": "",
                "g1_first_name_kana": "",
                "g1_relationship": "母",
                "g1_phone": "",
                "g1_workplace": "",
                "g1_workplace_address": "",
                "g1_workplace_phone": "",
                "g2_last_name": "",
                "g2_first_name": "",
                "g2_last_name_kana": "",
                "g2_first_name_kana": "",
                "g2_relationship": "父",
                "g2_phone": "",
                "g2_workplace": "",
                "g2_workplace_address": "",
                "g2_workplace_phone": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 303)

        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)

        self.assertEqual(child.classroom_id, self.usagi_id)


if __name__ == "__main__":
    unittest.main()
