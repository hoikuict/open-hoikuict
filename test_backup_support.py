"""Synthetic application DBs shared by backup/recovery tests (no live initialization)."""
from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3

from sqlmodel import SQLModel, Session, create_engine


def full_databases(main_db: Path, facility_db: Path, *, attachments=False, child=True):
    import models
    import child_records.models  # noqa: F401
    import plan_docs.db_models  # noqa: F401
    from plan_docs.services.bunrei import _ensure_facility_table

    main_db.parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{main_db}")
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if child:
            session.add(models.Family(id=1, family_name="架空家族"))
            session.add(models.Classroom(id=1, name="架空組", age=1))
            session.commit()
            session.add(models.Child(id=1, family_id=1, classroom_id=1,
                                     last_name="架空", first_name="園児", last_name_kana="カクウ",
                                     first_name_kana="エンジ", birth_date=date(2023, 1, 1),
                                     enrollment_date=date(2026, 4, 1)))
        if attachments:
            session.add(models.Notice(id=1, title="架空", body="架空"))
            session.add(models.Message(id=1, room_id=1, author_name="架空", body="架空"))
            session.commit()
            session.add(models.NoticeAttachment(notice_id=1, storage_path="notice.pdf",
                                                original_filename="notice.pdf", content_type="application/pdf",
                                                file_size=len(b"notice-pdf")))
            session.add(models.MessageAttachment(message_id=1, storage_path="message.png",
                                                 original_filename="message.png", file_size=len(b"message-image")))
        session.commit()
    engine.dispose()
    with closing(sqlite3.connect(facility_db)) as connection:
        _ensure_facility_table(connection)
        connection.commit()
