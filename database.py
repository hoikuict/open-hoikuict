from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import text
from sqlmodel import SQLModel, Session, create_engine, select

from family_support import bootstrap_family_data, sync_parent_child_links, sync_family_to_children
from time_utils import utc_now

DATABASE_URL = "sqlite:///./hoikuict.db"
engine = create_engine(DATABASE_URL, echo=False)

DEFAULT_CLASSROOMS = [
    ("ひよこ組", 1),
    ("うさぎ組", 2),
    ("きりん組", 3),
]


def get_session():
    with Session(engine) as session:
        yield session


def create_db_and_tables() -> None:
    SQLModel.metadata.create_all(engine)
    _migrate_add_child_columns()
    _migrate_add_attendance_columns()
    _migrate_add_staff_columns()
    _migrate_add_daily_contact_columns()
    _migrate_add_parent_account_columns()
    _migrate_add_family_columns()


def _table_columns(table_name: str) -> list[str]:
    with engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return [row[1] for row in result]


def _migrate_add_child_columns() -> None:
    try:
        with engine.connect() as conn:
            cols = _table_columns("children")
            if not cols:
                return
            if "home_address" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN home_address VARCHAR"))
            if "home_phone" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN home_phone VARCHAR"))
            if "older_sibling_id" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN older_sibling_id INTEGER REFERENCES children(id)"))
            if "classroom_id" not in cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN classroom_id INTEGER REFERENCES classrooms(id)"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_attendance_columns() -> None:
    try:
        with engine.connect() as conn:
            cols = _table_columns("attendance_records")
            if not cols:
                return
            if "planned_pickup_time" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN planned_pickup_time VARCHAR"))
            if "pickup_person" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN pickup_person VARCHAR"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_staff_columns() -> None:
    try:
        with engine.connect() as conn:
            cols = _table_columns("staff")
            if not cols:
                return
            if "employment_type" not in cols:
                conn.execute(text("ALTER TABLE staff ADD COLUMN employment_type VARCHAR DEFAULT 'regular'"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_daily_contact_columns() -> None:
    try:
        with engine.connect() as conn:
            cols = _table_columns("daily_contact_entries")
            if not cols:
                return
            if "contact_type" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN contact_type VARCHAR DEFAULT 'present'"))
            if "absence_temperature" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_temperature VARCHAR"))
            if "absence_symptoms" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_symptoms VARCHAR"))
            if "absence_diagnosis" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_diagnosis VARCHAR"))
            if "absence_note" not in cols:
                conn.execute(text("ALTER TABLE daily_contact_entries ADD COLUMN absence_note VARCHAR"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_parent_account_columns() -> None:
    try:
        with engine.connect() as conn:
            cols = _table_columns("parent_accounts")
            if not cols:
                return
            if "home_address" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN home_address VARCHAR"))
            if "workplace" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN workplace VARCHAR"))
            if "workplace_address" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN workplace_address VARCHAR"))
            if "workplace_phone" not in cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN workplace_phone VARCHAR"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_family_columns() -> None:
    try:
        with engine.connect() as conn:
            child_cols = _table_columns("children")
            if child_cols and "family_id" not in child_cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN family_id INTEGER REFERENCES families(id)"))

            parent_cols = _table_columns("parent_accounts")
            if parent_cols and "family_id" not in parent_cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN family_id INTEGER REFERENCES families(id)"))
            conn.commit()
    except Exception:
        pass


def seed_classroom_data() -> None:
    from models import Classroom

    with Session(engine) as session:
        classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        if classrooms:
            return

        for name, order in DEFAULT_CLASSROOMS:
            session.add(Classroom(name=name, display_order=order))

        session.commit()


def seed_staff_data() -> None:
    from auth import Role
    from models import Classroom, Staff, StaffEmploymentType, StaffStatus

    with Session(engine) as session:
        if session.exec(select(Staff)).first():
            return

        classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        classroom_ids = [classroom.id for classroom in classrooms if classroom.id is not None]

        def classroom_id_at(index: int) -> int | None:
            if not classroom_ids:
                return None
            return classroom_ids[min(index, len(classroom_ids) - 1)]

        staff_members = [
            Staff(
                full_name="山田 園長",
                display_name="山田園長",
                role=Role.ADMIN,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=None,
            ),
            Staff(
                full_name="佐藤 花",
                display_name="佐藤先生",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=classroom_id_at(0),
            ),
            Staff(
                full_name="鈴木 空",
                display_name="鈴木先生",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=classroom_id_at(1),
            ),
            Staff(
                full_name="中村 見学",
                display_name="中村さん",
                role=Role.VIEW_ONLY,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.part_time,
                primary_classroom_id=classroom_id_at(2),
            ),
        ]

        for staff in staff_members:
            session.add(staff)

        session.commit()


def seed_sample_data() -> None:
    from models import Child, ChildStatus, Classroom, Family, Guardian

    with Session(engine) as session:
        if session.exec(select(Child)).first():
            return

        classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        classroom_ids = [classroom.id for classroom in classrooms if classroom.id is not None]

        def classroom_id_at(index: int) -> int | None:
            if not classroom_ids:
                return None
            return classroom_ids[min(index, len(classroom_ids) - 1)]

        tanaka_family = Family(
            family_name="田中家",
            home_address="東京都渋谷区1-2-3",
            home_phone="03-1234-5678",
            shared_profile={
                "guardians": [
                    {
                        "order": 1,
                        "last_name": "田中",
                        "first_name": "真由美",
                        "last_name_kana": "タナカ",
                        "first_name_kana": "マユミ",
                        "relationship": "母",
                        "phone": "090-1111-2222",
                        "workplace": "サンプル商事",
                        "workplace_address": "東京都港区1-1-1",
                        "workplace_phone": "03-1111-2222",
                    },
                    {
                        "order": 2,
                        "last_name": "田中",
                        "first_name": "健一",
                        "last_name_kana": "タナカ",
                        "first_name_kana": "ケンイチ",
                        "relationship": "父",
                        "phone": "090-3333-4444",
                        "workplace": "サンプル工業",
                        "workplace_address": "東京都品川区2-2-2",
                        "workplace_phone": "03-3333-4444",
                    },
                ]
            },
        )
        sato_family = Family(
            family_name="佐藤家",
            home_address="東京都新宿区4-5-6",
            home_phone="03-2345-6789",
            shared_profile={
                "guardians": [
                    {
                        "order": 1,
                        "last_name": "佐藤",
                        "first_name": "真由美",
                        "last_name_kana": "サトウ",
                        "first_name_kana": "マユミ",
                        "relationship": "母",
                        "phone": "090-5555-6666",
                        "workplace": "グリーン企画",
                        "workplace_address": "東京都新宿区7-8-9",
                        "workplace_phone": "03-5555-6666",
                    }
                ]
            },
        )
        ito_family = Family(
            family_name="伊藤家",
            home_address="東京都目黒区9-8-7",
            home_phone="03-3456-7890",
            shared_profile={
                "guardians": [
                    {
                        "order": 1,
                        "last_name": "伊藤",
                        "first_name": "恵",
                        "last_name_kana": "イトウ",
                        "first_name_kana": "メグミ",
                        "relationship": "母",
                        "phone": "090-7777-8888",
                        "workplace": "ブルークリニック",
                        "workplace_address": "東京都目黒区3-3-3",
                        "workplace_phone": "03-7777-8888",
                    }
                ]
            },
        )
        session.add(tanaka_family)
        session.add(sato_family)
        session.add(ito_family)
        session.flush()

        children = [
            Child(
                last_name="田中",
                first_name="さくら",
                last_name_kana="タナカ",
                first_name_kana="サクラ",
                birth_date=date(2020, 4, 5),
                enrollment_date=date(2023, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(1),
                family_id=tanaka_family.id,
                extra_data={"allergy": ["卵"], "medical_notes": "特記事項なし"},
            ),
            Child(
                last_name="田中",
                first_name="はると",
                last_name_kana="タナカ",
                first_name_kana="ハルト",
                birth_date=date(2021, 8, 12),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(0),
                family_id=tanaka_family.id,
                extra_data={"allergy": [], "medical_notes": ""},
            ),
            Child(
                last_name="佐藤",
                first_name="真由美",
                last_name_kana="サトウ",
                first_name_kana="マユミ",
                birth_date=date(2019, 6, 15),
                enrollment_date=date(2022, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(2),
                family_id=sato_family.id,
                extra_data={"allergy": ["乳"], "medical_notes": "エピペン持参"},
            ),
            Child(
                last_name="伊藤",
                first_name="ネオ",
                last_name_kana="イトウ",
                first_name_kana="ネオ",
                birth_date=date(2021, 4, 12),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom_id_at(0),
                family_id=ito_family.id,
                extra_data={"allergy": [], "medical_notes": ""},
            ),
            Child(
                last_name="山田",
                first_name="こうた",
                last_name_kana="ヤマダ",
                first_name_kana="コウタ",
                birth_date=date(2018, 11, 3),
                enrollment_date=date(2021, 4, 1),
                withdrawal_date=date(2025, 3, 31),
                status=ChildStatus.graduated,
                extra_data={"allergy": [], "medical_notes": ""},
            ),
        ]
        for child in children:
            session.add(child)
        session.flush()

        children[1].older_sibling_id = children[0].id
        session.add(children[1])

        for family in (tanaka_family, sato_family, ito_family):
            sync_family_to_children(session, family, updated_at=utc_now())

        session.add(
            Guardian(
                child_id=children[4].id,
                last_name="山田",
                first_name="太郎",
                relationship="父",
                phone="090-9999-0000",
                workplace="レッド建設",
                workplace_address="東京都世田谷区5-5-5",
                workplace_phone="03-9999-0000",
                order=1,
            )
        )

        session.commit()


def seed_parent_portal_data() -> None:
    from models import (
        Child,
        ChildStatus,
        DailyContactEntry,
        Family,
        Notice,
        NoticePriority,
        NoticeRead,
        NoticeStatus,
        NoticeTarget,
        NoticeTargetType,
        ParentAccount,
        ParentAccountStatus,
    )

    with Session(engine) as session:
        if session.exec(select(ParentAccount)).first():
            return

        families = session.exec(
            select(Family).order_by(Family.id)
        ).all()
        if not families:
            bootstrap_family_data(session)
            session.flush()
            families = session.exec(select(Family).order_by(Family.id)).all()
        if not families:
            return

        tanaka_family = families[0]
        sato_family = families[1] if len(families) > 1 else families[0]

        accounts = [
            ParentAccount(
                display_name="田中 健一",
                email="tanaka.parent@example.com",
                phone="090-1111-0001",
                home_address=tanaka_family.home_address,
                workplace="サンプル商事",
                workplace_address="東京都港区1-1-1",
                workplace_phone="03-1111-1111",
                family_id=tanaka_family.id,
                status=ParentAccountStatus.active,
                invited_at=utc_now(),
            ),
            ParentAccount(
                display_name="佐藤 真由美",
                email="sato.parent@example.com",
                phone="090-2222-0002",
                home_address=sato_family.home_address,
                workplace="グリーン企画",
                workplace_address="東京都新宿区7-8-9",
                workplace_phone="03-2222-2222",
                family_id=sato_family.id,
                status=ParentAccountStatus.active,
                invited_at=utc_now(),
            ),
        ]
        for account in accounts:
            session.add(account)
        session.flush()

        families = session.exec(
            select(Family)
            .where(Family.id.in_([tanaka_family.id, sato_family.id]))
        ).all()
        for family in families:
            session.refresh(family)
            sync_parent_child_links(session, family)

        today = date.today()
        enrolled_children = session.exec(
            select(Child)
            .where(Child.status == ChildStatus.enrolled)
            .order_by(Child.last_name_kana, Child.first_name_kana)
        ).all()
        tanaka_child = next((child for child in enrolled_children if child.family_id == tanaka_family.id), None)
        sato_child = next((child for child in enrolled_children if child.family_id == sato_family.id), None)

        if tanaka_child:
            session.add(
                DailyContactEntry(
                    child_id=tanaka_child.id,
                    parent_account_id=accounts[0].id,
                    target_date=today,
                    temperature="36.7",
                    sleep_notes="21:00-6:30",
                    breakfast_status="完食",
                    bowel_movement_status="あり",
                    mood="元気",
                    cough="なし",
                    runny_nose="なし",
                    medication="なし",
                    condition_note="朝から元気です。",
                    contact_note="本日は16:30ごろお迎え予定です。",
                    submitted_at=utc_now(),
                )
            )
        if sato_child:
            session.add(
                DailyContactEntry(
                    child_id=sato_child.id,
                    parent_account_id=accounts[1].id,
                    target_date=today,
                    temperature="37.0",
                    sleep_notes="20:30-6:00",
                    breakfast_status="少なめ",
                    bowel_movement_status="なし",
                    mood="少し眠そう",
                    cough="少し",
                    runny_nose="なし",
                    medication="なし",
                    condition_note="少し鼻水があります。",
                    contact_note="様子を見てください。",
                    submitted_at=utc_now(),
                )
            )

        all_notice = Notice(
            title="今週の持ち物について",
            body="来週は避難訓練があります。カラー帽子と上履きを忘れずにお持ちください。",
            priority=NoticePriority.normal,
            status=NoticeStatus.published,
            publish_start_at=utc_now() - timedelta(hours=2),
            created_by="管理者サンプル",
        )
        session.add(all_notice)
        session.flush()
        session.add(NoticeTarget(notice_id=all_notice.id, target_type=NoticeTargetType.all))

        if tanaka_child and tanaka_child.classroom_id:
            classroom_notice = Notice(
                title="クラス懇談会のお知らせ",
                body="今週金曜日の16:00よりクラス懇談会を行います。ご都合をお知らせください。",
                priority=NoticePriority.high,
                status=NoticeStatus.published,
                publish_start_at=utc_now() - timedelta(hours=2),
                created_by="管理者サンプル",
            )
            session.add(classroom_notice)
            session.flush()
            session.add(
                NoticeTarget(
                    notice_id=classroom_notice.id,
                    target_type=NoticeTargetType.classroom,
                    target_value=str(tanaka_child.classroom_id),
                )
            )

        if sato_child:
            child_notice = Notice(
                title="個別連絡",
                body=f"{sato_child.full_name} さんの体調確認をお願いします。",
                priority=NoticePriority.high,
                status=NoticeStatus.published,
                publish_start_at=utc_now() - timedelta(hours=2),
                created_by="管理者サンプル",
            )
            session.add(child_notice)
            session.flush()
            session.add(
                NoticeTarget(
                    notice_id=child_notice.id,
                    target_type=NoticeTargetType.child,
                    target_value=str(sato_child.id),
                )
            )

        session.flush()
        session.add(
            NoticeRead(
                notice_id=all_notice.id,
                parent_account_id=accounts[0].id,
                read_at=utc_now(),
            )
        )
        session.commit()


def bootstrap_family_records() -> None:
    with Session(engine) as session:
        bootstrap_family_data(session)
        session.commit()
