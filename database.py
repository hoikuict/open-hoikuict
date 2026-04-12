from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from sqlalchemy import text
from sqlalchemy.engine import Engine
from starlette.requests import HTTPConnection
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


def _resolve_engine(db_engine: Optional[Engine] = None) -> Engine:
    return db_engine or engine


def get_session(connection: HTTPConnection):
    resolved_engine = engine
    if connection is not None:
        from demo_runtime import DEMO_SESSION_COOKIE_NAME, get_demo_session_manager, is_public_demo_enabled

        if is_public_demo_enabled():
            session_id = (
                getattr(connection.state, "demo_session_id", None)
                or connection.cookies.get(DEMO_SESSION_COOKIE_NAME)
                or connection.query_params.get(DEMO_SESSION_COOKIE_NAME)
            )
            if session_id:
                resolved_engine = get_demo_session_manager().get_engine(session_id)

    with Session(resolved_engine) as session:
        yield session


def create_db_and_tables(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    SQLModel.metadata.create_all(resolved_engine)
    _migrate_add_child_columns(resolved_engine)
    _migrate_add_attendance_columns(resolved_engine)
    _migrate_add_staff_columns(resolved_engine)
    _migrate_add_daily_contact_columns(resolved_engine)
    _migrate_add_parent_account_columns(resolved_engine)
    _migrate_add_family_columns(resolved_engine)
    _migrate_add_message_columns(resolved_engine)


def _table_columns(table_name: str, db_engine: Optional[Engine] = None) -> list[str]:
    resolved_engine = _resolve_engine(db_engine)
    with resolved_engine.connect() as conn:
        result = conn.execute(text(f"PRAGMA table_info({table_name})"))
        return [row[1] for row in result]


def _migrate_add_child_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            cols = _table_columns("children", resolved_engine)
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


def _migrate_add_attendance_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            cols = _table_columns("attendance_records", resolved_engine)
            if not cols:
                return
            if "planned_pickup_time" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN planned_pickup_time VARCHAR"))
            if "pickup_person" not in cols:
                conn.execute(text("ALTER TABLE attendance_records ADD COLUMN pickup_person VARCHAR"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_staff_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            cols = _table_columns("staff", resolved_engine)
            if not cols:
                return
            if "employment_type" not in cols:
                conn.execute(text("ALTER TABLE staff ADD COLUMN employment_type VARCHAR DEFAULT 'regular'"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_daily_contact_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            cols = _table_columns("daily_contact_entries", resolved_engine)
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

def _migrate_add_parent_account_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            cols = _table_columns("parent_accounts", resolved_engine)
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


def _migrate_add_family_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            child_cols = _table_columns("children", resolved_engine)
            if child_cols and "family_id" not in child_cols:
                conn.execute(text("ALTER TABLE children ADD COLUMN family_id INTEGER REFERENCES families(id)"))

            parent_cols = _table_columns("parent_accounts", resolved_engine)
            if parent_cols and "family_id" not in parent_cols:
                conn.execute(text("ALTER TABLE parent_accounts ADD COLUMN family_id INTEGER REFERENCES families(id)"))
            conn.commit()
    except Exception:
        pass


def _migrate_add_message_columns(db_engine: Optional[Engine] = None) -> None:
    resolved_engine = _resolve_engine(db_engine)
    try:
        with resolved_engine.connect() as conn:
            message_cols = _table_columns("messages", resolved_engine)
            if message_cols:
                if "parent_message_id" not in message_cols:
                    conn.execute(
                        text("ALTER TABLE messages ADD COLUMN parent_message_id INTEGER REFERENCES messages(id)")
                    )
                if "deleted_at" not in message_cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN deleted_at DATETIME"))
                if "deleted_by" not in message_cols:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN deleted_by VARCHAR"))
            conn.commit()
    except Exception:
        pass


def seed_classroom_data(db_engine: Optional[Engine] = None) -> None:
    from models import Classroom

    with Session(_resolve_engine(db_engine)) as session:
        classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()
        if classrooms:
            return

        for name, order in DEFAULT_CLASSROOMS:
            session.add(Classroom(name=name, display_order=order))

        session.commit()

def seed_staff_data(db_engine: Optional[Engine] = None) -> None:
    from auth import Role
    from models import Classroom, Staff, StaffEmploymentType, StaffStatus

    with Session(_resolve_engine(db_engine)) as session:
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

        staff_members = [
            Staff(
                full_name="園長",
                display_name="園長",
                role=Role.ADMIN,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=None,
            ),
            Staff(
                full_name="主任",
                display_name="主任",
                role=Role.ADMIN,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=None,
            ),
            Staff(
                full_name="ひよこぐみ担任",
                display_name="ひよこぐみ担任",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=classroom_id_at(0),
            ),
            Staff(
                full_name="たけのこぐみ担任",
                display_name="たけのこぐみ担任",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=classroom_id_at(1),
            ),
            Staff(
                full_name="きのこぐみ担任",
                display_name="きのこぐみ担任",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=classroom_id_at(2),
            ),
            Staff(
                full_name="パート職員",
                display_name="パート職員",
                role=Role.VIEW_ONLY,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.part_time,
                primary_classroom_id=None,
            ),
            Staff(
                full_name="アルバイト職員",
                display_name="アルバイト職員",
                role=Role.VIEW_ONLY,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.part_time,
                primary_classroom_id=None,
            ),
        ]

        for staff in staff_members:
            session.add(staff)

        session.commit()

def seed_sample_data(db_engine: Optional[Engine] = None) -> None:
    from models import Child, ChildStatus, Classroom, Family, Guardian

    with Session(_resolve_engine(db_engine)) as session:
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


def seed_parent_portal_data(db_engine: Optional[Engine] = None) -> None:
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

    with Session(_resolve_engine(db_engine)) as session:
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


def seed_meeting_note_data(db_engine: Optional[Engine] = None) -> None:
    from models import MeetingNote

    with Session(_resolve_engine(db_engine)) as session:
        if session.exec(select(MeetingNote)).first():
            return

        now = utc_now()
        session.add(
            MeetingNote(
                title="議事録",
                created_by="管理者",
                updated_by="管理者",
                created_at=now,
                updated_at=now,
            )
        )
        session.commit()


def bootstrap_family_records(db_engine: Optional[Engine] = None) -> None:
    with Session(_resolve_engine(db_engine)) as session:
        bootstrap_family_data(session)
        session.commit()


def seed_calendar_data(db_engine: Optional[Engine] = None) -> None:
    from models import (
        Calendar,
        CalendarMember,
        CalendarMemberRole,
        CalendarType,
        CalendarUserPreference,
        Staff,
        StaffStatus,
        User,
    )

    with Session(_resolve_engine(db_engine)) as session:
        active_staff = session.exec(
            select(Staff)
            .where(Staff.status == StaffStatus.active)
            .order_by(Staff.id)
        ).all()
        if not active_staff:
            return

        staff_defaults = {
            "園長": {"email": "principal@example.com", "sort_order": 10, "color": "#2563EB"},
            "主任": {"email": "chief@example.com", "sort_order": 20, "color": "#7C3AED"},
            "ひよこぐみ担任": {"email": "hiyoko@example.com", "sort_order": 30, "color": "#F59E0B"},
            "たけのこぐみ担任": {"email": "takenoko@example.com", "sort_order": 40, "color": "#10B981"},
            "きのこぐみ担任": {"email": "kinoko@example.com", "sort_order": 50, "color": "#EC4899"},
            "パート職員": {"email": "part@example.com", "sort_order": 60, "color": "#64748B"},
            "アルバイト職員": {"email": "arbeit@example.com", "sort_order": 70, "color": "#0EA5E9"},
        }

        def staff_profile(staff: Staff, index: int) -> dict[str, object]:
            fallback_id = staff.id if staff.id is not None else index + 1
            defaults = staff_defaults.get(staff.display_name, {})
            return {
                "email": defaults.get("email", f"demo-staff-{fallback_id}@example.com"),
                "sort_order": defaults.get("sort_order", (index + 1) * 10),
                "color": defaults.get("color", "#2563EB"),
            }

        def ensure_user(staff: Staff, *, email: str, sort_order: int) -> User:
            user = session.exec(select(User).where(User.email == email)).first()
            if user is None:
                user = User(
                    email=email,
                    display_name=staff.display_name,
                    timezone="Asia/Tokyo",
                    locale="ja-JP",
                    staff_role=staff.role.value,
                    staff_sort_order=sort_order,
                    is_calendar_admin=staff.role.value == "admin",
                    is_active=True,
                )
            else:
                user.display_name = staff.display_name
                user.timezone = user.timezone or "Asia/Tokyo"
                user.locale = user.locale or "ja-JP"
                user.staff_role = staff.role.value
                user.staff_sort_order = sort_order
                user.is_calendar_admin = staff.role.value == "admin"
                user.is_active = True
                user.updated_at = utc_now()
            session.add(user)
            session.flush()
            return user

        def ensure_member(calendar: Calendar, user: User, role: CalendarMemberRole) -> None:
            member = session.exec(
                select(CalendarMember).where(
                    CalendarMember.calendar_id == calendar.id,
                    CalendarMember.user_id == user.id,
                )
            ).first()
            if member is None:
                member = CalendarMember(calendar_id=calendar.id, user_id=user.id, role=role)
            else:
                member.role = role
                member.updated_at = utc_now()
            session.add(member)
            session.flush()

        def ensure_preference(calendar: Calendar, user: User, *, display_order: int) -> None:
            preference = session.exec(
                select(CalendarUserPreference).where(
                    CalendarUserPreference.calendar_id == calendar.id,
                    CalendarUserPreference.user_id == user.id,
                )
            ).first()
            if preference is None:
                preference = CalendarUserPreference(
                    calendar_id=calendar.id,
                    user_id=user.id,
                    is_visible=True,
                    display_order=display_order,
                )
            else:
                preference.is_visible = True
                preference.display_order = display_order
                preference.updated_at = utc_now()
            session.add(preference)
            session.flush()

        calendar_users: list[tuple[Staff, User, dict[str, object]]] = []
        for index, staff in enumerate(active_staff):
            profile = staff_profile(staff, index)
            user = ensure_user(
                staff,
                email=str(profile["email"]),
                sort_order=int(profile["sort_order"]),
            )
            calendar_users.append((staff, user, profile))

        for _, user, profile in calendar_users:
            personal_calendar = session.exec(
                select(Calendar).where(
                    Calendar.owner_user_id == user.id,
                    Calendar.is_primary.is_(True),
                )
            ).first()
            if personal_calendar is None:
                personal_calendar = session.exec(
                    select(Calendar).where(
                        Calendar.owner_user_id == user.id,
                        Calendar.calendar_type == CalendarType.staff_personal,
                    )
                ).first()
            if personal_calendar is None:
                personal_calendar = Calendar(owner_user_id=user.id)
            personal_calendar.name = f"{user.display_name}の個人カレンダー"
            personal_calendar.calendar_type = CalendarType.staff_personal
            personal_calendar.color = str(profile["color"])
            personal_calendar.description = "職員ごとの個人用カレンダー"
            personal_calendar.is_primary = True
            personal_calendar.is_archived = False
            personal_calendar.updated_at = utc_now()
            session.add(personal_calendar)
            session.flush()

            ensure_member(personal_calendar, user, CalendarMemberRole.owner)
            ensure_preference(personal_calendar, user, display_order=10)

            user.default_calendar_id = personal_calendar.id
            user.updated_at = utc_now()
            session.add(user)

        lead_user = calendar_users[0][1]
        shared_calendar = session.exec(
            select(Calendar).where(
                Calendar.calendar_type == CalendarType.facility_shared,
                Calendar.name == "施設共用カレンダー",
            )
        ).first()
        if shared_calendar is None:
            shared_calendar = session.exec(
                select(Calendar).where(Calendar.calendar_type == CalendarType.facility_shared)
            ).first()
        if shared_calendar is None:
            shared_calendar = Calendar(owner_user_id=lead_user.id)
        shared_calendar.owner_user_id = lead_user.id
        shared_calendar.name = "施設共用カレンダー"
        shared_calendar.calendar_type = CalendarType.facility_shared
        shared_calendar.color = "#059669"
        shared_calendar.description = "施設全体で共有するカレンダー"
        shared_calendar.is_primary = False
        shared_calendar.is_archived = False
        shared_calendar.updated_at = utc_now()
        session.add(shared_calendar)
        session.flush()

        for _, user, profile in calendar_users:
            role = (
                CalendarMemberRole.owner
                if user.id == shared_calendar.owner_user_id
                else CalendarMemberRole.editor if user.can_edit_calendar else CalendarMemberRole.viewer
            )
            ensure_member(shared_calendar, user, role)
            ensure_preference(shared_calendar, user, display_order=20 + int(profile["sort_order"]))

        session.commit()


def initialize_demo_template_database(db_path: Path) -> None:
    demo_engine = create_engine(
        f"sqlite:///{db_path.resolve().as_posix()}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    try:
        create_db_and_tables(demo_engine)
        seed_classroom_data(demo_engine)
        seed_staff_data(demo_engine)
        seed_sample_data(demo_engine)
        bootstrap_family_records(demo_engine)
        seed_parent_portal_data(demo_engine)
        seed_calendar_data(demo_engine)
        seed_meeting_note_data(demo_engine)
    finally:
        demo_engine.dispose()
