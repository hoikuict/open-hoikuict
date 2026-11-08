import unittest

from sqlmodel import Session, select

import test_parent_portal
from auth import Role, StaffUser, get_current_staff_user
from models import ChildHealthProfile, ParentChildLink, ParentMedicalResponse
from parent_medical_service import UNANSWERED, XRAY_QUESTION, current_values
from routers import child_health, parent_medical


class ParentMedicalTests(unittest.TestCase):
    def setUp(self):
        self.fixture = test_parent_portal.ParentPortalTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.app.include_router(parent_medical.router)
        self.fixture.app.include_router(child_health.router)
        self.client = self.fixture.client
        self.child = self.fixture.child_id
        self.parent = self.fixture.parent_account_id
        self.url = parent_medical.PARENT.format(child_id=self.child)
        self.staff = parent_medical.STAFF.format(child_id=self.child)
        with Session(self.fixture.engine) as session:
            session.add(ParentChildLink(child_id=self.child, parent_account_id=self.parent))
            session.commit()
        self.fixture._login_parent(self.parent)

    def post(self, action, **fields):
        revision = self.client.get(self.url).context["revision"]
        return self.client.post(self.url, data={"revision": revision, "action": action, **fields})

    def test_request_preview_send_approve_and_stale_edits(self):
        for _ in range(2):
            self.assertEqual(self.client.post(self.staff + "/request", data={"parent_id": self.parent}).status_code, 200)
        self.assertIn("園から基本医療情報の記入", self.client.get("/parent-portal/").text)
        form = self.client.get(self.url)
        self.assertNotRegex(form.text, r'name="xray_answer"[^>]* checked')
        info = {"blood_type": "A型", "primary_doctor_name": "見本医院", "xray_answer": "agree"}
        self.assertIn("回答の確認", self.post("preview", **info).text)
        self.assertEqual(self.post("edit", **info).context["draft"]["blood_type"], "A型")
        profile_url = f"/children/{self.child}/health/profile"
        version = self.client.get(profile_url).context["medical_version"]
        with Session(self.fixture.engine) as session:
            self.assertEqual([r.status for r in session.exec(select(ParentMedicalResponse))], ["requested"])
        self.assertIn("園に回答を送りました", self.post("send", **info).text)
        self.assertEqual(self.client.post(self.url, data={"revision": form.context["revision"], "action": "send"}).status_code, 409)
        with Session(self.fixture.engine) as session:
            record = session.exec(select(ParentMedicalResponse)).one()
            self.assertEqual(record.xray_question, XRAY_QUESTION)
            self.assertEqual(current_values(session, self.child)["blood_type"], "")
            record_id = record.id
        self.assertIn("事前承諾として扱えません", self.client.get(profile_url).text)
        self.assertEqual(self.client.post(f"{self.staff}/{record_id}", data={"action": "approve"}).status_code, 200)
        self.assertEqual(self.client.post(profile_url, data={"medical_version": version}).status_code, 409)
        self.assertIn("園で確認済み", self.client.get(profile_url).text)
        with Session(self.fixture.engine) as session:
            self.assertEqual(current_values(session, self.child)["blood_type"], "A型")
            self.assertEqual(current_values(session, self.fixture.second_child_id)["blood_type"], "")

    def test_scope_return_and_no_consent(self):
        self.assertEqual(self.client.get(parent_medical.PARENT.format(child_id=self.fixture.second_child_id)).status_code, 404)
        self.assertEqual(self.client.post(self.staff + "/request", data={"parent_id": self.fixture.single_parent_account_id}).status_code, 404)
        self.assertEqual(self.post("preview", hospital_phone="000").status_code, 422)
        self.assertIn(UNANSWERED, self.post("preview").text)
        self.assertEqual(self.post("send", xray_answer="contact").status_code, 200)
        with Session(self.fixture.engine) as session:
            record_id = session.exec(select(ParentMedicalResponse.id)).one()
        data = {"action": "return", "note": "病院名を確認してください。"}
        self.assertEqual(self.client.post(f"{self.staff}/{record_id}", data=data).status_code, 200)
        self.assertIn(data["note"], self.client.get(self.url).text)
        self.assertEqual(self.post("send", xray_answer="undecided").status_code, 200)
        self.fixture.app.dependency_overrides[get_current_staff_user] = lambda: StaffUser(role=Role.VIEW_ONLY, name="閲覧")
        self.assertEqual(self.client.post(self.staff + "/request", data={"parent_id": self.parent}).status_code, 403)
        self.assertEqual(self.client.post(f"{self.staff}/{record_id + 1}", data={"action": "approve"}).status_code, 403)
        self.fixture._login_parent(self.fixture.single_parent_account_id)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_clear_hospital_conflict_and_supersession(self):
        with Session(self.fixture.engine) as session:
            session.add(ChildHealthProfile(child_id=self.child, hospital_name="見本病院", hospital_phone="000"))
            session.commit()
        self.assertEqual(self.post("preview").context["draft"]["hospital_name"], "見本病院")
        self.assertEqual(self.post("preview", hospital_name="別の病院").context["draft"]["hospital_phone"], "")
        self.assertEqual(self.post("send", clear_hospital="yes", xray_answer="agree").status_code, 200)
        self.assertEqual(self.post("send", clear_hospital="yes").status_code, 200)
        with Session(self.fixture.engine) as session:
            records = session.exec(select(ParentMedicalResponse).order_by(ParentMedicalResponse.id)).all()
            self.assertEqual([r.status for r in records], ["superseded", "pending"])
            self.assertEqual(records[-1].answers["hospital_name"], "")
            self.assertIsNone(records[-1].xray_answer)
            last_id = records[-1].id
            profile = session.exec(select(ChildHealthProfile)).one()
            profile.hospital_name = "更新後の病院"
            session.add(profile)
            session.commit()
        self.assertEqual(self.client.post(f"{self.staff}/{last_id}", data={"action": "approve"}).status_code, 409)
        self.assertIn(UNANSWERED, self.client.get(f"/children/{self.child}/health").text)
