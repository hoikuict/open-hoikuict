import unittest
from datetime import date
from unittest.mock import patch

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

import database
import main
from models import (
    Calendar,
    Child,
    Classroom,
    ExtendedCareFeeRule,
    Family,
    Guardian,
    ParentAccount,
    User,
)


class ApplicationStartupTests(unittest.TestCase):
    def test_existing_family_ledger_is_unchanged_when_startup_repeats(self):
        test_engine = create_engine('sqlite://', poolclass=StaticPool)
        SQLModel.metadata.create_all(test_engine)
        try:
            with Session(test_engine) as session:
                family = Family(family_name='取り込み済み家族', shared_profile={'guardians': []})
                session.add(family)
                session.flush()
                linked = Child(last_name='検証', first_name='一郎', last_name_kana='ケンショウ',
                               first_name_kana='イチロウ', birth_date=date(2022, 1, 1),
                               enrollment_date=date(2026, 4, 1), family_id=family.id,
                               home_address='園児側で保持している住所')
                unlinked = Child(last_name='検証', first_name='二郎', last_name_kana='ケンショウ',
                                 first_name_kana='ジロウ', birth_date=date(2023, 1, 1),
                                 enrollment_date=date(2026, 4, 1), home_address='未紐付け園児の住所')
                session.add_all([linked, unlinked])
                session.flush()
                session.add(Guardian(child_id=linked.id, last_name='検証', first_name='祖母',
                                     relationship='祖母', order=3, workplace='既存の勤務先'))
                session.commit()
                before = {model.__tablename__: [row.model_dump() for row in session.exec(select(model)).all()]
                          for model in (Family, Child, Guardian)}
            with patch.object(database, 'engine', test_engine):
                database.bootstrap_family_records()
                database.bootstrap_family_records()
            with Session(test_engine) as session:
                after = {model.__tablename__: [row.model_dump() for row in session.exec(select(model)).all()]
                         for model in (Family, Child, Guardian)}
            self.assertEqual(before, after)
        finally:
            test_engine.dispose()

    def test_legacy_ledger_without_families_is_migrated_once(self):
        test_engine = create_engine('sqlite://', poolclass=StaticPool)
        SQLModel.metadata.create_all(test_engine)
        try:
            with Session(test_engine) as session:
                child = Child(last_name='旧台帳', first_name='花子', last_name_kana='キュウダイチョウ',
                              first_name_kana='ハナコ', birth_date=date(2022, 1, 1),
                              enrollment_date=date(2026, 4, 1), home_address='旧台帳の住所')
                session.add(child)
                session.flush()
                child_id = child.id
                session.add(Guardian(child_id=child.id, last_name='旧台帳', first_name='保護者',
                                     relationship='母', order=1, workplace='旧台帳の勤務先'))
                session.commit()
            with patch.object(database, 'engine', test_engine):
                database.bootstrap_family_records()
                database.bootstrap_family_records()
            with Session(test_engine) as session:
                families = session.exec(select(Family)).all()
                self.assertEqual(len(families), 1)
                self.assertEqual(session.get(Child, child_id).family_id, families[0].id)
                self.assertEqual(families[0].home_address, '旧台帳の住所')
                self.assertEqual(families[0].guardian_profiles()[0]['workplace'], '旧台帳の勤務先')
                self.assertEqual(len(session.exec(select(Guardian)).all()), 1)
        finally:
            test_engine.dispose()

    def test_initialize_application_does_not_seed_business_data(self):
        test_engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        original_engine = database.engine
        database.engine = test_engine
        try:
            with (
                patch.object(main, "validate_runtime_security"),
                patch.object(main, "_cleanup_stale_previews"),
                patch.object(main, "ensure_runtime_files"),
                patch.object(main, "apply_parent_push_retention"),
                patch.object(main, "create_db_and_tables", side_effect=lambda: SQLModel.metadata.create_all(test_engine)),
            ):
                main.initialize_application()
                main.initialize_application()

            with Session(test_engine) as session:
                for model in (
                    Classroom,
                    Family,
                    Child,
                    ParentAccount,
                    User,
                    Calendar,
                    ExtendedCareFeeRule,
                ):
                    self.assertEqual(len(session.exec(select(model)).all()), 0, model.__name__)
        finally:
            database.engine = original_engine
            test_engine.dispose()


if __name__ == "__main__":
    unittest.main()
