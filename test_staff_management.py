import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role
from models import Classroom, Staff, StaffEmploymentType, StaffStatus
import routers.classrooms as classrooms_module
import routers.staff as staff_module


class StaffManagementTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(staff_module.router)
        self.app.include_router(classrooms_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.app.dependency_overrides[staff_module.get_session] = override_get_session
        self.app.dependency_overrides[classrooms_module.get_session] = override_get_session
        self.client = TestClient(self.app)

        with Session(self.engine) as session:
            hiyoko = Classroom(name="ひよこ組", display_order=1)
            usagi = Classroom(name="うさぎ組", display_order=2)
            session.add(hiyoko)
            session.add(usagi)
            session.flush()

            admin = Staff(
                full_name="園長 花子",
                display_name="園長花子",
                role=Role.ADMIN,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
            )
            editor = Staff(
                full_name="田中 一郎",
                display_name="田中先生",
                role=Role.CAN_EDIT,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.regular,
                primary_classroom_id=hiyoko.id,
            )
            viewer = Staff(
                full_name="中村 由紀",
                display_name="中村さん",
                role=Role.VIEW_ONLY,
                status=StaffStatus.active,
                employment_type=StaffEmploymentType.part_time,
                primary_classroom_id=usagi.id,
            )
            retired = Staff(
                full_name="佐藤 退職",
                display_name="佐藤先生",
                role=Role.CAN_EDIT,
                status=StaffStatus.retired,
                employment_type=StaffEmploymentType.regular,
            )
            session.add(admin)
            session.add(editor)
            session.add(viewer)
            session.add(retired)
            session.commit()

            self.admin_id = admin.id
            self.editor_id = editor.id
            self.viewer_id = viewer.id
            self.retired_id = retired.id
            self.hiyoko_id = hiyoko.id
            self.usagi_id = usagi.id

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def _mock_login(self, staff_id: int):
        response = self.client.post(
            "/staff/mock-login",
            data={"staff_id": str(staff_id), "redirect_to": "/staff/"},
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 303)

    def test_admin_can_create_and_edit_staff_with_employment_type(self):
        self._mock_login(self.admin_id)

        create_response = self.client.post(
            "/staff/",
            data={
                "full_name": "新規 職員",
                "display_name": "新規先生",
                "role": Role.CAN_EDIT.value,
                "status": StaffStatus.active.value,
                "employment_type": StaffEmploymentType.part_time.value,
                "primary_classroom_id": str(self.hiyoko_id),
            },
            follow_redirects=False,
        )
        self.assertEqual(create_response.status_code, 303)

        with Session(self.engine) as session:
            created = session.exec(select(Staff).where(Staff.display_name == "新規先生")).first()

        self.assertIsNotNone(created)
        self.assertEqual(created.primary_classroom_id, self.hiyoko_id)
        self.assertEqual(created.employment_type, StaffEmploymentType.part_time)

        update_response = self.client.post(
            f"/staff/{created.id}/edit",
            data={
                "full_name": "更新 職員",
                "display_name": "更新先生",
                "role": Role.ADMIN.value,
                "status": StaffStatus.retired.value,
                "employment_type": StaffEmploymentType.regular.value,
                "primary_classroom_id": "",
            },
            follow_redirects=False,
        )
        self.assertEqual(update_response.status_code, 303)

        with Session(self.engine) as session:
            updated = session.get(Staff, created.id)

        self.assertEqual(updated.display_name, "更新先生")
        self.assertEqual(updated.role, Role.ADMIN)
        self.assertEqual(updated.status, StaffStatus.retired)
        self.assertEqual(updated.employment_type, StaffEmploymentType.regular)
        self.assertIsNone(updated.primary_classroom_id)

    def test_can_edit_staff_can_use_editable_screen_but_not_staff_admin_screen(self):
        self._mock_login(self.editor_id)

        classroom_form = self.client.get("/classrooms/new")
        self.assertEqual(classroom_form.status_code, 200)

        staff_form = self.client.get("/staff/new")
        self.assertEqual(staff_form.status_code, 403)

    def test_view_only_staff_can_view_staff_list_and_filter_retired_staff(self):
        self._mock_login(self.viewer_id)

        classroom_form = self.client.get("/classrooms/new")
        self.assertEqual(classroom_form.status_code, 403)

        active_list = self.client.get("/staff/")
        self.assertEqual(active_list.status_code, 200)
        self.assertIn("中村さん", active_list.text)
        self.assertIn("パート", active_list.text)
        self.assertNotIn("佐藤先生", active_list.text)

        retired_list = self.client.get("/staff/?status=retired")
        self.assertEqual(retired_list.status_code, 200)
        self.assertIn("佐藤先生", retired_list.text)


if __name__ == "__main__":
    unittest.main()
