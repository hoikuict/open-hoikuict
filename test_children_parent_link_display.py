import unittest
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from models import Child, ChildStatus, Classroom, Family, ParentAccount, ParentAccountStatus
import routers.children as children_module


class ChildrenParentLinkDisplayTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(children_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[children_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.flush()

            family = Family(
                family_name="田中家",
                home_address="東京都港区1-1-1",
                home_phone="03-1111-1111",
                shared_profile={
                    "guardians": [
                        {
                            "order": 1,
                            "last_name": "田中",
                            "first_name": "健一",
                            "relationship": "父",
                        },
                        {
                            "order": 2,
                            "last_name": "田中",
                            "first_name": "真由美",
                            "relationship": "母",
                        },
                    ]
                },
            )
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
                display_name="別名アカウント",
                email="guardian@example.com",
                status=ParentAccountStatus.active,
                family_id=family.id,
                invited_at=datetime.utcnow(),
            )
            session.add(parent)
            session.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_children_list_shows_guardians_from_family_profile(self):
        response = self.client.get("/children/?fields=family_name&fields=guardians")

        self.assertEqual(response.status_code, 200)
        self.assertIn("田中家", response.text)
        self.assertIn("田中 健一（父）", response.text)
        self.assertIn("田中 真由美（母）", response.text)
        self.assertNotIn("別名アカウント", response.text)


if __name__ == "__main__":
    unittest.main()
