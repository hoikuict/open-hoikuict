import unittest
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from child_care_certification_service import effective_certification
from extended_care_fee_service import recalculate_attendance_charge, resolve_calculation_context
from family_support import apply_family_shared_data, build_family_payload
from models import (
    AttendanceRecord,
    CareNeedReason,
    CareTimeCategory,
    Child,
    ChildCareCertification,
    ChildCareNeedReason,
    ChildStatus,
    ExtendedCareCalculationSetting,
    ExtendedCareFeeRule,
    Family,
)
import routers.care_certifications as care_router_module


class CareCertificationTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(care_router_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="園児台帳担当",
            can_manage_child_records=True,
        )

        def override_current_user():
            return self.current_user

        self.app.dependency_overrides[care_router_module.get_session] = override_get_session
        self.app.dependency_overrides[care_router_module.get_current_staff_user] = override_current_user
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            family = Family(
                family_name="検証家",
                shared_profile={
                    "guardians": [
                        {"order": 1, "last_name": "検証", "first_name": "母", "relationship": "母"},
                        {"order": 2, "last_name": "検証", "first_name": "父", "relationship": "父"},
                    ]
                },
            )
            session.add(family)
            session.flush()
            child = Child(
                last_name="検証",
                first_name="園児",
                last_name_kana="ケンショウ",
                first_name_kana="エンジ",
                birth_date=date(2021, 4, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                family_id=family.id,
            )
            session.add(child)
            session.commit()
            self.child_id = child.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_staff_can_register_period_and_guardian_reasons(self):
        response = self.client.post(
            f"/children/{self.child_id}/care-certifications",
            data={
                "care_time_category": "short",
                "effective_from": "2026-04-01",
                "effective_to": "",
                "guardian_reason_1": "employment",
                "guardian_reason_2": "job_search_startup",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            certification = session.exec(select(ChildCareCertification)).one()
            reasons = session.exec(select(ChildCareNeedReason).order_by(ChildCareNeedReason.guardian_order)).all()
            self.assertEqual(certification.care_time_category, CareTimeCategory.short)
            self.assertEqual([item.reason for item in reasons], [CareNeedReason.employment, CareNeedReason.job_search_startup])
            self.assertEqual(reasons[0].guardian_name_snapshot, "検証 母")

    def test_overlapping_period_is_rejected(self):
        base = {
            "care_time_category": "standard",
            "effective_from": "2026-04-01",
            "effective_to": "2026-09-30",
            "guardian_reason_1": "employment",
        }
        self.client.post(f"/children/{self.child_id}/care-certifications", data=base)
        response = self.client.post(
            f"/children/{self.child_id}/care-certifications",
            data={**base, "care_time_category": "short", "effective_from": "2026-09-01"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        self.assertIn("care_error=", response.headers["location"])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(ChildCareCertification)).all()), 1)

    def test_parent_family_update_does_not_overwrite_certification(self):
        self.client.post(
            f"/children/{self.child_id}/care-certifications",
            data={
                "care_time_category": "standard",
                "effective_from": "2026-04-01",
                "guardian_reason_1": "illness_disability",
            },
        )
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            apply_family_shared_data(
                session,
                child.family,
                build_family_payload(
                    family_name="更新家",
                    home_address="更新住所",
                    home_phone="",
                    guardians_data=[
                        {"order": 1, "last_name": "更新", "first_name": "保護者", "relationship": "母"}
                    ],
                ),
            )
            session.commit()
            certification = effective_certification(session, self.child_id, date(2026, 8, 1))
            reason = session.exec(select(ChildCareNeedReason)).one()
            self.assertEqual(certification.care_time_category, CareTimeCategory.standard)
            self.assertEqual(reason.reason, CareNeedReason.illness_disability)
            self.assertEqual(reason.guardian_name_snapshot, "検証 母")

    def test_category_rules_calculate_standard_short_and_morning(self):
        with Session(self.engine) as session:
            session.add(ExtendedCareCalculationSetting(mode="category_aware", category_aware_from=date(2026, 4, 1)))
            standard = ChildCareCertification(
                child_id=self.child_id,
                care_time_category=CareTimeCategory.standard,
                effective_from=date(2026, 4, 1),
                effective_to=date(2026, 4, 30),
            )
            short = ChildCareCertification(
                child_id=self.child_id,
                care_time_category=CareTimeCategory.short,
                effective_from=date(2026, 5, 1),
            )
            session.add(standard)
            session.add(short)
            session.add(
                ExtendedCareFeeRule(
                    name="標準",
                    effective_from=date(2026, 4, 1),
                    care_time_category=CareTimeCategory.standard,
                    normal_start_time="07:30",
                    normal_end_time="18:00",
                    start_time="18:00",
                    grace_minutes=0,
                    rounding_minutes=15,
                    unit_price=100,
                    evening_enabled=True,
                )
            )
            session.add(
                ExtendedCareFeeRule(
                    name="短時間",
                    effective_from=date(2026, 4, 1),
                    care_time_category=CareTimeCategory.short,
                    normal_start_time="08:30",
                    normal_end_time="16:30",
                    morning_enabled=True,
                    morning_grace_minutes=0,
                    morning_rounding_minutes=15,
                    morning_unit_price=100,
                    start_time="16:30",
                    grace_minutes=0,
                    rounding_minutes=15,
                    unit_price=100,
                    evening_enabled=True,
                )
            )
            session.flush()
            standard_record = AttendanceRecord(
                child_id=self.child_id,
                attendance_date=date(2026, 4, 10),
                check_in_at=datetime(2026, 4, 10, 8, 0),
                check_out_at=datetime(2026, 4, 10, 18, 10),
            )
            short_record = AttendanceRecord(
                child_id=self.child_id,
                attendance_date=date(2026, 5, 10),
                check_in_at=datetime(2026, 5, 10, 8, 20),
                check_out_at=datetime(2026, 5, 10, 17, 10),
            )
            session.add(standard_record)
            session.add(short_record)
            session.flush()
            standard_charge = recalculate_attendance_charge(session, standard_record)
            short_charge = recalculate_attendance_charge(session, short_record)

            self.assertEqual(standard_charge.auto_amount, 100)
            self.assertEqual(standard_charge.care_time_category_snapshot, CareTimeCategory.standard)
            self.assertEqual(short_charge.morning_amount, 100)
            self.assertEqual(short_charge.evening_amount, 300)
            self.assertEqual(short_charge.auto_amount, 400)
            self.assertEqual(short_charge.calculation_version, "category_v1")

    def test_category_mode_without_certification_is_not_zero_or_legacy(self):
        with Session(self.engine) as session:
            session.add(ExtendedCareCalculationSetting(mode="category_aware", category_aware_from=date(2026, 4, 1)))
            session.add(
                ExtendedCareFeeRule(
                    name="従来",
                    effective_from=date(2020, 1, 1),
                    start_time="18:00",
                    unit_price=100,
                )
            )
            record = AttendanceRecord(
                child_id=self.child_id,
                attendance_date=date(2026, 4, 10),
                check_in_at=datetime(2026, 4, 10, 8, 0),
                check_out_at=datetime(2026, 4, 10, 18, 30),
            )
            session.add(record)
            session.flush()
            rule, certification, issue = resolve_calculation_context(session, record)
            charge = recalculate_attendance_charge(session, record)
            self.assertIsNone(rule)
            self.assertIsNone(certification)
            self.assertIn("保育認定", issue)
            self.assertIsNone(charge)


if __name__ == "__main__":
    unittest.main()
