import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from models import Child, ChildStatus, Classroom, Family, ParentAccount, ParentAccountStatus
import routers.families as families_module


class FamilyManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(families_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[families_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(classroom)
            session.flush()

            family_a = Family(family_name="田中家", home_address="Old Address", home_phone="03-1111-1111")
            family_b = Family(family_name="佐藤家", home_address="Other Address", home_phone="03-2222-2222")
            session.add(family_a)
            session.add(family_b)
            session.flush()
            self.family_id = family_a.id

            child_a = Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2021, 5, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family_a.id,
                home_address="Old Address",
                home_phone="03-1111-1111",
            )
            child_b = Child(
                last_name="佐藤",
                first_name="みお",
                last_name_kana="サトウ",
                first_name_kana="ミオ",
                birth_date=date(2021, 6, 6),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family_b.id,
                home_address="Other Address",
                home_phone="03-2222-2222",
            )
            session.add(child_a)
            session.add(child_b)
            session.flush()
            self.child_a_id = child_a.id
            self.child_b_id = child_b.id

            account = ParentAccount(
                display_name="田中 真由美",
                email="tanaka@example.com",
                status=ParentAccountStatus.active,
            )
            session.add(account)
            session.flush()
            self.account_id = account.id
            session.commit()

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_edit_family_updates_membership_and_shared_profile(self):
        response = self.client.post(
            f"/families/{self.family_id}/edit",
            data={
                "family_name": "田中家",
                "home_address": "New Shared Address",
                "home_phone": "03-9999-9999",
                "child_ids": [str(self.child_a_id), str(self.child_b_id)],
                "parent_account_ids": [str(self.account_id)],
                "g1_last_name": "田中",
                "g1_first_name": "真由美",
                "g1_last_name_kana": "タナカ",
                "g1_first_name_kana": "マユミ",
                "g1_relationship": "母",
                "g1_phone": "090-1111-2222",
                "g1_workplace": "新しい勤務先",
                "g1_workplace_address": "東京都港区3-3-3",
                "g1_workplace_phone": "03-3333-3333",
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
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            family = session.get(Family, self.family_id)
            children = session.exec(select(Child).where(Child.id.in_([self.child_a_id, self.child_b_id]))).all()
            account = session.get(ParentAccount, self.account_id)

        self.assertEqual(account.family_id, self.family_id)
        self.assertEqual({child.family_id for child in children}, {self.family_id})
        self.assertEqual({child.home_address for child in children}, {"New Shared Address"})
        self.assertEqual(family.home_phone, "03-9999-9999")


if __name__ == "__main__":
    unittest.main()
