"""Annual import, copy and editing tests against isolated SQLite databases."""
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import child_records.models  # noqa: F401
import database
from csrf import CsrfTokenMiddleware, verify_csrf
from models import Classroom
from plan_docs.auth_adapter import StaffUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentStatus, DocumentType, Role
from plan_docs.db_models import PlanDocumentRow, PlanRevisionRow
from plan_docs.models import PlanDocument, SectionBlock
from plan_docs.routers.annual_library import router
from plan_docs.routers.documents import router as document_router
from plan_docs.services.annual_library import SOURCE_SCHEMA
from plan_docs.store import SqlModelDocumentRepository


def source_fixture():
    fields = [{"id": "annual", "label": "年間のねらい", "sourceCell": "I1",
               "text": "架空の年間目標\n末尾の改行を保持\n"}]
    for kind in ("goal", "content", "care"):
        for i in range(4):
            fields.append({"id": f"{kind}:{i}", "label": kind, "period": i,
                           "text": f"架空の{kind}{i}\n", "sourceCell": f"B{i+9}"})
    sections = []
    for kind, values in (("development", range(12, 36)), ("support", range(12))):
        items = []
        for i in range(2):
            annual = kind == "support" and i == 1
            items.append({"id": f"{kind}-{i+1}", "kind": kind, "category": "遊び",
                "sourceLine": 1, "sourceCell": "B4" if kind == "development" else "B7",
                "text": f"◯架空の文{i+1}。", "rawLine": "　＜遊び＞　◯架空の文。　",
                "positionRatio": .12 + i / 3, "estimateValue": "annual" if annual else values[i],
                "positionStatus": "explicit_annual" if annual else "needs_confirmation"})
        sections.append({"kind": kind, "ticks": [{"value": v, "x": 10 + i * 11} for i,v in enumerate(values)],
                         "items": items})
    return {"schema": SOURCE_SCHEMA, "fields": fields, "sections": sections,
            "source": {"age": 1, "year": 2026, "className": "架空A組",
                       "ownerText": "架空担任", "title": "架空の既存年案",
                       "sheet": "Sheet1", "range": "A1:Q19",
                       "url": "https://docs.google.com/spreadsheets/d/test-source"},
            "rawCells": {"I1": fields[0]["text"]}}


class AnnualLibraryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "source.json"
        self.source = source_fixture()
        self.path.write_text(json.dumps(self.source, ensure_ascii=False), encoding="utf-8")
        self.original_bytes = self.path.read_bytes()
        self.env = patch.dict("os.environ", {
            "HOIKU_ANNUAL_LIBRARY_SOURCES": json.dumps({"test-nursery": [
                {"id": "fixture", "path": str(self.path)}]}),
            "HOIKUICT_ENV": "production", "HOIKUICT_SECRET_KEY": "annual-test-only",
            "HOIKUICT_CSRF_ENFORCE": "1",
        })
        self.env.start()
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(self.engine)
        with Session(self.engine) as s:
            s.add_all([Classroom(id=1, name="A組"), Classroom(id=2, name="B組")]); s.commit()
        self.user = StaffUser(role=Role.CAN_EDIT, actor_ref="staff:test", nursery_ref="test-nursery",
                              classroom_refs=("A組",), name="今年の担任")
        self.app = FastAPI(dependencies=[Depends(verify_csrf)])
        self.app.add_middleware(CsrfTokenMiddleware)
        self.app.include_router(router, prefix="/plans")
        self.app.include_router(document_router, prefix="/plans")
        self.app.dependency_overrides[resolve_plan_docs_staff_user] = lambda: self.user
        def session_override():
            with Session(self.engine) as s:
                yield s
        self.app.dependency_overrides[database.get_session] = session_override
        self.client = TestClient(self.app, base_url="https://testserver")
        self.client.get("/plans/annual-library")
        self.client.headers["X-CSRF-Token"] = self.client.cookies["hoikuict_csrf"]

    def tearDown(self):
        self.client.close(); self.engine.dispose(); self.env.stop(); self.temp.cleanup()

    def preview(self, **query):
        params = {"classroom_id": 1, "school_year": 2026, "source_key": "fixture", **query}
        if query.get("previous_id"):
            params.pop("source_key")
        response = self.client.get("/plans/annual-library/context", params=params)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def payload(self, boot):
        return {"document_id": boot["document_id"], "lock_version": boot["lock_version"],
                "classroom_id": boot["classroom_id"], "school_year": boot["school_year"],
                "owner_name": boot["owner_name"], "origin": boot["sheet"]["origin"],
                "source_digest": boot["sheet"]["source_digest"],
                "fields": {k: {a: v[a] for a in ("body", "start", "confirmed")}
                           for k,v in boot["sheet"]["fields"].items()}}

    def save(self, payload):
        response = self.client.post("/plans/annual-library/save", json=payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_import_roundtrip_preserves_original_text_fractional_positions_and_revision(self):
        preview = self.preview()
        self.assertEqual(preview["pending_timings"], 3)
        with Session(self.engine) as s:
            self.assertEqual(s.exec(select(PlanDocumentRow)).all(), [])
        first = self.save(self.payload(preview))
        p = self.payload(first)
        p["fields"]["annual"]["body"] = ""
        p["fields"]["development-1"].update(body="自由に編集\n改行\n", start=18, confirmed=True)
        edited = self.save(p)
        self.assertEqual(edited["pending_timings"], 2)
        self.assertEqual(edited["sheet"]["fields"]["annual"]["body"], "")
        self.assertEqual(edited["sheet"]["source"], self.source)
        self.assertEqual(edited["sheet"]["baseline"], preview["sheet"]["fields"])
        self.assertEqual(edited["sheet"]["fields"]["development-2"]["position_ratio"],
                         preview["sheet"]["fields"]["development-2"]["position_ratio"])
        self.assertEqual(self.path.read_bytes(), self.original_bytes)
        with Session(self.engine) as s:
            revisions = s.exec(select(PlanRevisionRow).order_by(PlanRevisionRow.id)).all()
            self.assertEqual(len(revisions), 2)
            self.assertEqual(revisions[0].snapshot["annual_sheet"], first["sheet"])
            self.assertEqual(revisions[1].snapshot["annual_sheet"], edited["sheet"])
        reopened = self.client.get("/plans/annual-library/context", params={
            "classroom_id":1, "school_year":2026, "document_id":first["document_id"]}).json()
        self.assertEqual(reopened["sheet"], edited["sheet"])

    def test_duplicate_creation_and_stale_saves_are_rejected(self):
        preview = self.preview()
        first = self.save(self.payload(preview))
        self.assertEqual(self.client.post("/plans/annual-library/save", json=self.payload(preview)).status_code, 409)
        p = self.payload(first); p["fields"]["annual"]["body"] = "new"
        saved = self.save(p)
        p["fields"]["annual"]["body"] = "stale"
        self.assertEqual(self.client.post("/plans/annual-library/save", json=p).status_code, 409)
        with Session(self.engine) as s:
            self.assertEqual(len(s.exec(select(PlanDocumentRow)).all()), 1)
            self.assertEqual(s.get(PlanDocumentRow, saved["document_id"]).annual_sheet["fields"]["annual"]["body"], "new")

    def test_copy_pins_revision_and_does_not_copy_approval_owner_or_mutate_previous(self):
        original = self.save(self.payload(self.preview()))
        doc_id = original["document_id"]
        with Session(self.engine) as s:
            repo = SqlModelDocumentRepository(s)
            doc = repo.get(doc_id)
            revision = repo.head(doc_id).current_revision_id
            repo.update_status(doc_id, DocumentStatus.IN_REVIEW, actor_ref="staff:test", actor_name="担任",
                            expected_lock_version=repo.lock_version(doc_id))
            repo.update_status(doc_id, DocumentStatus.APPROVED, actor_ref="staff:admin", actor_name="管理者",
                            expected_lock_version=repo.lock_version(doc_id))
            previous_sheet = deepcopy(doc.annual_sheet)
        preview = self.preview(school_year=2027, previous_id=doc_id, revision_id=revision)
        self.assertEqual(preview["owner_name"], "今年の担任")
        self.assertEqual(preview["sheet"]["baseline"], previous_sheet["fields"])
        p = self.payload(preview); p["fields"]["annual"]["body"] = "翌年度の微修正"
        copied = self.save(p)
        self.assertNotEqual(copied["document_id"], doc_id)
        self.assertEqual(copied["status"], "下書き")
        self.assertEqual(copied["sheet"]["origin"]["revision_id"], revision)
        with Session(self.engine) as s:
            self.assertEqual(s.get(PlanDocumentRow, doc_id).annual_sheet, previous_sheet)
            self.assertIsNone(SqlModelDocumentRepository(s).head(copied["document_id"]).approved_revision_id)
        self.assertEqual(self.client.post("/plans/annual-library/save", json=self.payload(original)).status_code, 409)

    def test_permissions_csrf_and_wrong_scope(self):
        boot = self.preview(); p = self.payload(boot)
        with TestClient(self.app, base_url="https://testserver") as no_csrf:
            self.assertEqual(no_csrf.post("/plans/annual-library/save", json=p).status_code, 403)
        self.user.role = Role.VIEW_ONLY
        self.assertEqual(self.client.post("/plans/annual-library/save", json=p).status_code, 403)
        self.user.role = Role.CAN_EDIT
        self.assertEqual(self.client.get("/plans/annual-library/context", params={
            "classroom_id":2, "school_year":2026, "source_key":"fixture"}).status_code, 403)
        saved = self.save(p)
        self.user.nursery_ref = "different-nursery"
        self.assertEqual(self.client.get("/plans/annual-library", params={"document_id":saved["document_id"]}).status_code, 404)
        self.user.nursery_ref = "test-nursery"; self.user.actor_ref = None
        self.assertEqual(self.client.get(f"/plans/documents/{saved['document_id']}").status_code, 404)

    def test_tampering_invalid_values_missing_fields_and_source_change(self):
        boot = self.preview(); original = self.payload(boot)
        for key, change in [
            ("bad-source", lambda p: p.update(origin={"kind":"source","key":"../secret"})),
            ("bad-year", lambda p: p.update(school_year=2200)),
            ("bad-start", lambda p: p["fields"]["development-1"].update(start=0)),
            ("wrong-type", lambda p: p["fields"]["development-1"].update(start=True)),
            ("bad-confirm", lambda p: p["fields"]["annual"].update(confirmed=True)),
            ("missing", lambda p: p["fields"].pop("annual")),
            ("unknown", lambda p: p["fields"].update(unknown={"body":"x"})),
            ("source-write", lambda p: p.update(source={"text":"overwrite"})),
            ("blank-owner", lambda p: p.update(owner_name="  ")),
        ]:
            with self.subTest(key):
                p=deepcopy(original); change(p)
                self.assertIn(self.client.post("/plans/annual-library/save", json=p).status_code, (404,422))
        self.source["fields"][0]["text"] += "変更"
        self.path.write_text(json.dumps(self.source), encoding="utf-8")
        self.assertEqual(self.client.post("/plans/annual-library/save", json=original).status_code, 409)

    def test_existing_document_opens_without_external_source_and_common_edit_cannot_overwrite(self):
        saved = self.save(self.payload(self.preview()))
        self.path.unlink()
        page = self.client.get("/plans/annual-library", params={"document_id":saved["document_id"]})
        self.assertEqual(page.status_code, 200)
        self.assertIn("annual-library-boot", page.text)
        document = self.client.get(f"/plans/documents/{saved['document_id']}")
        self.assertEqual(document.status_code, 200)
        self.assertIn("annual-plan-sheet", document.text)
        edit = self.client.get(f"/plans/documents/{saved['document_id']}/edit", follow_redirects=False)
        self.assertEqual(edit.status_code, 303)
        self.assertIn("/plans/annual-library?", edit.headers["location"])
        self.assertEqual(self.client.post(f"/plans/documents/{saved['document_id']}", data={"title":"overwrite"}).status_code,409)

    def test_legacy_annual_plan_keeps_existing_editor(self):
        with Session(self.engine) as s:
            doc = SqlModelDocumentRepository(s).create(PlanDocument(
                id=0, document_type=DocumentType.ANNUAL_PLAN, status=DocumentStatus.DRAFT,
                title="旧年案", nursery_ref="test-nursery", classroom_ref="A組", actor_ref="staff:test",
                owner_name="担当", school_year=2025,
                sections=[SectionBlock("annual_goal","ねらい","旧本文",[],[])]))
        response = self.client.get(f"/plans/documents/{doc.id}/edit")
        self.assertEqual(response.status_code,200)
        self.assertIn("旧本文",response.text)
        self.assertNotIn("annual-library-boot",response.text)

    def test_additive_migration_retains_existing_rows_and_is_idempotent(self):
        engine = create_engine("sqlite://")
        with engine.begin() as conn:
            conn.exec_driver_sql("CREATE TABLE plan_documents (id INTEGER PRIMARY KEY, title TEXT)")
            conn.exec_driver_sql("INSERT INTO plan_documents VALUES (1, 'legacy')")
        with patch.object(database, "engine", engine):
            database._migrate_annual_sheet_columns()
            database._migrate_annual_sheet_columns()
        with engine.begin() as conn:
            self.assertEqual(conn.exec_driver_sql("SELECT title,annual_sheet,annual_sheet_key FROM plan_documents").one(), ("legacy",None,None))
        engine.dispose()
