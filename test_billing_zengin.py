import unittest
from datetime import date
from decimal import Decimal

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from billing_calculation_service import BillingCalculationError, apply_proration_rounding, validate_charge_amount
from models import (
    BillingChargeSourceType,
    BillingClaim,
    BillingClaimStatus,
    BillingCycle,
    BillingCycleStatus,
    BillingPaymentMethod,
    BillingSetting,
    Child,
    ChildStatus,
    DirectDebitStatus,
    Family,
    FamilyBillingProfile,
    FamilyBillingProfileChangeLog,
    MealFeeRule,
    MealFeeProrationPolicy,
    ProrationRounding,
    ZenginExport,
    ZenginExportLine,
    ZenginExportStatus,
    User,
)
import routers.billing as billing_router_module
import routers.zengin as zengin_router_module
from zengin_service import (
    ParsedResultRecord,
    ZenginError,
    build_data_record,
    build_end_record,
    build_file_bytes,
    build_header_record,
    build_trailer_record,
    build_zengin_file,
    create_customer_number,
    create_zengin_export,
    parse_result_file,
    mark_zengin_export_submitted,
    supersede_zengin_export,
)


class BillingZenginTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)
        self.current_user = StaffUser(role=Role.ADMIN, name="園長")

    def tearDown(self):
        self.engine.dispose()

    def _seed_exportable_claim(self, *, direct_debit_status=DirectDebitStatus.active):
        with Session(self.engine) as session:
            settings = BillingSetting(
                facility_name="HOIKU",
                collector_code="1234567890",
                collector_name_kana="HOIKU",
                customer_number_facility_code="001",
                withdrawal_bank_code="0001",
                withdrawal_bank_name_kana="BANK",
                withdrawal_branch_code="001",
                withdrawal_branch_name_kana="BRANCH",
                collector_account_type="1",
                collector_account_number="1234567",
            )
            family = Family(family_name="田中家")
            session.add(settings)
            session.add(family)
            session.flush()

            profile = FamilyBillingProfile(
                family_id=family.id,
                payment_method=BillingPaymentMethod.direct_debit,
                direct_debit_status=direct_debit_status,
                bank_code="0005",
                bank_name_kana="BANK",
                branch_code="123",
                branch_name_kana="BRANCH",
                account_type="1",
                account_number="7654321",
                account_holder_kana="TANAKA TARO",
                customer_number=create_customer_number("001", family.id),
                new_code="1",
            )
            cycle = BillingCycle(
                year_month="2026-04",
                period_start=date(2026, 4, 1),
                period_end=date(2026, 4, 30),
                withdrawal_date=date(2026, 5, 27),
                status=BillingCycleStatus.confirmed,
            )
            session.add(profile)
            session.add(cycle)
            session.flush()

            claim = BillingClaim(
                billing_cycle_id=cycle.id,
                family_id=family.id,
                payment_method=BillingPaymentMethod.direct_debit,
                total_amount=12345,
                status=BillingClaimStatus.confirmed,
            )
            session.add(claim)
            session.commit()
            return cycle.id, profile.customer_number

    def _zengin_client(self):
        app = FastAPI()
        app.include_router(zengin_router_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        def override_get_current_staff_user():
            return self.current_user

        app.dependency_overrides[zengin_router_module.get_session] = override_get_session
        app.dependency_overrides[zengin_router_module.get_current_staff_user] = override_get_current_staff_user
        return TestClient(app)

    def test_unique_constraints_for_year_month_and_customer_number(self):
        with Session(self.engine) as session:
            session.add(
                BillingCycle(
                    year_month="2026-04",
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 4, 30),
                    withdrawal_date=date(2026, 5, 27),
                )
            )
            session.add(
                BillingCycle(
                    year_month="2026-04",
                    period_start=date(2026, 4, 1),
                    period_end=date(2026, 4, 30),
                    withdrawal_date=date(2026, 5, 27),
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

        with Session(self.engine) as session:
            family_a = Family(family_name="A")
            family_b = Family(family_name="B")
            session.add(family_a)
            session.add(family_b)
            session.flush()
            session.add(
                FamilyBillingProfile(
                    family_id=family_a.id,
                    customer_number="00100000000000000001",
                )
            )
            session.add(
                FamilyBillingProfile(
                    family_id=family_b.id,
                    customer_number="00100000000000000001",
                )
            )
            with self.assertRaises(IntegrityError):
                session.commit()

    def test_zengin_export_requires_active_profile_and_outputs_n_customer_number(self):
        cycle_id, _ = self._seed_exportable_claim(direct_debit_status=DirectDebitStatus.paper_received)
        with Session(self.engine) as session:
            with self.assertRaisesRegex(ZenginError, "active"):
                create_zengin_export(session, cycle_id, created_by="tester")

        self.engine.dispose()
        self.setUp()
        cycle_id, customer_number = self._seed_exportable_claim()
        with Session(self.engine) as session:
            export = create_zengin_export(session, cycle_id, created_by="tester")
            file_bytes = build_zengin_file(session, export.id)
            records = file_bytes.split(b"\r\n")
            if records and records[-1] == b"":
                records = records[:-1]

            self.assertEqual(len(records), 4)
            self.assertTrue(all(len(record) == 120 for record in records))
            data_record = records[1].decode("cp932")
            self.assertEqual(data_record[91:111], customer_number)
            self.assertTrue(data_record[91:111].isdigit())

    def test_zengin_download_requires_admin(self):
        cycle_id, _ = self._seed_exportable_claim()
        with Session(self.engine) as session:
            export = create_zengin_export(session, cycle_id, created_by="tester")
            export_id = export.id

        client = self._zengin_client()
        self.current_user = StaffUser(role=Role.CAN_EDIT, name="一般職員")
        forbidden = client.get(f"/billing/zengin/exports/{export_id}/download")
        self.assertEqual(forbidden.status_code, 403)

        with Session(self.engine) as session:
            export = session.get(ZenginExport, export_id)
            self.assertEqual(export.status, ZenginExportStatus.created)

        self.current_user = StaffUser(role=Role.ADMIN, name="園長")
        allowed = client.get(f"/billing/zengin/exports/{export_id}/download")
        self.assertEqual(allowed.status_code, 200)

        with Session(self.engine) as session:
            export = session.get(ZenginExport, export_id)
            self.assertEqual(export.status, ZenginExportStatus.created)

        submitted = client.post(f"/billing/zengin/exports/{export_id}/mark-submitted")
        self.assertEqual(submitted.status_code, 200)
        with Session(self.engine) as session:
            export = session.get(ZenginExport, export_id)
            self.assertEqual(export.status, ZenginExportStatus.submitted)

        client.close()

    def test_result_parser_removes_crlf_before_record_validation_and_checks_trailer(self):
        cycle_id, customer_number = self._seed_exportable_claim()
        with Session(self.engine) as session:
            export = create_zengin_export(session, cycle_id, created_by="tester")
            line = session.exec(select(ZenginExportLine)).first()
            result_record = ParsedResultRecord(customer_number=customer_number, amount=12345, result_code="0")
            records = [
                build_header_record(export.settings_snapshot, export.withdrawal_date),
                build_data_record(line),
                build_trailer_record([line], result_records=[result_record]),
                build_end_record(),
            ]
            file_bytes = build_file_bytes(records, "cp932", "CRLF")

            mark_zengin_export_submitted(session, export.id)

            parsed = parse_result_file(session, file_bytes, export.id)

            self.assertEqual(parsed.errors, [])
            self.assertEqual(len(parsed.records), 1)

            cr_only_file = file_bytes.replace(b"\r\n", b"\r")
            with self.assertRaisesRegex(ZenginError, "CR"):
                parse_result_file(session, cr_only_file, export.id)

            bad_records = records.copy()
            bad_records[2] = build_trailer_record([], result_records=[])
            bad_file = build_file_bytes(bad_records, "cp932", "CRLF")
            parsed_bad = parse_result_file(session, bad_file, export.id)
            self.assertTrue(any("トレーラー" in error for error in parsed_bad.errors))

    def test_supersede_restores_only_new_code_owned_by_original_export(self):
        cycle_id, _ = self._seed_exportable_claim()
        with Session(self.engine) as session:
            original = create_zengin_export(session, cycle_id, created_by="tester")
            original_id = original.id
            mark_zengin_export_submitted(session, original_id)

            profile = session.exec(select(FamilyBillingProfile)).one()
            self.assertEqual(profile.new_code, "0")
            self.assertEqual(profile.new_code_consumed_by_export_id, original_id)

            replacement = supersede_zengin_export(
                session,
                original_id,
                reason="口座情報を訂正",
                created_by="tester",
            )
            replacement_id = replacement.id

        with Session(self.engine) as session:
            original = session.get(ZenginExport, original_id)
            replacement = session.get(ZenginExport, replacement_id)
            profile = session.exec(select(FamilyBillingProfile)).one()
            claim = session.exec(select(BillingClaim)).one()
            self.assertEqual(original.status, ZenginExportStatus.superseded)
            self.assertEqual(original.superseded_by_export_id, replacement_id)
            self.assertEqual(replacement.status, ZenginExportStatus.created)
            self.assertEqual(profile.new_code, "1")
            self.assertIsNone(profile.new_code_consumed_by_export_id)
            self.assertEqual(claim.zengin_export_id, replacement_id)

    def test_invalid_result_file_returns_422_without_importing(self):
        cycle_id, _ = self._seed_exportable_claim()
        with Session(self.engine) as session:
            export = create_zengin_export(session, cycle_id, created_by="tester")
            export_id = export.id
            mark_zengin_export_submitted(session, export_id)

        client = self._zengin_client()
        response = client.post(
            f"/billing/zengin/exports/{export_id}/results",
            files={"file": ("result.txt", b"\x81" * 120, "application/octet-stream")},
        )
        self.assertEqual(response.status_code, 422)
        with Session(self.engine) as session:
            export = session.get(ZenginExport, export_id)
            self.assertEqual(export.status, ZenginExportStatus.submitted)
            self.assertIsNone(export.result_imported_at)
        client.close()

    def test_proration_rounding_and_negative_amount_validation(self):
        rule = MealFeeRule(
            name="月額",
            calculation_type="monthly_fixed",
            monthly_amount=10000,
            proration_policy=MealFeeProrationPolicy.daily_by_enrolled_days,
            proration_rounding=ProrationRounding.round,
            valid_from=date(2026, 4, 1),
        )
        self.assertEqual(rule.proration_rounding, ProrationRounding.round)
        self.assertEqual(apply_proration_rounding(Decimal("100.5"), ProrationRounding.round), 101)
        self.assertEqual(apply_proration_rounding(Decimal("100.9"), ProrationRounding.floor), 100)
        self.assertEqual(apply_proration_rounding(Decimal("100.1"), ProrationRounding.ceil), 101)

        validate_charge_amount(BillingChargeSourceType.adjustment, -500)
        validate_charge_amount(BillingChargeSourceType.manual, -500)
        with self.assertRaises(BillingCalculationError):
            validate_charge_amount(BillingChargeSourceType.meal_auto, -500)


class BillingAccountPermissionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        with Session(self.engine) as session:
            admin = User(
                email="billing-admin@example.com",
                display_name="園長",
                staff_role="admin",
            )
            office = User(
                email="billing-office@example.com",
                display_name="事務",
                staff_role="can_edit",
                can_manage_billing_accounts=True,
            )
            teacher = User(
                email="billing-teacher@example.com",
                display_name="担任",
                staff_role="can_edit",
            )
            viewer = User(
                email="billing-viewer@example.com",
                display_name="閲覧職員",
                staff_role="view_only",
                can_manage_billing_accounts=True,
            )
            family = Family(family_name="請求権限テスト家族")
            session.add_all([admin, office, teacher, viewer, family])
            session.flush()
            child = Child(
                last_name="請求",
                first_name="花子",
                last_name_kana="セイキュウ",
                first_name_kana="ハナコ",
                birth_date=date(2021, 4, 1),
                enrollment_date=date(2024, 4, 1),
                status=ChildStatus.enrolled,
                family_id=family.id,
            )
            cycle = BillingCycle(
                year_month="2026-08",
                period_start=date(2026, 8, 1),
                period_end=date(2026, 8, 31),
                withdrawal_date=date(2026, 9, 27),
                status=BillingCycleStatus.confirmed,
            )
            profile = FamilyBillingProfile(
                family_id=family.id,
                payment_method=BillingPaymentMethod.direct_debit,
                direct_debit_status=DirectDebitStatus.active,
                bank_code="0005",
                bank_name_kana="SECRET BANK",
                branch_code="123",
                branch_name_kana="SECRET BRANCH",
                account_type="1",
                account_number="7654321",
                account_holder_kana="SECRET HOLDER",
                customer_number="00100000000000009999",
                new_code="1",
                note="SECRET NOTE",
            )
            session.add_all([child, cycle, profile])
            session.commit()
            self.admin_id = admin.id
            self.office_id = office.id
            self.teacher_id = teacher.id
            self.viewer_id = viewer.id
            self.child_id = child.id
            self.cycle_id = cycle.id
            self.profile_id = profile.id

        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="担任",
            user_id=self.teacher_id,
        )
        self.app = FastAPI()
        self.app.include_router(billing_router_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[billing_router_module.get_session] = override_get_session
        self.app.dependency_overrides[billing_router_module.get_current_staff_user] = (
            lambda: self.current_user
        )
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    @property
    def page_url(self):
        return f"/billing/cycles/{self.cycle_id}/child-charges/{self.child_id}"

    @property
    def update_url(self):
        return f"{self.page_url}/profile"

    @staticmethod
    def _profile_form_data(**overrides):
        values = {
            "payment_method": "direct_debit",
            "direct_debit_status": "active",
            "bank_code": "0005",
            "bank_name_kana": "UPDATED BANK",
            "branch_code": "123",
            "branch_name_kana": "UPDATED BRANCH",
            "account_type": "1",
            "account_number": "1111222",
            "account_holder_kana": "UPDATED HOLDER",
            "new_code": "2",
            "mandate_received_on": "2026-08-11",
            "note": "更新済み",
        }
        values.update(overrides)
        return values

    def test_teacher_cannot_see_sensitive_account_fields_or_update_profile(self):
        page = self.client.get(self.page_url)

        self.assertEqual(page.status_code, 200)
        self.assertIn("口座情報は管理者または請求・口座情報管理権限を持つ職員が管理します。", page.text)
        self.assertIn("登録済み", page.text)
        self.assertNotIn("SECRET BANK", page.text)
        self.assertNotIn("7654321", page.text)
        self.assertNotIn("SECRET HOLDER", page.text)
        self.assertNotIn("SECRET NOTE", page.text)
        self.assertNotIn('name="account_number"', page.text)

        response = self.client.post(
            self.update_url,
            data=self._profile_form_data(),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 403)
        with Session(self.engine) as session:
            profile = session.get(FamilyBillingProfile, self.profile_id)
            logs = session.exec(select(FamilyBillingProfileChangeLog)).all()
        self.assertEqual(profile.account_number, "7654321")
        self.assertEqual(logs, [])

    def test_office_can_edit_profile_and_change_is_audited(self):
        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="事務",
            user_id=self.office_id,
        )
        page = self.client.get(self.page_url)

        self.assertEqual(page.status_code, 200)
        self.assertIn('name="account_number"', page.text)
        self.assertIn("SECRET HOLDER", page.text)

        response = self.client.post(
            self.update_url,
            data=self._profile_form_data(),
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)
        with Session(self.engine) as session:
            profile = session.get(FamilyBillingProfile, self.profile_id)
            log = session.exec(select(FamilyBillingProfileChangeLog)).one()
        self.assertEqual(profile.account_number, "1111222")
        self.assertEqual(log.changed_by_user_id, self.office_id)
        self.assertIn("account_number", log.changed_fields)
        self.assertIn("account_holder_kana", log.changed_fields)

    def test_account_management_navigation_is_visible_only_to_authorized_staff(self):
        teacher_dashboard = self.client.get("/billing/")
        teacher_accounts = self.client.get("/billing/accounts")
        self.assertEqual(teacher_dashboard.status_code, 200)
        self.assertNotIn('href="/billing/accounts"', teacher_dashboard.text)
        self.assertEqual(teacher_accounts.status_code, 403)

        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="事務",
            user_id=self.office_id,
        )
        office_dashboard = self.client.get("/billing/")
        office_accounts = self.client.get("/billing/accounts")

        self.assertEqual(office_dashboard.status_code, 200)
        self.assertIn('href="/billing/accounts"', office_dashboard.text)
        self.assertEqual(office_accounts.status_code, 200)
        self.assertIn("口座情報管理", office_accounts.text)
        self.assertIn("請求 花子", office_accounts.text)
        self.assertIn(
            f'/billing/cycles/{self.cycle_id}/child-charges/{self.child_id}#account-profile',
            office_accounts.text,
        )

        child_page = self.client.get(self.page_url)
        self.assertIn('id="account-profile"', child_page.text)
        self.assertIn("口座情報一覧へ戻る", child_page.text)

    def test_admin_has_implicit_permission_and_revocation_is_immediate(self):
        self.current_user = StaffUser(
            role=Role.ADMIN,
            name="園長",
            user_id=self.admin_id,
        )
        admin_page = self.client.get(self.page_url)
        self.assertEqual(admin_page.status_code, 200)
        self.assertIn('name="account_number"', admin_page.text)

        self.current_user = StaffUser(
            role=Role.CAN_EDIT,
            name="事務",
            user_id=self.office_id,
        )
        allowed_page = self.client.get(self.page_url)
        self.assertIn('name="account_number"', allowed_page.text)

        with Session(self.engine) as session:
            office = session.get(User, self.office_id)
            office.can_manage_billing_accounts = False
            session.add(office)
            session.commit()

        revoked_page = self.client.get(self.page_url)
        revoked_update = self.client.post(
            self.update_url,
            data=self._profile_form_data(),
            follow_redirects=False,
        )
        self.assertEqual(revoked_page.status_code, 200)
        self.assertNotIn('name="account_number"', revoked_page.text)
        self.assertEqual(revoked_update.status_code, 403)

    def test_view_only_never_gets_business_permission(self):
        self.current_user = StaffUser(
            role=Role.VIEW_ONLY,
            name="閲覧職員",
            user_id=self.viewer_id,
        )

        page = self.client.get(self.page_url)
        update = self.client.post(
            self.update_url,
            data=self._profile_form_data(),
            follow_redirects=False,
        )

        self.assertEqual(page.status_code, 200)
        self.assertNotIn('name="account_number"', page.text)
        self.assertEqual(update.status_code, 403)


if __name__ == "__main__":
    unittest.main()
