import base64
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role, StaffUser
from models import MeetingNote
import routers.meeting_notes as meeting_notes_module


class MeetingNoteRouterTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(self.engine)

        self.app = FastAPI()
        self.app.include_router(meeting_notes_module.router)

        def override_get_session():
            with Session(self.engine) as session:
                yield session

        self.current_user = StaffUser(role=Role.CAN_EDIT, name="テスト担当")

        def override_get_current_staff_user():
            return self.current_user

        self.app.dependency_overrides[meeting_notes_module.get_session] = override_get_session
        self.app.dependency_overrides[meeting_notes_module.get_current_staff_user] = override_get_current_staff_user
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.engine.dispose()

    def test_staff_can_create_and_save_meeting_note(self):
        create_response = self.client.post("/meeting-notes/", follow_redirects=False)
        self.assertEqual(create_response.status_code, 303)
        self.assertRegex(create_response.headers["location"], r"^/meeting-notes/\d+$")

        with Session(self.engine) as session:
            note = session.exec(select(MeetingNote)).first()

        self.assertIsNotNone(note)
        self.assertEqual(note.title, "無題の議事録")
        self.assertEqual(note.created_by, "テスト担当")

        sample_state = bytes([1, 2, 3, 4, 5])
        save_response = self.client.post(
            f"/meeting-notes/api/{note.id}/save",
            json={
                "title": "朝会メモ",
                "content_base64": base64.b64encode(sample_state).decode("utf-8"),
            },
        )
        self.assertEqual(save_response.status_code, 200)
        self.assertEqual(save_response.json(), {"status": "ok"})

        with Session(self.engine) as session:
            saved_note = session.get(MeetingNote, note.id)

        self.assertEqual(saved_note.title, "朝会メモ")
        self.assertEqual(saved_note.content, sample_state)
        self.assertEqual(saved_note.updated_by, "テスト担当")

        content_response = self.client.get(f"/meeting-notes/api/{note.id}/content")
        self.assertEqual(content_response.status_code, 200)
        self.assertEqual(content_response.json()["content_base64"], base64.b64encode(sample_state).decode("utf-8"))

    def test_view_only_user_cannot_create_or_save_meeting_note(self):
        self.current_user = StaffUser(role=Role.VIEW_ONLY, name="閲覧担当")

        create_response = self.client.post("/meeting-notes/", follow_redirects=False)
        self.assertEqual(create_response.status_code, 403)

        with Session(self.engine) as session:
            note = MeetingNote(title="共有メモ")
            session.add(note)
            session.commit()
            session.refresh(note)
            note_id = note.id

        save_response = self.client.post(
            f"/meeting-notes/api/{note_id}/save",
            json={"title": "更新不可", "content_base64": ""},
        )
        self.assertEqual(save_response.status_code, 403)

        detail_response = self.client.get(f"/meeting-notes/{note_id}")
        self.assertEqual(detail_response.status_code, 200)
        self.assertIn("閲覧専用", detail_response.text)

    def test_websocket_broadcasts_updates_to_other_editors(self):
        with Session(self.engine) as session:
            note = MeetingNote(title="共同編集テスト")
            session.add(note)
            session.commit()
            session.refresh(note)
            note_id = note.id

        with self.client.websocket_connect(f"/meeting-notes/ws/{note_id}") as ws_one:
            with self.client.websocket_connect(f"/meeting-notes/ws/{note_id}") as ws_two:
                payload = b"\x00\x01\x02sync"
                ws_one.send_bytes(payload)
                self.assertEqual(ws_two.receive_bytes(), payload)

    def test_room_id_uses_demo_session_id_when_present(self):
        class DummyWebSocket:
            def __init__(self, query_params=None, cookies=None):
                self.query_params = query_params or {}
                self.cookies = cookies or {}

        demo_socket = DummyWebSocket(query_params={"demo_session_id": "a" * 32})
        shared_socket = DummyWebSocket()

        self.assertEqual(
            meeting_notes_module._meeting_note_room_id(demo_socket, 1),
            f'{"a" * 32}:1',
        )
        self.assertEqual(meeting_notes_module._meeting_note_room_id(shared_socket, 1), "shared:1")


if __name__ == "__main__":
    unittest.main()
