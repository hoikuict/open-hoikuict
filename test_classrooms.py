import re
import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
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
        self.child_record_user = StaffUser(
            role=Role.CAN_EDIT,
            name="台帳担当",
            can_manage_child_records=True,
        )

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[classrooms_module.get_session] = override_get_session
        self.app.dependency_overrides[children_module.get_session] = override_get_session
        self.app.dependency_overrides[children_module.get_current_staff_user] = lambda: self.child_record_user
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

    def _add_child(self, session, *, classroom_id, status):
        child = Child(
            last_name="検証",
            first_name="園児",
            last_name_kana="ケンショウ",
            first_name_kana="エンジ",
            birth_date=date(2021, 4, 5),
            enrollment_date=date(2024, 4, 1),
            status=status,
            classroom_id=classroom_id,
            family_id=self.family_id,
        )
        session.add(child)
        return child

    def _assert_classroom_counts(self, response, expected):
        self.assertEqual(response.status_code, 200)
        for name, count in expected.items():
            self.assertIsNotNone(
                re.search(rf">{re.escape(name)}</td>\s*<td[^>]*>{count}人</td>", response.text),
                f"{name} の表示人数が {count} 人と一致しません。",
            )

    def test_classroom_counts_match_approved_mock_and_enrolled_children_list(self):
        samples = [
            ("きいちご", 6, 1),
            ("どんぐり", 15, 1),
            ("くるみ", 20, 0),
            ("うめ", 20, 0),
            ("たけ", 17, 0),
            ("まつ", 19, 0),
        ]
        with Session(self.engine) as session:
            for order, (name, enrolled, withdrawn) in enumerate(samples, start=1):
                if order <= 2:
                    classroom = session.get(Classroom, self.hiyoko_id if order == 1 else self.usagi_id)
                    classroom.name = name
                else:
                    classroom = Classroom(name=name, display_order=order)
                session.add(classroom)
                session.flush()
                for _ in range(enrolled - (1 if order == 1 else 0)):
                    self._add_child(session, classroom_id=classroom.id, status=ChildStatus.enrolled)
                for _ in range(withdrawn):
                    self._add_child(session, classroom_id=classroom.id, status=ChildStatus.withdrawn)
            session.commit()
            before = session.exec(select(Child.id, Child.status, Child.classroom_id).order_by(Child.id)).all()

        self._assert_classroom_counts(
            self.client.get("/classrooms/"),
            {name: enrolled for name, enrolled, _ in samples},
        )
        for status, expected in (("enrolled", 97), ("all", 99), ("withdrawn", 2)):
            response = self.client.get("/children/", params={"status": status})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.context["total"], expected)
        with Session(self.engine) as session:
            after = session.exec(select(Child.id, Child.status, Child.classroom_id).order_by(Child.id)).all()
        self.assertEqual(after, before)

    def test_zero_enrolled_and_empty_classes_remain_visible(self):
        with Session(self.engine) as session:
            for status in (ChildStatus.withdrawn, ChildStatus.graduated):
                self._add_child(session, classroom_id=self.usagi_id, status=status)
            self._add_child(session, classroom_id=None, status=ChildStatus.enrolled)
            session.add(Classroom(name="新設クラス", display_order=3))
            session.commit()

        self._assert_classroom_counts(
            self.client.get("/classrooms/"),
            {"ひよこ組": 1, "うさぎ組": 0, "新設クラス": 0},
        )
        self.assertEqual(self.client.get("/children/").context["total"], 2)
        self.assertEqual(self.client.get("/children/?status=graduated").context["total"], 1)
        with Session(self.engine) as session:
            classroom = session.get(Classroom, self.usagi_id)
            self.assertEqual(len(classroom.children), 2)

    def test_classroom_count_refreshes_after_status_edit(self):
        for status, count in (("withdrawn", 0), ("graduated", 0), ("enrolled", 1)):
            with self.subTest(status=status):
                response = self.client.post(
                    f"/children/{self.child_id}/edit",
                    data={
                        "last_name": "田中", "first_name": "さくら",
                        "last_name_kana": "タナカ", "first_name_kana": "サクラ",
                        "birth_date": "2021-04-05", "enrollment_date": "2024-04-01",
                        "status": status, "classroom_id": str(self.hiyoko_id),
                        "family_selection": str(self.family_id),
                    },
                    follow_redirects=False,
                )
                self.assertEqual(response.status_code, 303)
                self._assert_classroom_counts(
                    self.client.get("/classrooms/"), {"ひよこ組": count, "うさぎ組": 0},
                )
                self.assertEqual(self.client.get("/children/").context["total"], count)
                with Session(self.engine) as session:
                    child = session.get(Child, self.child_id)
                    self.assertEqual(child.classroom_id, self.hiyoko_id)
                    self.assertEqual(child.status.value, status)

    def test_classroom_counts_use_status_rather_than_enrollment_dates(self):
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            child.enrollment_date = date(2099, 4, 1)
            child.withdrawal_date = date(2099, 5, 1)
            session.add(child)
            session.commit()

        self._assert_classroom_counts(
            self.client.get("/classrooms/"), {"ひよこ組": 1, "うさぎ組": 0},
        )
        self.assertEqual(self.client.get("/children/").context["total"], 1)

    def test_classroom_list_without_classes(self):
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            child.classroom_id = None
            session.add(child)
            session.flush()
            for classroom in session.exec(select(Classroom)).all():
                session.delete(classroom)
            session.commit()

        response = self.client.get("/classrooms/")
        self.assertEqual(response.status_code, 200)
        self.assertIn("クラスがまだ登録されていません。", response.text)

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
