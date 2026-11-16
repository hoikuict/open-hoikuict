from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlmodel import Session, SQLModel, create_engine, select

from auth import Role, StaffUser
import database
from models import (BillingChargeLine, BillingChargeSourceType, BillingClaim, BillingClaimStatus,
                    BillingCycle, BillingCycleStatus, Child, ChildStatus, FamilyBillingProfile,
                    FeeItem, User, ZenginExport, ZenginExportLine, ZenginExportStatus)
import routers.billing as billing
import routers.zengin as zengin
import test_billing_zengin as fixtures
from time_utils import utc_now
from zengin_service import (ZenginError, cancel_zengin_export_for_edit,
                            create_zengin_export, mark_zengin_export_submitted,
                            supersede_zengin_export)


class BillingReopenTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.BillingZenginTests()
        self.fixture.setUp()
        self.engine = self.fixture.engine
        self.user = StaffUser(role=Role.ADMIN, name='確認用管理者')
        self.cycle_id, _ = self.fixture._seed_exportable_claim()
        with Session(self.engine) as session:
            admin = User(email='billing-reopen@example.invalid', display_name='確認用管理者', staff_role='admin')
            session.add(admin)
            session.flush()
            self.user = StaffUser(role=Role.ADMIN, name=admin.display_name, user_id=admin.id)
            claim = session.exec(select(BillingClaim)).one()
            claim.total_amount = 300
            child = Child(last_name='見本', first_name='はる', last_name_kana='ミホン', first_name_kana='ハル',
                          birth_date=date(2022, 4, 1), enrollment_date=date(2025, 4, 1),
                          status=ChildStatus.enrolled, family_id=claim.family_id)
            session.add(child)
            fee = FeeItem(code='temp_photo', name='写真代', category='temporary', charge_unit='child', default_amount=0)
            session.add(fee)
            session.flush()
            session.add(BillingChargeLine(billing_claim_id=claim.id, fee_item_id=fee.id,
                child_id=child.id, source_type=BillingChargeSourceType.manual,
                description='写真代', quantity=1, unit_price=300, amount=300))
            session.add(claim)
            session.commit()
            self.child_id, self.claim_id = child.id, claim.id
            self.export_id = create_zengin_export(session, self.cycle_id, created_by='fixture').id
        app = FastAPI()
        app.include_router(billing.router)
        app.include_router(zengin.router)

        def get_session():
            with Session(self.engine) as session:
                yield session

        app.dependency_overrides[billing.get_session] = get_session
        app.dependency_overrides[billing.get_current_staff_user] = lambda: self.user
        self.client = TestClient(app)

    def tearDown(self):
        self.client.close()
        self.fixture.tearDown()

    def cancel(self, session, **changes):
        args = dict(reason='写真代を訂正', confirmed_unsubmitted=True, canceled_by=self.user.name)
        args.update(changes)
        return cancel_zengin_export_for_edit(session, self.export_id, **args)

    def test_cancel_edit_recreate_preserves_snapshot_and_audit(self):
        with Session(self.engine) as session:
            old = session.get(ZenginExport, self.export_id)
            content_hash, snapshot = old.content_hash, dict(old.settings_snapshot)
            line = session.exec(select(ZenginExportLine)).one()
            bank = dict(line.bank_snapshot)
            profile = session.exec(select(FamilyBillingProfile)).one()
            original_code = profile.new_code
            self.cancel(session)
            self.assertEqual(old.status, ZenginExportStatus.canceled)
            self.assertEqual(old.canceled_reason, '写真代を訂正')
            self.assertEqual(old.canceled_by, self.user.name)
            self.assertIsNotNone(old.canceled_at)
            self.assertEqual(old.content_hash, content_hash)
            self.assertEqual(old.settings_snapshot, snapshot)
            self.assertEqual(line.bank_snapshot, bank)
            self.assertEqual(line.amount, 300)
            self.assertEqual(profile.new_code, original_code)
            claim = session.get(BillingClaim, self.claim_id)
            self.assertEqual(claim.status, BillingClaimStatus.confirmed)
            self.assertIsNone(claim.zengin_export_id)
            self.assertIsNone(claim.exported_at)
            self.assertEqual(claim.total_amount, 300)
        edited = self.client.post(f'/billing/cycles/{self.cycle_id}/child-charges/table',
            data={f'amount_temp_photo_{self.child_id}': '500'}, follow_redirects=False)
        self.assertEqual(edited.status_code, 303)
        with Session(self.engine) as session:
            new = create_zengin_export(session, self.cycle_id, created_by=self.user.name)
            self.assertNotEqual(new.id, self.export_id)
            self.assertEqual(new.total_amount, 500)
            self.assertNotEqual(new.content_hash, content_hash)
            self.assertEqual(session.get(ZenginExport, self.export_id).total_amount, 300)
            self.assertEqual(session.get(BillingClaim, self.claim_id).zengin_export_id, new.id)
            with self.assertRaises(ZenginError):
                self.cancel(session)
            self.assertEqual(session.get(BillingClaim, self.claim_id).zengin_export_id, new.id)

    def test_reason_and_actual_unsubmitted_confirmation_are_required(self):
        with Session(self.engine) as session:
            for args in ({'reason':''}, {'reason':'  '}, {'reason':'長'*501}, {'confirmed_unsubmitted':False}):
                with self.subTest(args=args), self.assertRaises(ZenginError):
                    self.cancel(session, **args)
                self.assertEqual(session.get(ZenginExport, self.export_id).status, ZenginExportStatus.created)
                self.assertEqual(session.get(BillingCycle, self.cycle_id).status, BillingCycleStatus.exported)

    def test_all_ineligible_states_are_rejected(self):
        with Session(self.engine) as session:
            for status in (ZenginExportStatus.submitted, ZenginExportStatus.result_imported,
                           ZenginExportStatus.superseded, ZenginExportStatus.canceled):
                item = session.get(ZenginExport, self.export_id)
                item.status = status
                session.add(item)
                session.commit()
                with self.subTest(status=status), self.assertRaises(ZenginError):
                    self.cancel(session)
                self.assertEqual(session.get(BillingClaim, self.claim_id).status, BillingClaimStatus.exported)

    def test_submission_timestamp_blocks_inconsistent_created_state(self):
        with Session(self.engine) as session:
            item = session.get(ZenginExport, self.export_id)
            item.submitted_at = utc_now()
            session.add(item)
            session.commit()
            with self.assertRaises(ZenginError):
                self.cancel(session)

    def test_superseding_a_submitted_file_does_not_make_cycle_unsubmitted(self):
        with Session(self.engine) as session:
            mark_zengin_export_submitted(session, self.export_id)
            replacement = supersede_zengin_export(session, self.export_id, reason='口座訂正', created_by='fixture')
            with self.assertRaises(ZenginError):
                cancel_zengin_export_for_edit(session, replacement.id, reason='金額訂正',
                    confirmed_unsubmitted=True, canceled_by='fixture')
            self.assertEqual(session.get(BillingCycle, self.cycle_id).status, BillingCycleStatus.exported)
        self.assertNotIn('data-reopen-export=', self.client.get('/billing/').text)

    def test_paid_claim_or_changed_link_is_not_reopened(self):
        with Session(self.engine) as session:
            claim = session.get(BillingClaim, self.claim_id)
            for key, value in [('status', BillingClaimStatus.paid), ('zengin_export_id', None), ('total_amount', 500)]:
                original = getattr(claim, key)
                setattr(claim, key, value)
                session.add(claim)
                session.commit()
                with self.subTest(key=key), self.assertRaises(ZenginError):
                    self.cancel(session)
                self.assertEqual(session.get(ZenginExport, self.export_id).status, ZenginExportStatus.created)
                setattr(claim, key, original)
                session.add(claim)
                session.commit()

    def test_newer_export_or_multiple_active_exports_block_cancel(self):
        with Session(self.engine) as session:
            original = session.get(ZenginExport, self.export_id)
            newer = ZenginExport(billing_cycle_id=self.cycle_id, withdrawal_date=original.withdrawal_date,
                                file_name='fixture.txt', status=ZenginExportStatus.created,
                                content_hash='fixture', created_by='fixture')
            session.add(newer)
            session.commit()
            with self.assertRaises(ZenginError):
                self.cancel(session)
            newer.status = ZenginExportStatus.canceled
            session.add(newer)
            session.commit()
            with self.assertRaises(ZenginError):
                self.cancel(session)

    def test_commit_failure_rolls_back_every_change(self):
        with Session(self.engine) as session:
            with patch.object(session, 'commit', side_effect=RuntimeError('injected failure')):
                with self.assertRaises(RuntimeError):
                    self.cancel(session)
            item = session.get(ZenginExport, self.export_id)
            self.assertEqual(item.status, ZenginExportStatus.created)
            self.assertIsNone(item.canceled_at)
            self.assertIsNone(item.canceled_reason)
            self.assertEqual(session.get(BillingClaim, self.claim_id).zengin_export_id, self.export_id)
            self.assertEqual(session.get(BillingCycle, self.cycle_id).status, BillingCycleStatus.exported)

    def test_canceled_export_cannot_be_reused_via_direct_urls(self):
        with Session(self.engine) as session:
            self.cancel(session)
        prefix = f'/billing/zengin/exports/{self.export_id}'
        self.assertEqual(self.client.get(prefix+'/download').status_code, 400)
        for suffix, data in [('/mark-submitted', {}), ('/supersede', {'reason':'やり直し'}),
                             ('/cancel', {'reason':'再実行', 'confirmed_unsubmitted':'true'})]:
            with self.subTest(suffix=suffix):
                self.assertEqual(self.client.post(prefix+suffix, data=data).status_code, 409)
        result = self.client.post(prefix+'/results', files={'file':('result.txt', b'invalid', 'text/plain')})
        self.assertEqual(result.status_code, 400)
        dashboard = self.client.get('/billing/').text
        self.assertNotIn(f'href="{prefix}/download"', dashboard)
        self.assertIn('写真代を訂正', dashboard)
        self.assertIn(self.user.name, dashboard)

    def test_admin_only_for_ui_and_api(self):
        for role in (Role.CAN_EDIT, Role.VIEW_ONLY):
            self.user = StaffUser(role=role, name='確認用職員')
            for suffix in ('cancel', 'cancel-ui'):
                response = self.client.post(f'/billing/zengin/exports/{self.export_id}/{suffix}',
                    data={'reason':'訂正', 'confirmed_unsubmitted':'true'})
                self.assertEqual(response.status_code, 403)
            self.assertNotIn('data-reopen-export=', self.client.get('/billing/').text)

    def test_ui_error_keeps_reason_and_ui_success_returns_to_same_month(self):
        url = f'/billing/zengin/exports/{self.export_id}/cancel-ui'
        error = self.client.post(url, data={'reason':'写真代を訂正'}, follow_redirects=False)
        self.assertEqual(error.status_code, 409)
        self.assertEqual(error.context['reopen_initial']['reason'], '写真代を訂正')
        self.assertFalse(error.context['reopen_initial']['checked'])
        success = self.client.post(url, data={'reason':'写真代を訂正', 'confirmed_unsubmitted':'true'}, follow_redirects=False)
        self.assertEqual(success.status_code, 303)
        self.assertTrue(success.headers['location'].startswith(f'/billing/cycles/{self.cycle_id}/child-charges?'))

    def test_table_error_keeps_all_entered_values_without_saving(self):
        with Session(self.engine) as session:
            self.cancel(session)
        response = self.client.post(f'/billing/cycles/{self.cycle_id}/child-charges/table', data={
            f'amount_monthly_meal_{self.child_id}':'4500', f'amount_temp_photo_{self.child_id}':'300.5'})
        self.assertEqual(response.status_code, 400)
        amounts = response.context['table_rows'][0]['amounts']
        self.assertEqual(amounts['monthly_meal'], '4500')
        self.assertEqual(amounts['temp_photo'], '300.5')
        with Session(self.engine) as session:
            self.assertEqual(session.get(BillingClaim, self.claim_id).total_amount, 300)
            self.assertEqual(len(session.exec(select(BillingChargeLine)).all()), 1)

    def test_locked_transferred_line_is_still_locked_after_reopen(self):
        with Session(self.engine) as session:
            line = session.exec(select(BillingChargeLine)).one()
            line.is_locked = True
            line.source_type = BillingChargeSourceType.extension_auto
            session.add(line)
            session.commit()
            self.cancel(session)
        response = self.client.post(f'/billing/cycles/{self.cycle_id}/child-charges/table',
                                    data={f'amount_temp_photo_{self.child_id}':'500'})
        self.assertEqual(response.status_code, 400)
        with Session(self.engine) as session:
            self.assertEqual(session.exec(select(BillingChargeLine)).one().amount, 300)


class BillingReopenMigrationAndRaceTests(unittest.TestCase):
    def test_old_database_adds_nullable_audit_columns_idempotently(self):
        with tempfile.TemporaryDirectory() as tmp:
            engine = create_engine('sqlite:///'+str(Path(tmp)/'migration.db'))
            try:
                with engine.begin() as conn:
                    conn.execute(text('CREATE TABLE zengin_exports (id INTEGER PRIMARY KEY, status VARCHAR, canceled_reason VARCHAR)'))
                    conn.execute(text("INSERT INTO zengin_exports VALUES (1, 'created', NULL)"))
                with patch.object(database, 'engine', engine):
                    database._migrate_zengin_workflow()
                    database._migrate_zengin_workflow()
                with engine.connect() as conn:
                    row = conn.execute(text('SELECT status, canceled_reason, canceled_by, canceled_at FROM zengin_exports')).one()
                    self.assertEqual(tuple(row), ('created', None, None, None))
            finally:
                engine.dispose()

    def test_concurrent_cancel_submit_supersede_and_creation(self):
        for other in ('cancel', 'submit', 'supersede', 'create'):
            with self.subTest(other=other), tempfile.TemporaryDirectory() as tmp:
                engine = create_engine('sqlite:///'+str(Path(tmp)/'race.db'), connect_args={'check_same_thread':False, 'timeout':15})
                SQLModel.metadata.create_all(engine)
                fixture = fixtures.BillingZenginTests()
                fixture.engine = engine
                cycle_id, _ = fixture._seed_exportable_claim()
                with Session(engine) as session:
                    export_id = create_zengin_export(session, cycle_id, created_by='fixture').id
                    if other == 'create':
                        cancel_zengin_export_for_edit(session, export_id, reason='訂正', confirmed_unsubmitted=True, canceled_by='fixture')
                barrier = Barrier(2)

                def work(operation):
                    with Session(engine) as session:
                        # Deliberately keep stale instances in both identity maps.
                        held = (session.get(ZenginExport, export_id), session.get(BillingCycle, cycle_id))
                        assert all(held)
                        barrier.wait(timeout=10)
                        try:
                            if operation == 'cancel':
                                cancel_zengin_export_for_edit(session, export_id, reason='訂正', confirmed_unsubmitted=True, canceled_by='fixture')
                            elif operation == 'submit':
                                mark_zengin_export_submitted(session, export_id)
                            elif operation == 'supersede':
                                supersede_zengin_export(session, export_id, reason='訂正', created_by='fixture')
                            else:
                                create_zengin_export(session, cycle_id, created_by='fixture')
                            return 'ok'
                        except ZenginError:
                            return 'rejected'

                try:
                    with ThreadPoolExecutor(max_workers=2) as pool:
                        first = pool.submit(work, 'create' if other == 'create' else 'cancel')
                        second = pool.submit(work, other)
                        results = [first.result(timeout=20), second.result(timeout=20)]
                    self.assertEqual(sorted(results), ['ok', 'rejected'])
                    with Session(engine) as session:
                        active = session.exec(select(ZenginExport).where(ZenginExport.status.in_([ZenginExportStatus.created, ZenginExportStatus.submitted]))).all()
                        cycle = session.get(BillingCycle, cycle_id)
                        claim = session.exec(select(BillingClaim)).one()
                        self.assertLessEqual(len(active), 1)
                        if active:
                            self.assertEqual(cycle.status, BillingCycleStatus.exported)
                            self.assertEqual(claim.zengin_export_id, active[0].id)
                        else:
                            self.assertEqual(cycle.status, BillingCycleStatus.confirmed)
                            self.assertIsNone(claim.zengin_export_id)
                finally:
                    engine.dispose()
