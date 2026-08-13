import csv
import unittest

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine, select

from models import Classroom, Message, MessageAttachment
from scripts.seed_demo_100 import (
    BASE_DIR,
    build_family_guardian_profiles,
    load_rows,
    validate_name_duplicates,
    wipe_all,
)


class DemoSeedNameTests(unittest.TestCase):
    def test_family_profiles_use_current_guardian_names(self):
        profiles_by_family = build_family_guardian_profiles()

        self.assertEqual(profiles_by_family[61][0]["first_name"], "由美")
        self.assertEqual(profiles_by_family[61][0]["first_name_kana"], "ユミ")
        self.assertEqual(len(profiles_by_family[61]), 2)

    def test_wipe_all_removes_dependent_tables_without_foreign_key_violations(self):
        test_engine = create_engine("sqlite://")
        SQLModel.metadata.create_all(test_engine)
        with Session(test_engine) as session:
            session.exec(
                text(
                    "CREATE TABLE legacy_demo_rows ("
                    "id INTEGER PRIMARY KEY, classroom_id INTEGER, "
                    "FOREIGN KEY(classroom_id) REFERENCES classrooms(id))"
                )
            )
            session.add(Classroom(id=1, name="テスト", display_order=1))
            session.add(Message(id=1, room_id=1, author_name="テスト"))
            session.add(
                MessageAttachment(
                    id=1,
                    message_id=1,
                    original_filename="test.txt",
                    storage_path="test.txt",
                )
            )
            session.commit()
            session.exec(
                text("INSERT INTO legacy_demo_rows (id, classroom_id) VALUES (1, 1)")
            )
            session.commit()

            wipe_all(session)

            self.assertEqual(session.exec(select(MessageAttachment)).all(), [])
            self.assertEqual(session.exec(select(Message)).all(), [])
            self.assertEqual(
                session.exec(text("SELECT * FROM legacy_demo_rows")).all(), []
            )
            self.assertEqual(
                session.exec(text("PRAGMA foreign_key_check")).all(), []
            )
        test_engine.dispose()

    def test_bundled_people_have_at_most_two_duplicate_name_groups(self):
        for table in ("children", "parent_accounts"):
            with self.subTest(table=table):
                validate_name_duplicates(table, load_rows(table))

    def test_full_and_import_compatible_names_stay_in_sync(self):
        import_dir = BASE_DIR / "demo_data" / "import_compatible"
        with (import_dir / "children.csv").open(
            encoding="utf-8-sig", newline=""
        ) as file:
            imported_children = list(csv.DictReader(file))
        with (import_dir / "parent_accounts.csv").open(
            encoding="utf-8-sig", newline=""
        ) as file:
            imported_parents = list(csv.DictReader(file))

        full_children = load_rows("children")
        full_parents = load_rows("parent_accounts")
        self.assertEqual(
            [(row["last_name"], row["first_name"]) for row in full_children],
            [(row["姓"], row["名"]) for row in imported_children],
        )
        self.assertEqual(
            {row["email"]: row["display_name"] for row in full_parents},
            {row["メールアドレス"]: row["表示名"] for row in imported_parents},
        )

    def test_parent_account_and_guardian_names_stay_in_sync(self):
        guardians_by_phone = {
            row["phone"]: f"{row['last_name']} {row['first_name']}"
            for row in load_rows("guardians")
        }
        for parent in load_rows("parent_accounts"):
            with self.subTest(email=parent["email"]):
                self.assertEqual(
                    guardians_by_phone[parent["phone"]], parent["display_name"]
                )

    def test_more_than_two_duplicate_name_groups_is_rejected(self):
        rows = [
            {"last_name": last_name, "first_name": first_name}
            for last_name, first_name in (
                ("青木", "葵"),
                ("青木", "葵"),
                ("石井", "凛"),
                ("石井", "凛"),
                ("井上", "蓮"),
                ("井上", "蓮"),
            )
        ]

        with self.assertRaisesRegex(ValueError, "同姓同名は最大2組"):
            validate_name_duplicates("children", rows)

    def test_same_name_cannot_appear_three_times(self):
        rows = [
            {"display_name": "青木 真由美"},
            {"display_name": "青木 真由美"},
            {"display_name": "青木 真由美"},
        ]

        with self.assertRaisesRegex(ValueError, "各2人まで"):
            validate_name_duplicates("parent_accounts", rows)


if __name__ == "__main__":
    unittest.main()
