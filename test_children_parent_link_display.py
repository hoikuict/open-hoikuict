import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine

from models import Child, ChildStatus, Classroom, Family, ParentAccount, ParentAccountStatus
from time_utils import utc_now
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
            classroom = Classroom(name="Class A", display_order=1)
            session.add(classroom)
            session.flush()

            family = Family(
                family_name="Tanaka Family",
                home_address="Tokyo 1-1-1",
                home_phone="03-1111-1111",
                shared_profile={
                    "guardians": [
                        {
                            "order": 1,
                            "last_name": "Tanaka",
                            "first_name": "Hanako",
                            "relationship": "母",
                        },
                        {
                            "order": 2,
                            "last_name": "Tanaka",
                            "first_name": "Kenichi",
                            "relationship": "父",
                        },
                    ]
                },
            )
            session.add(family)
            session.flush()

            child = Child(
                last_name="Tanaka",
                first_name="Sakura",
                last_name_kana="TANAKA",
                first_name_kana="SAKURA",
                birth_date=date(2021, 5, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family.id,
            )
            sibling = Child(
                last_name="Tanaka",
                first_name="Haru",
                last_name_kana="TANAKA",
                first_name_kana="HARU",
                birth_date=date(2020, 6, 6),
                enrollment_date=date(2023, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family.id,
            )
            session.add(child)
            session.add(sibling)
            session.flush()
            self.child_id = child.id
            self.sibling_id = sibling.id

            parent = ParentAccount(
                display_name="Portal Account Name",
                email="guardian@example.com",
                status=ParentAccountStatus.active,
                family_id=family.id,
                invited_at=utc_now(),
            )
            session.add(parent)
            session.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_children_list_shows_guardians_from_family_profile(self):
        response = self.client.get("/children/?fields=family_name&fields=guardians")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Tanaka Family", response.text)
        self.assertIn("Tanaka Hanako", response.text)
        self.assertIn("Tanaka Kenichi", response.text)
        self.assertNotIn("Portal Account Name", response.text)

    def test_view_only_user_sees_detail_link_and_family_overview(self):
        response = self.client.get("/children/?fields=family_name&fields=guardians&as=view_only")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'/children/{self.child_id}', response.text)
        self.assertIn("詳細", response.text)
        self.assertNotIn(f"/children/{self.child_id}/edit", response.text)

        detail_response = self.client.get(f"/children/{self.child_id}?as=view_only")

        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("家族一覧", detail_response.text)
        self.assertIn("Portal Account Name", detail_response.text)
        self.assertIn(f'/children/{self.sibling_id}', detail_response.text)

    def test_sibling_add_link_opens_new_child_form(self):
        response = self.client.get(f"/children/new?sibling_id={self.child_id}")

        self.assertEqual(response.status_code, 200)
        self.assertIn(f'name="older_sibling_id" value="{self.child_id}"', response.text)
        self.assertIn("Tanaka Family", response.text)


if __name__ == "__main__":
    unittest.main()
