import unittest
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
    ParentAccount,
    User,
)


class ApplicationStartupTests(unittest.TestCase):
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
