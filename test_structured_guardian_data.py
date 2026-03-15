import unittest
from datetime import date

from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from child_profile_changes import build_child_profile_payload
from family_support import apply_family_shared_data
from models import Child, ChildStatus, Family


class StructuredGuardianDataTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def test_build_child_profile_payload_returns_structured_child_and_guardians(self):
        payload = build_child_profile_payload(
            last_name="田中",
            first_name="さくら",
            last_name_kana="タナカ",
            first_name_kana="サクラ",
            birth_date="2021-04-05",
            enrollment_date="2024-04-01",
            withdrawal_date="",
            status="enrolled",
            home_address="東京都渋谷区1-2-3",
            home_phone="03-1111-1111",
            allergy="卵、乳",
            medical_notes="エピペン携帯",
            g1_last_name="田中",
            g1_first_name="花子",
            g1_last_name_kana="タナカ",
            g1_first_name_kana="ハナコ",
            g1_relationship="母",
            g1_phone="090-1111-2222",
            g1_workplace="株式会社A",
            g1_workplace_address="東京都港区",
            g1_workplace_phone="03-2222-3333",
            g2_last_name="",
            g2_first_name="",
            g2_last_name_kana="",
            g2_first_name_kana="",
            g2_relationship="父",
            g2_phone="",
            g2_workplace="",
            g2_workplace_address="",
            g2_workplace_phone="",
        )

        self.assertEqual(
            payload,
            {
                "child_data": {
                    "last_name": "田中",
                    "first_name": "さくら",
                    "last_name_kana": "タナカ",
                    "first_name_kana": "サクラ",
                    "birth_date": "2021-04-05",
                    "enrollment_date": "2024-04-01",
                    "withdrawal_date": "",
                    "status": "enrolled",
                    "allergy": "卵,乳",
                    "medical_notes": "エピペン携帯",
                },
                "home_address": "東京都渋谷区1-2-3",
                "home_phone": "03-1111-1111",
                "guardians_data": [
                    {
                        "order": 1,
                        "last_name": "田中",
                        "first_name": "花子",
                        "last_name_kana": "タナカ",
                        "first_name_kana": "ハナコ",
                        "relationship": "母",
                        "phone": "090-1111-2222",
                        "workplace": "株式会社A",
                        "workplace_address": "東京都港区",
                        "workplace_phone": "03-2222-3333",
                    }
                ],
            },
        )

    def test_apply_family_shared_data_persists_multiple_guardians(self):
        with Session(self.engine) as session:
            family = Family(family_name="田中家")
            session.add(family)
            session.flush()

            child = Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2021, 4, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                family_id=family.id,
            )
            session.add(child)
            session.flush()
            child_id = child.id
            family_id = family.id

            apply_family_shared_data(
                session,
                family,
                {
                    "family_name": "田中家",
                    "home_address": "東京都渋谷区1-2-3",
                    "home_phone": "03-1111-1111",
                    "guardians_data": [
                        {
                            "last_name": "田中",
                            "first_name": "花子",
                            "relationship": "母",
                            "phone": "090-1111-2222",
                        },
                        {
                            "last_name": "田中",
                            "first_name": "健一",
                            "relationship": "父",
                            "phone": "090-3333-4444",
                        },
                        {
                            "last_name": "田中",
                            "first_name": "和子",
                            "relationship": "祖母",
                            "phone": "090-5555-6666",
                        },
                    ],
                },
            )
            session.commit()

        with Session(self.engine) as session:
            family = session.get(Family, family_id)
            child = session.exec(
                select(Child).options(selectinload(Child.guardians)).where(Child.id == child_id)
            ).first()

        self.assertIsNotNone(family)
        self.assertEqual(len(family.shared_profile["guardians"]), 3)
        self.assertEqual([guardian.order for guardian in child.guardians], [1, 2, 3])
        self.assertEqual(child.guardians[2].first_name, "和子")
        self.assertEqual(child.guardians[2].relationship, "祖母")


if __name__ == "__main__":
    unittest.main()
