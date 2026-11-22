import os
import re
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlmodel import SQLModel, Session, create_engine, select
from auth import Role, StaffUser, get_current_staff_user
from csrf import CsrfTokenMiddleware
from database import get_session
from models import (Child, Classroom, ParentAccount, DailyContactEntry, AttendanceVerification, AttendanceVerificationHistory,
                    Message, AttendanceVerificationStatus, ParentPushDeliveryAttemptResult)
from class_kiosk.router import router, admin_router, KioskResponseHeaders
from class_kiosk.models import KioskAccount, KioskAudit, KioskDevice, KioskEnrollment, KioskChange, KioskSubscription, KioskDelivery, KioskOperation
from class_kiosk import push
from time_utils import utc_now, local_today


class ClassKioskTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"HOIKUICT_ENV":"test", "HOIKUICT_CLASS_KIOSK_ENABLED":"1", "HOIKUICT_CLASS_KIOSK_NETWORKS":"127.0.0.1/32",
            "HOIKUICT_CSRF_ENFORCE":"1", "HOIKUICT_COOKIE_SECURE":"1", "HOIKUICT_SECRET_KEY":"kiosk-tests-" * 8, "HOIKUICT_CLASS_KIOSK_PUSH":"webpush", "HOIKUICT_CLASS_KIOSK_VAPID_PUBLIC_KEY":"testing"})
        self.env.start()
        self.temp = tempfile.TemporaryDirectory()
        self.engine = create_engine("sqlite:///"+str(Path(self.temp.name)/"test.db"), connect_args={"check_same_thread":False})
        SQLModel.metadata.create_all(self.engine)
        self.app = FastAPI()
        self.app.add_middleware(CsrfTokenMiddleware)
        self.app.add_middleware(KioskResponseHeaders)
        self.app.include_router(router)
        self.app.include_router(admin_router)
        def sessions():
            with Session(self.engine) as session:
                yield session
        self.user = StaffUser(role=Role.ADMIN, name="テスト管理者")
        self.app.dependency_overrides[get_session]=sessions
        self.app.dependency_overrides[get_current_staff_user]=lambda:self.user
        self.client = TestClient(self.app, base_url="https://testserver", client=("127.0.0.1",50000))
        html=self.client.get("/class-kiosk/").text
        self.headers={"X-CSRF-Token":re.search(r'name="csrf-token" content="([^"]+)"',html)[1]}
        with Session(self.engine) as session:
            session.add_all([Classroom(id=1,name="ひよこ組"),Classroom(id=2,name="別クラス")]);session.flush()
            for i in range(1,4):
                session.add(Child(id=i,last_name="テスト",first_name=str(i),last_name_kana="テスト",first_name_kana=str(i),birth_date=date(2024,1,1),enrollment_date=date(2026,4,1),classroom_id=1 if i<3 else 2))
            session.add(ParentAccount(id=1, display_name="保護者",email="kiosk@example.invalid"))
            session.commit()
        self.code=self.issue()
        self.assertEqual(self.post("/class-kiosk/enroll",{"code":self.code}).status_code,200)

    def tearDown(self):
        self.client.close();self.engine.dispose();self.temp.cleanup();self.env.stop()

    def post(self,path,data):
        return self.client.post(path,json=data,headers=self.headers)

    def issue(self):
        response=self.post("/settings/class-kiosk/enrollments",{"classroom_id":1,"name":"共用スマホ"})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()["code"]

    def state(self):
        response=self.client.get("/class-kiosk/api/state")
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_existing_registration_has_no_expiry_and_cookie_is_renewed(self):
        from class_kiosk.security import DEVICE_COOKIE_SECONDS, cookie_name
        with Session(self.engine) as session:
            device = session.get(KioskDevice, 1)
            device.expires_at = utc_now()-timedelta(days=800)
            session.add(device); session.commit()
            legacy_expiry = device.expires_at
        token = self.client.cookies.get(cookie_name())
        with patch.dict(os.environ, {"HOIKUICT_CLASS_KIOSK_SESSION_DAYS":"1"}):
            response = self.client.get('/class-kiosk/api/state')
        self.assertEqual(response.status_code, 200)
        cookie = response.headers['set-cookie']
        for part in ('HttpOnly', 'Secure', 'SameSite=strict', 'Path=/', f'Max-Age={DEVICE_COOKIE_SECONDS}'):
            self.assertIn(part, cookie)
        self.assertEqual(self.client.cookies.get(cookie_name()), token)
        with Session(self.engine) as session:
            self.assertEqual(session.get(KioskDevice, 1).expires_at, legacy_expiry)
        self.post('/settings/class-kiosk/devices/1/revoke', {})
        response = self.client.get('/class-kiosk/api/state')
        self.assertEqual(response.status_code, 401)
        self.assertNotIn(cookie_name()+'=', response.headers.get('set-cookie', ''))

    def test_new_registration_remains_valid_years_later_but_revocation_does_not(self):
        from class_kiosk.security import authenticate
        from class_kiosk import security
        code = self.issue()
        self.assertEqual(self.post('/class-kiosk/enroll', {'code':code}).status_code, 200)
        with Session(self.engine) as session:
            device = session.exec(select(KioskDevice).order_by(KioskDevice.id.desc())).first()
            token_hash, device_id = device.token_hash, device.id
            with patch.object(security, 'utc_now', return_value=utc_now()+timedelta(days=3650)):
                self.assertEqual(authenticate(session, token_hash).device_id, device_id)
        self.post(f'/settings/class-kiosk/devices/{device_id}/revoke', {})
        with Session(self.engine) as session, patch.object(security, 'utc_now', return_value=utc_now()+timedelta(days=7300)):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as error:
                authenticate(session, token_hash)
            self.assertEqual(error.exception.status_code, 401)
            self.assertFalse(session.get(KioskDevice, device_id).active)

    def test_admin_inventory_uses_all_classes_order_and_current_subscriptions(self):
        with Session(self.engine) as session:
            first=session.get(Classroom,1); first.display_order=10; session.add(first)
            session.add(Classroom(id=3,name='追加クラス',display_order=0))
            account=KioskAccount(classroom_id=2); session.add(account); session.flush()
            session.add(KioskDevice(account_id=account.id,name='解除済み',token_hash='revoked-test',active=False))
            session.add(KioskSubscription(device_id=1,endpoint='https://fcm.googleapis.com/secret-endpoint',p256dh_key='secret-key',auth_key='secret-auth'))
            session.commit()
        response=self.client.get('/settings/class-kiosk/api')
        data=response.json()
        self.assertEqual([c['id'] for c in data['classrooms']], [3,2,1])
        self.assertEqual([(d['classroom_id'],d['available'],d['push_enabled']) for d in data['devices']],[(1,True,True),(2,False,False)])
        for secret in ('secret-endpoint','secret-key','secret-auth','token_hash','expires_at',self.code):
            self.assertNotIn(secret,response.text)
        with Session(self.engine) as session:
            sub=session.get(KioskSubscription,1); sub.active=False; session.add(sub); session.commit()
        self.assertFalse(self.client.get('/settings/class-kiosk/api').json()['devices'][0]['push_enabled'])

    def test_registration_status_tracks_real_enrollment_and_ten_minute_boundary(self):
        from class_kiosk import router as routes, security
        from time_utils import ensure_utc
        with patch.dict(os.environ, {'HOIKUICT_CLASS_KIOSK_ORIGIN':'https://kiosk.example.invalid'}):
            result=self.post('/settings/class-kiosk/enrollments',{'classroom_id':2,'name':' 新スマホ '}).json()
        self.assertTrue(result['qr'].startswith('data:image/png;base64,'))
        path=f'/settings/class-kiosk/enrollments/{result["id"]}'
        pending=self.client.get(path).json()
        self.assertEqual(pending['status'],'pending')
        self.assertEqual(pending['name'],'新スマホ')
        self.assertNotIn('code',pending); self.assertNotIn('qr',pending)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(KioskDevice)).all()),1)
            expiry=ensure_utc(session.get(KioskEnrollment,result['id']).expires_at)
        with patch.object(routes,'utc_now',return_value=expiry),patch.object(security,'utc_now',return_value=expiry):
            self.assertEqual(self.client.get(path).json()['status'],'expired')
            self.assertEqual(self.post('/class-kiosk/enroll',{'code':result['code']}).status_code,400)
        another=self.post('/settings/class-kiosk/enrollments',{'classroom_id':2,'name':'別スマホ'}).json()
        self.assertEqual(self.post('/class-kiosk/enroll',{'code':another['code']}).status_code,200)
        self.assertEqual(self.client.get(f'/settings/class-kiosk/enrollments/{another["id"]}').json()['status'],'used')
        self.assertEqual(self.post('/class-kiosk/enroll',{'code':another['code']}).status_code,400)
        self.assertEqual(self.state()['class_name'],'別クラス')

    def test_admin_mutations_require_admin_csrf_and_valid_fields(self):
        for body in ({'classroom_id':999,'name':'端末'},{'classroom_id':1,'name':'   '},{'classroom_id':1,'name':'名'*81}):
            self.assertEqual(self.post('/settings/class-kiosk/enrollments',body).status_code,422)
        for path,body in [('/settings/class-kiosk/enrollments',{'classroom_id':1,'name':'端末'}),('/settings/class-kiosk/devices/1/revoke',{})]:
            self.assertEqual(self.client.post(path,json=body).status_code,403)
        self.user=StaffUser(role=Role.VIEW_ONLY,name='閲覧者')
        for path in ('/settings/class-kiosk/','/settings/class-kiosk/api','/settings/class-kiosk/enrollments/1'):
            self.assertEqual(self.client.get(path).status_code,403)
        self.assertEqual(self.post('/settings/class-kiosk/devices/1/revoke',{}).status_code,403)
        self.assertEqual(self.post('/settings/class-kiosk/enrollments',{'classroom_id':1,'name':'端末'}).status_code,403)
        with Session(self.engine) as session:
            self.assertTrue(session.get(KioskDevice,1).active)
            self.assertEqual(len(session.exec(select(KioskEnrollment)).all()),1)

    def test_settings_link_uses_private_origin_and_is_admin_only(self):
        from routers import settings
        self.app.include_router(settings.router)
        with patch.dict(os.environ, {'HOIKUICT_CLASS_KIOSK_ORIGIN':'https://private.example.invalid:8443'}):
            response=self.client.get('/settings')
            self.assertEqual(response.status_code,200)
            self.assertIn('href="https://private.example.invalid:8443/settings/class-kiosk/"',response.text)
            self.user=StaffUser(role=Role.VIEW_ONLY,name='閲覧者')
            self.assertNotIn('private.example.invalid',self.client.get('/settings').text)
            self.user=StaffUser(role=Role.ADMIN,name='管理者')
            with patch.dict(os.environ, {'HOIKUICT_CLASS_KIOSK_ENABLED':'0'}):
                self.assertNotIn('private.example.invalid',self.client.get('/settings').text)

    def test_revocation_cancels_push_preserves_history_and_is_idempotent(self):
        with Session(self.engine) as session:
            session.add(Message(room_id=1,author_name='ひよこ組',body='保存する投稿'))
            session.add(KioskSubscription(device_id=1,endpoint='https://fcm.googleapis.com/revoke',p256dh_key='fake',auth_key='fake'))
            session.add(KioskDelivery(device_id=1,event_key='queued',expires_at=utc_now()+timedelta(minutes=10)))
            session.add(KioskDelivery(device_id=1,event_key='accepted',state='accepted',expires_at=utc_now()+timedelta(minutes=10)))
            session.commit()
        for _ in range(2):self.assertEqual(self.post('/settings/class-kiosk/devices/1/revoke',{}).status_code,200)
        with Session(self.engine) as session:
            self.assertFalse(session.get(KioskSubscription,1).active)
            self.assertEqual([d.state for d in session.exec(select(KioskDelivery).order_by(KioskDelivery.id)).all()],['cancelled','accepted'])
            self.assertEqual(len(session.exec(select(KioskAudit).where(KioskAudit.kind=='device_revoked')).all()),1)
            self.assertEqual(session.exec(select(Message)).one().body,'保存する投稿')
        self.assertEqual(self.client.get('/class-kiosk/api/state').status_code,401)
        self.assertEqual(self.post('/class-kiosk/api/push/test',{}).status_code,401)

    def test_legacy_expiry_does_not_disable_notifications(self):
        with Session(self.engine) as session:
            device=session.get(KioskDevice,1); device.expires_at=utc_now()-timedelta(days=900); session.add(device)
            session.add(KioskSubscription(device_id=1,endpoint='https://fcm.googleapis.com/legacy',p256dh_key='fake',auth_key='fake',created_at=utc_now()-timedelta(days=1)))
            change=KioskChange(account_id=device.account_id,child_id=1,day=local_today(),kind='pickup',version='new')
            session.add(change); session.flush()
            push.queue_change(session,change,utc_now()); session.flush()
            item=session.exec(select(KioskDelivery)).one()
            self.assertIsNotNone(push.delivery_valid(session,item))
            device.active=False; session.add(device); session.flush()
            self.assertIsNone(push.delivery_valid(session,item))

    def test_inactive_class_cannot_enroll_authenticate_or_receive_push(self):
        with Session(self.engine) as session:
            account=session.get(KioskAccount,1); account.active=False; session.add(account)
            session.add(KioskSubscription(device_id=1,endpoint='https://fcm.googleapis.com/disabled',p256dh_key='fake',auth_key='fake'))
            delivery=KioskDelivery(device_id=1,event_key='disabled',expires_at=utc_now()+timedelta(minutes=10))
            session.add(delivery); session.commit()
            self.assertIsNone(push.delivery_valid(session,delivery))
        self.assertEqual(self.client.get('/class-kiosk/api/state').status_code,401)
        self.assertEqual(self.post('/settings/class-kiosk/enrollments',{'classroom_id':1,'name':'スマホ'}).status_code,409)
        data=self.client.get('/settings/class-kiosk/api').json()
        self.assertFalse(data['classrooms'][0]['enabled'])
        self.assertFalse(data['devices'][0]['available'])
        self.assertFalse(data['devices'][0]['push_enabled'])

    def test_home_timeline_includes_exact_boundary_and_excludes_future_and_older(self):
        from datetime import datetime, timezone
        from class_kiosk import service
        now = datetime(2026, 11, 22, 1, 0, tzinfo=timezone.utc)
        with Session(self.engine) as session:
            for body, offset in [('now', timedelta()), ('boundary', timedelta(hours=3)),
                                 ('older', timedelta(hours=3, microseconds=1)), ('future', -timedelta(seconds=1))]:
                session.add(Message(room_id=1, author_name='職員', body=body, created_at=now-offset))
            session.commit()
        with patch.object(service, 'utc_now', return_value=now):
            preview = self.state()['home_timeline']
        self.assertEqual(preview['total'], 2)
        self.assertEqual([m['body'] for m in preview['messages']], ['now', 'boundary'])
        with patch.object(service, 'utc_now', return_value=now+timedelta(hours=4)):
            self.assertEqual(self.state()['home_timeline'], {'messages': [], 'total': 0})
        self.assertEqual(len(self.client.get('/class-kiosk/api/messages').json()), 4)

    def test_home_timeline_counts_all_classes_and_caps_before_backdated_posts(self):
        from class_kiosk import service
        now = utc_now()
        with Session(self.engine) as session:
            for i in range(8):
                session.add(Message(room_id=i % 2 + 1, author_name='職員', body=f'recent-{i}', created_at=now-timedelta(minutes=i)))
            for i in range(35):
                session.add(Message(room_id=1, author_name='職員', body=f'older-{i}', created_at=now-timedelta(days=1)))
            session.commit()
        with patch.object(service, 'utc_now', return_value=now):
            preview = self.state()['home_timeline']
        self.assertEqual(preview['total'], 8)
        self.assertEqual([m['body'] for m in preview['messages']], [f'recent-{i}' for i in range(5)])

    def test_new_reply_does_not_promote_old_parent_and_remains_readable(self):
        from class_kiosk import service
        now = utc_now()
        with Session(self.engine) as session:
            parent = Message(room_id=1, author_name='職員', body='old parent', created_at=now-timedelta(hours=4))
            session.add(parent); session.flush(); parent_id = parent.id
            session.add(Message(room_id=1, author_name='職員', body='new reply', parent_message_id=parent_id, created_at=now))
            session.commit()
            before = [(m.id, m.body, m.is_deleted) for m in session.exec(select(Message).order_by(Message.id)).all()]
        with patch.object(service, 'utc_now', return_value=now):
            self.assertEqual(self.state()['home_timeline'], {'messages': [], 'total': 0})
        full = self.client.get('/class-kiosk/api/messages').json()
        self.assertEqual(len(full), 1); self.assertEqual(full[0]['replies'], 1)
        thread = self.client.get(f'/class-kiosk/api/messages/{parent_id}').json()
        self.assertEqual(thread['replies'][0]['body'], 'new reply')
        with Session(self.engine) as session:
            self.assertEqual(before, [(m.id, m.body, m.is_deleted) for m in session.exec(select(Message).order_by(Message.id)).all()])

    def test_timeline_pagination_orders_by_post_time_without_missing_ties(self):
        now = utc_now()
        with Session(self.engine) as session:
            for i in range(65):
                session.add(Message(room_id=1, author_name='職員', body=str(i), created_at=now-timedelta(minutes=(i*17)%23)))
            session.commit()
            expected = [m.id for m in session.exec(select(Message).order_by(Message.created_at.desc(), Message.id.desc())).all()]
        received = []; before = None
        for _ in range(3):
            page = self.client.get('/class-kiosk/api/messages'+(f'?before={before}' if before else '')).json()
            received.extend(m['id'] for m in page); before = page[-1]['id']
        self.assertEqual(received, expected)
        self.assertEqual(self.client.get(f'/class-kiosk/api/messages?before={before}').json(), [])

    def review(self,status="present"):
        state=self.state()
        rows=[{"id":r["id"],"status":status,"reason":"訂正のテスト" if r["status"] else "","version":r["version"]} for r in state["rows"]]
        response=self.post("/class-kiosk/api/attendance/review",{"day":state["day"],"rows":rows})
        self.assertEqual(response.status_code,200,response.text)
        return response.json()

    def test_registration_is_one_use_and_revocation_is_immediate(self):
        self.assertEqual(self.post("/class-kiosk/enroll",{"code":self.code}).status_code,400)
        self.assertEqual(self.post("/settings/class-kiosk/devices/1/revoke",{}).status_code,200)
        self.assertEqual(self.client.get("/class-kiosk/api/state").status_code,401)

    def test_expiry_and_registration_rate_limit(self):
        code=self.issue()
        with Session(self.engine) as session:
            row=session.exec(select(KioskEnrollment).order_by(KioskEnrollment.id.desc())).first();row.expires_at=utc_now()-timedelta(seconds=1);session.add(row);session.commit()
        self.assertEqual(self.post("/class-kiosk/enroll",{"code":code}).status_code,400)
        for _ in range(8):self.post("/class-kiosk/enroll",{"code":"invalid"})
        self.assertEqual(self.post("/class-kiosk/enroll",{"code":"invalid"}).status_code,429)

    def test_class_boundary_csrf_admin_and_no_cache(self):
        self.assertEqual([r["id"] for r in self.state()["rows"]],[1,2])
        self.assertEqual(self.client.get("/class-kiosk/api/children/3").status_code,404)
        self.assertEqual(self.client.post("/class-kiosk/api/attendance/review",json={"day":str(local_today()),"rows":[]}).status_code,403)
        self.user=StaffUser(role=Role.VIEW_ONLY,name="閲覧者")
        self.assertEqual(self.client.get("/settings/class-kiosk/api").status_code,403)
        self.assertEqual(self.client.get("/class-kiosk/api/state").headers["cache-control"],"no-store")

    def test_network_gate_is_closed_in_production_without_dedicated_ingress(self):
        with patch.dict(os.environ,{"HOIKUICT_ENV":"production","HOIKUICT_CLASS_KIOSK_INGRESS_KEY":""}):
            self.assertEqual(self.client.get("/class-kiosk/api/state",headers={"X-Forwarded-For":"192.168.1.5"}).status_code,403)
        with patch.dict(os.environ,{"HOIKUICT_CLASS_KIOSK_NETWORKS":"192.168.0.0/24"}):
            self.assertEqual(self.client.get("/class-kiosk/api/state").status_code,403)

    def test_bulk_review_does_not_save_and_retries_are_idempotent(self):
        review=self.review()
        with Session(self.engine) as session:self.assertEqual(len(session.exec(select(AttendanceVerification)).all()),0)
        data={"request_id":str(uuid4()),"token":review["token"]}
        first=self.post("/class-kiosk/api/attendance/send",data)
        self.assertEqual(first.status_code,200,first.text)
        self.assertEqual(first.json()["saved"],2)
        self.assertEqual(self.post("/class-kiosk/api/attendance/send",data).json(),first.json())
        self.assertTrue(self.client.get("/class-kiosk/api/operations/"+data["request_id"]).json()["saved"])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(AttendanceVerificationHistory)).all()),2)
            self.assertEqual({r.updated_by_name for r in session.exec(select(AttendanceVerification)).all()},{"ひよこ組"})

    def test_concurrent_staff_edit_rejects_entire_batch(self):
        review=self.review()
        with Session(self.engine) as session:
            session.add(AttendanceVerification(child_id=2,target_date=local_today(),status=AttendanceVerificationStatus.sick_absent,updated_by_name="職員"));session.commit()
        response=self.post("/class-kiosk/api/attendance/send",{"request_id":str(uuid4()),"token":review["token"]})
        self.assertEqual(response.status_code,409,response.text)
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(AttendanceVerification)).all()),1)
            self.assertEqual(len(session.exec(select(AttendanceVerificationHistory)).all()),0)

    def test_new_parent_contact_invalidates_confirmation(self):
        review=self.review()
        with Session(self.engine) as session:
            session.add(DailyContactEntry(child_id=1,parent_account_id=1,target_date=local_today(),contact_note="お迎えについて"));session.commit()
        response=self.post("/class-kiosk/api/attendance/send",{"request_id":str(uuid4()),"token":review["token"]})
        self.assertEqual(response.status_code,409,response.text)
        with Session(self.engine) as session:self.assertFalse(session.exec(select(AttendanceVerification)).first())

    def test_error_mid_batch_rolls_back_every_child(self):
        review=self.review()
        with patch("class_kiosk.service.sync_attendance_alarm", side_effect=[None, RuntimeError("simulated disk failure")]):
            with self.assertRaises(RuntimeError):
                self.post("/class-kiosk/api/attendance/send",{"request_id":str(uuid4()),"token":review["token"]})
        with Session(self.engine) as session:
            self.assertFalse(session.exec(select(AttendanceVerification)).first())
            self.assertFalse(session.exec(select(AttendanceVerificationHistory)).first())
            self.assertFalse(session.exec(select(KioskOperation)).first())

    def test_notification_change_queue_deduplicates_and_ack_suppresses(self):
        with Session(self.engine) as session:
            session.add(KioskSubscription(device_id=1,endpoint="https://fcm.googleapis.com/fake",p256dh_key="fake",auth_key="fake",created_at=utc_now()-timedelta(minutes=5)))
            session.add(DailyContactEntry(child_id=1,parent_account_id=1,target_date=local_today(),contact_note="変更"));session.commit()
        change=self.state()["changes"][0]
        self.state()
        with Session(self.engine) as session:self.assertEqual(len(session.exec(select(KioskDelivery)).all()),1)
        self.post(f'/class-kiosk/api/changes/{change["id"]}/ack',{"version":change["version"],"acknowledged":True})
        class Transport:
            def send(self,**kw):raise AssertionError("Acknowledged notification must not send")
        with patch.object(push,"engine",self.engine):self.assertTrue(push.deliver_one(Transport()))

    def test_tamper_date_correction_reason_and_extra_fields_rejected(self):
        review=self.review()
        self.assertEqual(self.post("/class-kiosk/api/attendance/send",{"request_id":str(uuid4()),"token":review["token"]+'x'}).status_code,409)
        rows=review["rows"]
        self.assertEqual(self.post("/class-kiosk/api/attendance/review",{"day":"2020-01-01","rows":rows}).status_code,409)
        rows[0]["check_in_at"]="09:00"
        self.assertEqual(self.post("/class-kiosk/api/attendance/review",{"day":str(local_today()),"rows":rows}).status_code,422)
        del rows[0]["check_in_at"]
        self.post("/class-kiosk/api/attendance/send",{"request_id":str(uuid4()),"token":review["token"]})
        state=self.state();rows=[{"id":r["id"],"status":"unknown","reason":"","version":r["version"]} for r in state["rows"]]
        self.assertEqual(self.post("/class-kiosk/api/attendance/review",{"day":state["day"],"rows":rows}).status_code,409)

    def test_changed_contact_reopens_ack_and_stale_ack_fails(self):
        with Session(self.engine) as session:
            session.add(DailyContactEntry(child_id=1,parent_account_id=1,target_date=local_today(),contact_note="最初"));session.commit()
        change=self.state()["changes"][0]
        path=f'/class-kiosk/api/changes/{change["id"]}/ack'
        self.assertEqual(self.post(path,{"version":change["version"],"acknowledged":True}).status_code,200)
        with Session(self.engine) as session:
            entry=session.exec(select(DailyContactEntry)).one();entry.contact_note="追記";entry.updated_at=utc_now();session.add(entry);session.commit()
        self.assertEqual(self.post(path,{"version":change["version"],"acknowledged":True}).status_code,409)
        self.assertFalse(self.state()["changes"][0]["ack"])

    def test_today_history_includes_confirmed_but_excludes_previous_day(self):
        with Session(self.engine) as session:
            session.add(DailyContactEntry(child_id=1, parent_account_id=1, target_date=local_today(), contact_note="今日の変更"))
            session.commit()
        change = self.state()["changes"][0]
        self.assertEqual(self.post(f'/class-kiosk/api/changes/{change["id"]}/ack',
            {"version": change["version"], "acknowledged": True}).status_code, 200)
        with Session(self.engine) as session:
            session.add(KioskChange(account_id=1, child_id=2, day=local_today()-timedelta(days=1),
                kind="contact", version="old", history=[{"time":"昨日", "after":"前日の未確認"}]))
            session.commit()
        response = self.client.get("/class-kiosk/api/history")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.headers["cache-control"], "no-store")
        history = response.json()
        self.assertEqual(history["day"], str(local_today()))
        self.assertEqual([c["id"] for c in history["changes"]], [change["id"]])
        self.assertTrue(history["changes"][0]["ack"])
        self.assertTrue(history["changes"][0]["can_ack"])
        self.assertTrue(history["changes"][0]["ack_time"])
        self.assertEqual(len(self.state()["changes"]), 2)  # Home keeps yesterday's unread.

    def test_all_history_includes_unregistered_class_without_granting_write_access(self):
        with Session(self.engine) as session:
            session.add_all([DailyContactEntry(child_id=1, parent_account_id=1, target_date=local_today(), contact_note="自クラス", updated_at=utc_now()-timedelta(minutes=1)),
                DailyContactEntry(child_id=3, parent_account_id=1, target_date=local_today(), contact_note="他クラス")])
            session.commit()
            self.assertIsNone(session.exec(select(KioskAccount).where(KioskAccount.classroom_id == 2)).first())
        response = self.client.get("/class-kiosk/api/history?scope=all")
        self.assertEqual(response.status_code, 200, response.text)
        changes = response.json()["changes"]
        self.assertEqual([c["child_id"] for c in changes], [3, 1])
        other = changes[0]
        self.assertEqual(other["class_name"], "別クラス")
        self.assertFalse(other["can_ack"])
        self.assertFalse(other["ack"])
        for acknowledged in (True, False):
            self.assertEqual(self.post(f'/class-kiosk/api/changes/{other["id"]}/ack',
                {"version":other["version"], "acknowledged":acknowledged}).status_code, 404)
        self.assertEqual(self.client.get("/class-kiosk/api/children/3").status_code, 404)
        self.assertEqual([r["id"] for r in self.state()["rows"]], [1, 2])
        self.assertEqual([c["child_id"] for c in self.client.get("/class-kiosk/api/history").json()["changes"]], [1])
        with Session(self.engine) as session:
            self.assertEqual(len(session.exec(select(KioskDevice)).all()), 1)
            self.assertEqual(len(session.exec(select(KioskEnrollment)).all()), 1)
            self.assertFalse(session.get(KioskChange, other["id"]).acknowledged)
            self.assertFalse(session.exec(select(KioskAudit).where(KioskAudit.kind == "acknowledgement")).first())
            self.assertFalse(session.exec(select(KioskDelivery)).first())
        # Forging another child's row cannot expand the attendance batch.
        rows = [{"id":r["id"], "status":"present", "reason":"", "version":r["version"]} for r in self.state()["rows"]]
        rows.append({"id":3, "status":"present", "reason":"", "version":"forged"})
        self.assertEqual(self.post("/class-kiosk/api/attendance/review", {"day":str(local_today()), "rows":rows}).status_code, 409)

    def test_history_read_preserves_other_confirmation_and_stopped_accounts(self):
        with Session(self.engine) as session:
            session.add(KioskAccount(classroom_id=2, active=False))
            session.add(DailyContactEntry(child_id=3, parent_account_id=1, target_date=local_today(), contact_note="他クラス"))
            session.commit()
        other = self.client.get("/class-kiosk/api/history?scope=all").json()["changes"][0]
        with Session(self.engine) as session:
            change = session.get(KioskChange, other["id"])
            change.acknowledged = True
            session.add(change)
            session.commit()
        again = self.client.get("/class-kiosk/api/history?scope=all").json()["changes"][0]
        self.assertTrue(again["ack"])
        self.assertFalse(again["can_ack"])
        with Session(self.engine) as session:
            self.assertFalse(session.exec(select(KioskAccount).where(KioskAccount.classroom_id == 2)).one().active)
            entry = session.exec(select(DailyContactEntry)).one()
            entry.contact_note = "もう一度変更"
            entry.updated_at = utc_now()
            session.add(entry)
            session.commit()
        with patch.object(push, "engine", self.engine):
            push.scan()
        latest = self.client.get("/class-kiosk/api/history?scope=all").json()["changes"][0]
        self.assertFalse(latest["ack"])
        self.assertEqual(len(latest["history"]), 2)

    def test_history_authentication_scope_and_moved_child_boundaries(self):
        self.assertEqual(self.client.get("/class-kiosk/api/history?scope=invalid").status_code, 422)
        with Session(self.engine) as session:
            session.add(DailyContactEntry(child_id=1, parent_account_id=1, target_date=local_today(), contact_note="連絡"))
            session.commit()
        original = self.state()["changes"][0]
        with Session(self.engine) as session:
            child = session.get(Child, 1)
            child.classroom_id = 2
            session.add(child)
            session.commit()
        history = self.client.get("/class-kiosk/api/history?scope=all").json()["changes"]
        self.assertNotIn(original["id"], [c["id"] for c in history])
        self.assertEqual(history[0]["class_name"], "別クラス")
        self.assertFalse(history[0]["can_ack"])
        self.post("/settings/class-kiosk/devices/1/revoke", {})
        self.assertEqual(self.client.get("/class-kiosk/api/history?scope=all").status_code, 401)

    def test_posts_replies_ownership_and_existing_message_rows(self):
        response=self.client.post("/class-kiosk/api/messages",data={"request_id":str(uuid4()),"body":"共有連絡"},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        message_id=response.json()["message_id"]
        with Session(self.engine) as session:
            message=session.get(Message,message_id);self.assertEqual(message.author_name,"ひよこ組");self.assertIsNone(message.author_user_id)
            staff=Message(room_id=2,author_name="別の職員",body="別の投稿");session.add(staff);session.commit();other_id=staff.id
        self.assertEqual(self.post(f"/class-kiosk/api/messages/{other_id}/delete",{}).status_code,403)
        reply=self.client.post("/class-kiosk/api/messages",data={"request_id":str(uuid4()),"body":"返信", "parent_id":message_id},headers=self.headers)
        self.assertEqual(reply.status_code,200,reply.text)
        self.assertEqual(len(self.client.get(f"/class-kiosk/api/messages/{message_id}").json()["replies"]),1)
        self.assertEqual(self.post(f"/class-kiosk/api/messages/{message_id}/delete",{}).status_code,200)
        self.assertEqual(self.client.get(f"/class-kiosk/api/messages/{message_id}").json()["parent"]["body"],"このメッセージは削除されました。")

    def test_push_rejects_private_endpoints(self):
        self.assertEqual(self.post("/class-kiosk/api/push/subscribe",{"endpoint":"http://127.0.0.1/private","p256dh":"fake","auth":"fake"}).status_code,422)

    def test_push_configuration_checks_subject_and_key_pair_before_start(self):
        import base64
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives import serialization
        key=ec.generate_private_key(ec.SECP256R1())
        path=Path(self.temp.name)/"vapid.pem"
        path.write_bytes(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        public=base64.urlsafe_b64encode(key.public_key().public_bytes(serialization.Encoding.X962,serialization.PublicFormat.UncompressedPoint)).rstrip(b"=").decode()
        with patch.dict(os.environ,{"HOIKUICT_CLASS_KIOSK_WORKER":"1", "HOIKUICT_CLASS_KIOSK_VAPID_PRIVATE_KEY":str(path), "HOIKUICT_CLASS_KIOSK_VAPID_PUBLIC_KEY":public, "HOIKUICT_CLASS_KIOSK_VAPID_SUBJECT":"https://example.invalid:8443"}):
            with self.assertRaises(RuntimeError):push.validate_configuration()
            os.environ["HOIKUICT_CLASS_KIOSK_VAPID_SUBJECT"]="https://example.invalid"
            push.validate_configuration()
            os.environ["HOIKUICT_CLASS_KIOSK_VAPID_PUBLIC_KEY"]="different"
            with self.assertRaises(RuntimeError):push.validate_configuration()

    def test_push_has_no_child_information_and_revocation_cancels_queue(self):
        with Session(self.engine) as session:
            session.add(KioskSubscription(device_id=1,endpoint="https://fcm.googleapis.com/fake",p256dh_key="fake",auth_key="fake"))
            session.add(KioskDelivery(device_id=1,event_key="test:1",expires_at=utc_now()+timedelta(minutes=10)));session.commit()
        calls=[]
        class Transport:
            def send(self,**kw):
                calls.append(kw);return SimpleNamespace(provider_status_code=201,result=ParentPushDeliveryAttemptResult.accepted)
        with patch.object(push,"engine",self.engine):
            self.assertTrue(push.deliver_one(Transport()))
            self.assertEqual(calls[0]["payload"]["body"],"通知のテストです。")
            with Session(self.engine) as session:
                session.add(KioskDelivery(device_id=1,event_key="test:2",expires_at=utc_now()+timedelta(minutes=10)));session.commit()
            self.post("/settings/class-kiosk/devices/1/revoke",{})
            push.deliver_one(Transport())
        self.assertEqual(len(calls),1)


if __name__ == "__main__":
    unittest.main()
