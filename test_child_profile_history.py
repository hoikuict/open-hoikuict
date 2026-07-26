import unittest
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from models import (
    Child,
    ChildProfileChangeRequest,
    ChildProfileChangeRequestStatus,
    ChildProfileHistory,
    ChildStatus,
    Classroom,
    Family,
    ParentAccount,
    ParentAccountStatus,
)
from child_profile_history import record_child_profile_history
import routers.children as children_module
from testing_helpers import authenticate_mock_staff


class ChildProfileHistoryTests(unittest.TestCase):
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
        authenticate_mock_staff(
            self.client,
            name="履歴担当者",
            can_manage_child_records=True,
        )

        with Session(self.engine) as session:
            classroom = Classroom(name="ぞう組", display_order=1)
            family = Family(
                family_name="青木家",
                home_address="旧住所",
                home_phone="03-1111-1111",
                shared_profile={
                    "guardians": [
                        {
                            "order": 1,
                            "last_name": "青木",
                            "first_name": "保護者",
                            "relationship": "母",
                            "phone": "090-1111-1111",
                        }
                    ]
                },
            )
            session.add(classroom)
            session.add(family)
            session.flush()
            child = Child(
                last_name="青木",
                first_name="朝陽",
                last_name_kana="アオキ",
                first_name_kana="アサヒ",
                birth_date=date(2020, 10, 24),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family.id,
                home_address=family.home_address,
                home_phone=family.home_phone,
                extra_data={"allergy": ["小麦", "卵"], "medical_notes": ""},
            )
            session.add(child)
            session.commit()
            session.refresh(child)
            self.child_id = child.id
            self.family_id = family.id
            self.classroom_id = classroom.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_update_records_actor_snapshot_and_highlighted_changes(self):
        response = self.client.post(
            f"/children/{self.child_id}/edit",
            data={
                "last_name": "青木",
                "first_name": "朝陽",
                "last_name_kana": "アオキ",
                "first_name_kana": "アサヒ",
                "birth_date": "2020-10-24",
                "enrollment_date": "2024-04-01",
                "withdrawal_date": "",
                "status": "enrolled",
                "classroom_id": str(self.classroom_id),
                "allergy": "小麦,卵",
                "medical_notes": "定期薬あり",
                "family_selection": str(self.family_id),
                "family_name": "青木家",
                "home_address": "新住所",
                "home_phone": "03-1111-1111",
                "g1_last_name": "青木",
                "g1_first_name": "保護者",
                "g1_last_name_kana": "",
                "g1_first_name_kana": "",
                "g1_relationship": "母",
                "g1_phone": "090-2222-2222",
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
        self.assertEqual(response.status_code, 303)

        with Session(self.engine) as session:
            histories = session.exec(
                select(ChildProfileHistory)
                .where(ChildProfileHistory.child_id == self.child_id)
                .order_by(ChildProfileHistory.recorded_at, ChildProfileHistory.id)
            ).all()

        self.assertEqual([item.action for item in histories], ["created", "updated"])
        self.assertEqual(histories[1].actor_name, "履歴担当者")
        self.assertEqual(histories[1].snapshot["home_address"], "新住所")
        self.assertEqual(histories[1].snapshot["medical_notes"], "定期薬あり")
        self.assertEqual(histories[1].snapshot["g1_phone"], "090-2222-2222")
        self.assertEqual(histories[1].changes["home_address"]["old"], "旧住所")
        self.assertIn("medical_notes", histories[1].changes)
        self.assertIn("g1_phone", histories[1].changes)

        list_response = self.client.get(f"/children/{self.child_id}/history")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("新規登録", list_response.text)
        self.assertIn("履歴担当者", list_response.text)
        self.assertIn("自宅住所", list_response.text)

        detail_response = self.client.get(
            f"/children/{self.child_id}/history/{histories[1].id}"
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("黄色の項目", detail_response.text)
        self.assertIn("変更前: 旧住所", detail_response.text)
        self.assertIn("新住所", detail_response.text)
        self.assertIn("定期薬あり", detail_response.text)

    def test_parent_request_history_shows_requester_and_approver_separately(self):
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            child.extra_data = {"allergy": ["小麦", "卵"], "medical_notes": "保護者申請で更新"}
            session.add(child)
            history = record_child_profile_history(
                session,
                child,
                actor_name="主任",
                previous_snapshot={},
                source="parent_request",
                requester_name="青木 真由美",
            )
            session.commit()
            history_id = history.id

        list_response = self.client.get(f"/children/{self.child_id}/history")
        self.assertEqual(list_response.status_code, 200)
        self.assertIn("保護者申請", list_response.text)
        self.assertIn("申請者: 青木 真由美", list_response.text)
        self.assertIn("承認: 主任", list_response.text)

        detail_response = self.client.get(
            f"/children/{self.child_id}/history/{history_id}"
        )
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("申請者: 青木 真由美", detail_response.text)
        self.assertIn("承認: 主任", detail_response.text)

    def test_existing_approval_history_is_backfilled_as_parent_request(self):
        with Session(self.engine) as session:
            parent = ParentAccount(
                display_name="青木 真由美",
                email="aoki@example.com",
                status=ParentAccountStatus.active,
                family_id=self.family_id,
            )
            session.add(parent)
            session.flush()
            session.add(
                ChildProfileHistory(
                    child_id=self.child_id,
                    action="updated",
                    actor_name="主任",
                    snapshot={"medical_notes": "申請後"},
                    changes={"medical_notes": {"old": "申請前", "new": "申請後"}},
                    recorded_at=datetime(2026, 7, 26, 8, 9),
                )
            )
            session.add(
                ChildProfileChangeRequest(
                    child_id=self.child_id,
                    parent_account_id=parent.id,
                    status=ChildProfileChangeRequestStatus.approved,
                    change_summary="医療メモの更新",
                    request_data={"medical_notes": "申請後"},
                    change_details={
                        "medical_notes": {
                            "label": "医療メモ",
                            "old": "申請前",
                            "new": "申請後",
                        }
                    },
                    reviewed_by="主任",
                    reviewed_at=datetime(2026, 7, 25, 23, 9),
                )
            )
            session.commit()

        response = self.client.get(f"/children/{self.child_id}/history")
        self.assertEqual(response.status_code, 200)
        self.assertIn("保護者申請", response.text)
        self.assertIn("申請者: 青木 真由美", response.text)
        self.assertIn("承認: 主任", response.text)


if __name__ == "__main__":
    unittest.main()
