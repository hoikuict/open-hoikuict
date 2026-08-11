import unittest
import uuid
from datetime import date, datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from extended_care_billing_transfer_service import (
    ExtendedCareBillingTransferError,
    build_extended_care_transfer_preview,
    revert_extended_care_transfer,
    transfer_extended_care_charges,
)
from extended_care_fee_service import adjust_charge, recalculate_attendance_charge
from models import (
    AttendanceRecord,
    BillingChargeLine,
    BillingChargeSourceType,
    BillingClaim,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    Child,
    ChildStatus,
    Classroom,
    ExtendedCareBillingSetting,
    ExtendedCareBillingTransferLog,
    ExtendedCareCharge,
    ExtendedCareChargeStatus,
    ExtendedCareFeeRule,
    Family,
    FeeItem,
)
import routers.billing as billing_module
import routers.extended_care_fees as extended_care_fees_module


class ExtendedCareBillingTransferTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.include_router(extended_care_fees_module.router)
        self.app.include_router(billing_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.user_id = uuid.uuid4()
        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="請求担当",
            user_id=self.user_id,
        )

        def override_get_current_staff_user():
            return self.current_user

        for module in (extended_care_fees_module, billing_module):
            self.app.dependency_overrides[module.get_session] = override_get_session
            self.app.dependency_overrides[
                module.get_current_staff_user
            ] = override_get_current_staff_user
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            family = Family(family_name="田中家")
            classroom = Classroom(name="ひよこ組", display_order=1)
            session.add(family)
            session.add(classroom)
            session.flush()
            child = Child(
                last_name="田中",
                first_name="太郎",
                last_name_kana="タナカ",
                first_name_kana="タロウ",
                birth_date=date(2021, 4, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                classroom_id=classroom.id,
                family_id=family.id,
            )
            rule = ExtendedCareFeeRule(
                name="標準延長保育料",
                effective_from=date(2026, 1, 1),
                start_time="18:00",
                grace_minutes=5,
                rounding_minutes=15,
                unit_price=100,
                is_active=True,
            )
            cycle = BillingCycle(
                year_month="2026-03",
                period_start=date(2026, 3, 1),
                period_end=date(2026, 3, 31),
                withdrawal_date=date(2026, 4, 27),
                status=BillingCycleStatus.confirmed,
            )
            setting = ExtendedCareBillingSetting(is_enabled=True)
            session.add(child)
            session.add(rule)
            session.add(cycle)
            session.add(setting)
            session.commit()
            self.child_id = child.id
            self.cycle_id = cycle.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _create_charge(
        self,
        target_date: date,
        checkout: datetime,
        *,
        confirm: bool = True,
        adjustment: int = 0,
    ) -> int:
        with Session(self.engine) as session:
            record = AttendanceRecord(
                child_id=self.child_id,
                attendance_date=target_date,
                check_in_at=datetime.combine(target_date, datetime.min.time()).replace(hour=9),
                check_out_at=checkout,
            )
            session.add(record)
            session.flush()
            charge = recalculate_attendance_charge(session, record)
            if adjustment:
                adjust_charge(charge, adjustment, "調整", "請求担当")
            elif confirm:
                charge.status = ExtendedCareChargeStatus.confirmed
                charge.confirmed_by = "請求担当"
            session.add(charge)
            session.commit()
            return charge.id

    def _transfer(self):
        with Session(self.engine) as session:
            result = transfer_extended_care_charges(
                session,
                "2026-03",
                executed_by_user_id=None,
                executed_by_name="請求担当",
            )
            session.commit()
            return result

    def test_draft_charge_blocks_monthly_transfer(self):
        self._create_charge(
            date(2026, 3, 2),
            datetime(2026, 3, 2, 18, 6),
            confirm=False,
        )
        with Session(self.engine) as session:
            preview = build_extended_care_transfer_preview(session, "2026-03")
            self.assertFalse(preview.can_transfer)
            self.assertEqual(preview.unconfirmed_count, 1)
            with self.assertRaises(ExtendedCareBillingTransferError):
                transfer_extended_care_charges(
                    session,
                    "2026-03",
                    executed_by_user_id=None,
                    executed_by_name="請求担当",
                )
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(BillingChargeLine)).all(), [])

    def test_transfer_aggregates_locks_and_is_idempotent(self):
        charge_a = self._create_charge(
            date(2026, 3, 2), datetime(2026, 3, 2, 18, 6)
        )
        charge_b = self._create_charge(
            date(2026, 3, 3), datetime(2026, 3, 3, 18, 21), adjustment=50
        )

        first = self._transfer()
        second = self._transfer()
        self.assertEqual(first.action, "transfer")
        self.assertEqual(first.total_amount, 350)
        self.assertEqual(second.action, "none")

        with Session(self.engine) as session:
            lines = session.exec(select(BillingChargeLine)).all()
            self.assertEqual(len(lines), 1)
            self.assertEqual(lines[0].amount, 350)
            self.assertTrue(lines[0].is_locked)
            self.assertEqual(lines[0].source_type, BillingChargeSourceType.extension_auto)
            self.assertEqual(lines[0].source_reference, f"extended-care:{self.cycle_id}:{self.child_id}")
            for charge_id, amount in ((charge_a, 100), (charge_b, 250)):
                charge = session.get(ExtendedCareCharge, charge_id)
                self.assertEqual(charge.billing_charge_line_id, lines[0].id)
                self.assertEqual(charge.transferred_amount, amount)
            claim = session.exec(select(BillingClaim)).one()
            self.assertEqual(claim.total_amount, 350)
            logs = session.exec(select(ExtendedCareBillingTransferLog)).all()
            self.assertEqual([log.action for log in logs], ["transfer"])

        response = self.client.get(
            f"/billing/cycles/{self.cycle_id}/child-charges"
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("自動転送・ロック", response.text)
        self.assertIn("延長保育から自動転送", response.text)
        self.assertIn("確定済み", response.text)

    def test_late_charge_retransfers_and_revert_unlocks_source(self):
        first_charge_id = self._create_charge(
            date(2026, 3, 2), datetime(2026, 3, 2, 18, 6)
        )
        self._transfer()
        late_charge_id = self._create_charge(
            date(2026, 3, 4), datetime(2026, 3, 4, 18, 21)
        )
        result = self._transfer()
        self.assertEqual(result.action, "retransfer")
        self.assertEqual(result.total_amount, 300)

        with Session(self.engine) as session:
            line = session.exec(select(BillingChargeLine)).one()
            self.assertEqual(line.amount, 300)
            with self.assertRaises(ValueError):
                adjust_charge(
                    session.get(ExtendedCareCharge, first_charge_id),
                    10,
                    "転送後調整",
                    "請求担当",
                )
            revert = revert_extended_care_transfer(
                session,
                "2026-03",
                executed_by_user_id=None,
                executed_by_name="請求担当",
            )
            session.commit()
            self.assertEqual(revert.action, "revert")

        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(BillingChargeLine)).all(), [])
            self.assertEqual(session.exec(select(BillingClaim)).one().total_amount, 0)
            for charge_id in (first_charge_id, late_charge_id):
                charge = session.get(ExtendedCareCharge, charge_id)
                self.assertIsNone(charge.billing_charge_line_id)
                self.assertIsNone(charge.transferred_amount)
            logs = session.exec(select(ExtendedCareBillingTransferLog)).all()
            self.assertEqual([log.action for log in logs], ["transfer", "retransfer", "revert"])

    def test_route_permissions_for_transfer_and_settings(self):
        self.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧担当")
        self.assertEqual(
            self.client.get("/extended-care-fees/billing-transfer?month=2026-03").status_code,
            403,
        )
        self.assertEqual(
            self.client.post(
                "/extended-care-fees/settings/billing",
                data={"is_enabled": "1", "fee_item_code": "monthly_childcare"},
            ).status_code,
            403,
        )

        self.current_user = StaffUser(role=Role.CAN_EDIT, name="請求担当")
        self.assertEqual(
            self.client.post(
                "/extended-care-fees/settings/billing",
                data={"is_enabled": "1", "fee_item_code": "monthly_childcare"},
            ).status_code,
            403,
        )

        self.current_user = StaffUser(role=Role.ADMIN, name="管理者")
        response = self.client.post(
            "/extended-care-fees/settings/billing",
            data={
                "is_enabled": "1",
                "fee_item_code": "monthly_childcare",
                "description_template": "延長保育料（{year}年{month}月分）",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_manual_conflict_has_correction_button_and_returns_to_preview(self):
        self._create_charge(
            date(2026, 3, 2), datetime(2026, 3, 2, 18, 6)
        )
        with Session(self.engine) as session:
            child = session.get(Child, self.child_id)
            previous_family = Family(family_name="旧田中家")
            session.add(previous_family)
            session.flush()
            fee_item = FeeItem(
                code="monthly_childcare",
                name="延長保育料",
                category="monthly",
                charge_unit="child",
            )
            claim = BillingClaim(
                billing_cycle_id=self.cycle_id,
                family_id=child.family_id,
                payment_method=BillingPaymentMethod.direct_debit,
                total_amount=400,
            )
            previous_claim = BillingClaim(
                billing_cycle_id=self.cycle_id,
                family_id=previous_family.id,
                payment_method=BillingPaymentMethod.direct_debit,
                total_amount=200,
            )
            session.add(fee_item)
            session.add(claim)
            session.add(previous_claim)
            session.flush()
            session.add_all(
                [
                BillingChargeLine(
                    billing_claim_id=claim.id,
                    fee_item_id=fee_item.id,
                    child_id=self.child_id,
                    source_type=BillingChargeSourceType.manual,
                    description="延長保育料（月額）",
                    amount=400,
                    unit_price=400,
                ),
                BillingChargeLine(
                    billing_claim_id=previous_claim.id,
                    fee_item_id=fee_item.id,
                    child_id=self.child_id,
                    source_type=BillingChargeSourceType.manual,
                    description="延長保育料（旧家族請求）",
                    amount=200,
                    unit_price=200,
                ),
                ]
            )
            session.commit()

        preview = self.client.get(
            "/extended-care-fees/billing-transfer?month=2026-03"
        )
        self.assertEqual(preview.status_code, 200)
        self.assertIn("競合手入力を削除", preview.text)
        self.assertIn("請求入力を開く", preview.text)
        self.assertIn('id="manual-conflict-delete-form"', preview.text)
        self.assertIn('form="manual-conflict-delete-form"', preview.text)
        self.assertIn(f'name="child_id" value="{self.child_id}"', preview.text)
        self.assertIn(
            f"#billing-child-{self.child_id}",
            preview.text,
        )

        correction = self.client.get(
            f"/billing/cycles/{self.cycle_id}/child-charges?return_month=2026-03"
        )
        self.assertEqual(correction.status_code, 200)
        self.assertIn("転送確認へ戻る", correction.text)
        self.assertIn("空欄または0円", correction.text)
        self.assertIn(f'id="billing-child-{self.child_id}"', correction.text)

        removed = self.client.post(
            "/extended-care-fees/billing-transfer/manual-conflict",
            data={
                "month": "2026-03",
                "child_id": str(self.child_id),
            },
            follow_redirects=False,
        )
        self.assertEqual(removed.status_code, 303)
        self.assertIn(
            "/extended-care-fees/billing-transfer?",
            removed.headers["location"],
        )
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(BillingChargeLine)).all(), [])
            preview_after = build_extended_care_transfer_preview(session, "2026-03")
            self.assertTrue(preview_after.can_transfer)


if __name__ == "__main__":
    unittest.main()
