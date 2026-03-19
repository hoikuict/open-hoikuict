import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from database import bootstrap_family_records, seed_classroom_data, seed_parent_portal_data, seed_sample_data
from models import Child, Family
import routers.children as children_module


class ChildCreateTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        seed_classroom_data(self.engine)
        seed_sample_data(self.engine)
        bootstrap_family_records(self.engine)
        seed_parent_portal_data(self.engine)

        self.app = FastAPI()
        self.app.include_router(children_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[children_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            family = session.exec(select(Family).order_by(Family.id)).first()
            self.assertIsNotNone(family)
            self.family_id = family.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_can_create_child_in_existing_family_without_deleted_guardian_error(self):
        with Session(self.engine) as session:
            before = session.exec(select(Child).where(Child.family_id == self.family_id)).all()
            before_count = len(before)

        response = self.client.post(
            "/children/",
            data={
                "last_name": "追加",
                "first_name": "太郎",
                "last_name_kana": "ツイカ",
                "first_name_kana": "タロウ",
                "birth_date": "2021-01-01",
                "enrollment_date": "2024-04-01",
                "withdrawal_date": "",
                "status": "enrolled",
                "classroom_id": "",
                "allergy": "",
                "medical_notes": "",
                "family_selection": str(self.family_id),
                "family_name": "更新家族",
                "home_address": "東京",
                "home_phone": "03-0000-0000",
                "g1_last_name": "田中",
                "g1_first_name": "花子",
                "g1_last_name_kana": "タナカ",
                "g1_first_name_kana": "ハナコ",
                "g1_relationship": "母",
                "g1_phone": "090",
                "g1_workplace": "",
                "g1_workplace_address": "",
                "g1_workplace_phone": "",
                "g2_last_name": "田中",
                "g2_first_name": "健一",
                "g2_last_name_kana": "タナカ",
                "g2_first_name_kana": "ケンイチ",
                "g2_relationship": "父",
                "g2_phone": "080",
                "g2_workplace": "",
                "g2_workplace_address": "",
                "g2_workplace_phone": "",
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            after = session.exec(select(Child).where(Child.family_id == self.family_id)).all()

        self.assertEqual(len(after), before_count + 1)
        self.assertTrue(any(child.last_name == "追加" and child.first_name == "太郎" for child in after))


if __name__ == "__main__":
    unittest.main()
