import unittest
from datetime import date

from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from demo_data_generation import (
    demo_attendance_range,
    demo_calendar_range,
    seed_dynamic_demo_data,
)
from models import (
    AttendanceRecord,
    AttendanceVerification,
    Calendar,
    CalendarType,
    Child,
    DailyContactEntry,
    Event,
    ExtendedCareCharge,
    ParentAccount,
    ParentChildLink,
    ParentContactType,
    User,
)


class DemoDataGenerationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as session:
            child = Child(
                last_name="架空",
                first_name="園児",
                last_name_kana="カクウ",
                first_name_kana="エンジ",
                birth_date=date(2022, 5, 1),
                enrollment_date=date(2024, 4, 1),
            )
            user = User(
                email="demo-generation@example.com",
                display_name="デモ担当",
                staff_role="admin",
                is_calendar_admin=True,
            )
            session.add(child)
            session.add(user)
            session.flush()
            parent = ParentAccount(
                display_name="架空 保護者",
                email="parent-demo-generation@example.com",
            )
            session.add(parent)
            session.flush()
            session.add(
                ParentChildLink(
                    parent_account_id=parent.id,
                    child_id=child.id,
                    is_primary_contact=True,
                )
            )
            session.add(
                Calendar(
                    owner_user_id=user.id,
                    name="施設共用カレンダー",
                    calendar_type=CalendarType.facility_shared,
                )
            )
            session.commit()

    def tearDown(self):
        self.engine.dispose()

    def test_date_ranges_follow_reference_date(self):
        reference_date = date(2026, 7, 27)

        self.assertEqual(
            demo_calendar_range(reference_date),
            (date(2026, 5, 1), date(2026, 9, 30)),
        )
        self.assertEqual(
            demo_attendance_range(reference_date),
            (date(2026, 4, 27), date(2026, 7, 27)),
        )

    def test_seed_creates_rolling_random_demo_data_idempotently(self):
        reference_date = date(2026, 7, 27)
        with Session(self.engine) as session:
            first_counts = seed_dynamic_demo_data(
                session,
                reference_date=reference_date,
                random_seed=1234,
                recalculate_extended_care=False,
            )
            session.commit()

            verifications = session.exec(select(AttendanceVerification)).all()
            attendance_records = session.exec(select(AttendanceRecord)).all()
            daily_contacts = session.exec(select(DailyContactEntry)).all()
            events = session.exec(select(Event)).all()

            expected_service_days = 66
            self.assertEqual(len(verifications), expected_service_days)
            self.assertEqual(
                min(row.target_date for row in verifications),
                date(2026, 4, 27),
            )
            self.assertEqual(
                max(row.target_date for row in verifications),
                date(2026, 7, 27),
            )
            self.assertTrue(attendance_records)
            self.assertTrue(
                all(
                    date(2026, 4, 27) <= row.attendance_date <= reference_date
                    and row.attendance_date.weekday() < 5
                    for row in attendance_records
                )
            )
            self.assertTrue(daily_contacts)
            verification_by_key = {
                (row.child_id, row.target_date): row.status for row in verifications
            }
            for entry in daily_contacts:
                verification_status = verification_by_key[(entry.child_id, entry.target_date)]
                if verification_status.value == "sick_absent":
                    self.assertEqual(entry.contact_type, ParentContactType.absent_sick)
                    self.assertTrue(entry.absence_symptoms)
                elif verification_status.value == "private_absent":
                    self.assertEqual(entry.contact_type, ParentContactType.absent_private)
                else:
                    self.assertEqual(entry.contact_type, ParentContactType.present)
                    self.assertTrue(entry.temperature)
            self.assertEqual(len(events), 30)
            self.assertEqual(
                {(row.start_at.year, row.start_at.month) for row in events},
                {
                    (2026, 5),
                    (2026, 6),
                    (2026, 7),
                    (2026, 8),
                    (2026, 9),
                },
            )
            self.assertEqual(first_counts["events"], 30)
            self.assertEqual(session.exec(select(ExtendedCareCharge)).all(), [])

            before = (
                len(verifications),
                len(attendance_records),
                len(daily_contacts),
                len(events),
            )
            second_counts = seed_dynamic_demo_data(
                session,
                reference_date=reference_date,
                random_seed=1234,
                recalculate_extended_care=False,
            )
            session.commit()
            after = (
                len(session.exec(select(AttendanceVerification)).all()),
                len(session.exec(select(AttendanceRecord)).all()),
                len(session.exec(select(DailyContactEntry)).all()),
                len(session.exec(select(Event)).all()),
            )

        self.assertEqual(before, after)
        self.assertTrue(all(count == 0 for count in second_counts.values()))

    def test_weekend_reference_date_still_has_current_day_contacts(self):
        reference_date = date(2026, 8, 2)  # Sunday
        with Session(self.engine) as session:
            for index in range(2, 17):
                child = Child(
                    last_name="架空",
                    first_name=f"園児{index}",
                    last_name_kana="カクウ",
                    first_name_kana=f"エンジ{index}",
                    birth_date=date(2022, 5, 1),
                    enrollment_date=date(2024, 4, 1),
                )
                parent = ParentAccount(
                    display_name=f"架空 保護者{index}",
                    email=f"parent-demo-generation-{index}@example.com",
                )
                session.add(child)
                session.add(parent)
                session.flush()
                session.add(
                    ParentChildLink(
                        parent_account_id=parent.id,
                        child_id=child.id,
                        is_primary_contact=True,
                    )
                )
            session.flush()
            seed_dynamic_demo_data(
                session,
                reference_date=reference_date,
                random_seed=1234,
                recalculate_extended_care=False,
            )
            session.commit()

            verifications = session.exec(
                select(AttendanceVerification).where(
                    AttendanceVerification.target_date == reference_date
                )
            ).all()
            contacts = session.exec(
                select(DailyContactEntry).where(
                    DailyContactEntry.target_date == reference_date
                )
            ).all()

        self.assertEqual(len(verifications), 16)
        self.assertTrue(contacts)
        self.assertLess(len(contacts), len(verifications))
        self.assertIn(1, {contact.child_id for contact in contacts})
        self.assertNotIn(16, {contact.child_id for contact in contacts})


if __name__ == "__main__":
    unittest.main()
