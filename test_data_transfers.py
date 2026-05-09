import csv
import io
import unittest
from datetime import date

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

import routers.data_transfers as data_transfers_module
from models import Child, ChildStatus, Classroom, DataTransferLog, Family, ParentAccount


def _csv_bytes(rows):
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\r\n")
    writer.writerows(rows)
    return buffer.getvalue().encode("utf-8-sig")


class DataTransferTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(data_transfers_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[data_transfers_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            classroom = Classroom(name="ひよこ組", display_order=1)
            family = Family(family_name="田中家", home_phone="03-1111-1111")
            session.add(classroom)
            session.add(family)
            session.flush()
            child = Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2021, 4, 5),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.graduated,
                classroom_id=classroom.id,
                family_id=family.id,
                extra_data={"allergy": [], "medical_notes": ""},
            )
            session.add(child)
            session.commit()
            self.classroom_id = classroom.id
            self.family_id = family.id
            self.child_id = child.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_exports_children_as_csv(self):
        response = self.client.get("/data-transfers/export/children.csv")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "text/csv; charset=utf-8")
        text = response.content.decode("utf-8-sig")
        self.assertIn("姓,名,姓カナ", text)
        self.assertIn("田中,さくら,タナカ", text)
        self.assertIn("卒園", text)

    def test_data_transfer_page_has_dataset_visibility_controls(self):
        response = self.client.get("/data-transfers/")

        self.assertEqual(response.status_code, 200)
        self.assertIn("表示するデータ", response.text)
        self.assertIn('data-dataset-toggle', response.text)
        self.assertIn('data-dataset-row="families"', response.text)

    def test_import_new_child_defaults_blank_status_to_enrolled(self):
        rows = [
            ["ID", "姓", "名", "姓カナ", "名カナ", "生年月日", "入園日", "退園日", "在園状態", "クラス名", "家庭ID", "家庭名", "住所", "電話番号"],
            ["", "佐藤", "みお", "サトウ", "ミオ", "2022-05-06", "2025-04-01", "", "", "ひよこ組", str(self.family_id), "田中家", "", ""],
        ]
        response = self.client.post(
            "/data-transfers/import/children/commit",
            files={"file": ("children.csv", _csv_bytes(rows), "text/csv")},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            child = session.exec(select(Child).where(Child.last_name_kana == "サトウ")).first()
            log = session.exec(select(DataTransferLog)).first()

        self.assertIsNotNone(child)
        self.assertEqual(child.status, ChildStatus.enrolled)
        self.assertEqual(child.family_id, self.family_id)
        self.assertIsNotNone(log)
        self.assertEqual(log.result, "success")
        self.assertEqual(log.created_count, 1)

    def test_import_existing_child_keeps_status_when_blank(self):
        rows = [
            ["ID", "姓", "名", "姓カナ", "名カナ", "生年月日", "入園日", "退園日", "在園状態", "クラス名", "家庭ID", "家庭名", "住所", "電話番号"],
            [str(self.child_id), "田中", "さくら", "タナカ", "サクラ", "2021-04-05", "2024-04-01", "", "", "ひよこ組", str(self.family_id), "田中家", "東京都", ""],
        ]
        response = self.client.post(
            "/data-transfers/import/children/commit",
            files={"file": ("children.csv", _csv_bytes(rows), "text/csv")},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)

        self.assertEqual(child.status, ChildStatus.graduated)
        self.assertEqual(child.home_address, "東京都")

    def test_family_id_and_name_conflict_is_validation_error(self):
        with Session(self.engine) as session:
            other = Family(family_name="佐藤家", home_phone="03-2222-2222")
            session.add(other)
            session.commit()

        rows = [
            ["ID", "姓", "名", "姓カナ", "名カナ", "生年月日", "入園日", "退園日", "在園状態", "クラス名", "家庭ID", "家庭名", "住所", "電話番号"],
            ["", "山田", "あおい", "ヤマダ", "アオイ", "2022-01-01", "2025-04-01", "", "在園", "ひよこ組", str(self.family_id), "佐藤家", "", ""],
        ]
        response = self.client.post(
            "/data-transfers/import/children/preview",
            files={"file": ("children.csv", _csv_bytes(rows), "text/csv")},
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("家庭IDの家庭名と一致しません", response.text)


if __name__ == "__main__":
    unittest.main()
