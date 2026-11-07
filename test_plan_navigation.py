"""Staff navigation to saved plans, using a disposable database."""
import unittest

from sqlmodel import Session

import test_monthly_library as fixtures
from plan_docs.contracts import DocumentStatus, DocumentType, Role
from plan_docs.models import PlanDocument
from plan_docs.routers import home, plans, weekly_library
from plan_docs.services.weekly_library import blank_sheet
from plan_docs.store import SqlModelDocumentRepository


class PlanNavigationTests(unittest.TestCase):
    tearDown = fixtures.MonthlyLibraryTests.tearDown

    def setUp(self):
        fixtures.MonthlyLibraryTests.setUp(self)
        for module in (home, plans, weekly_library):
            self.app.include_router(module.router, prefix="/plans")

    def save_legacy(self, kind, **values):
        document = PlanDocument(id=0, document_type=kind, title="見本の帳票",
            status=DocumentStatus.DRAFT, nursery_ref=self.user.nursery_ref, classroom_ref="A組",
            actor_ref=self.user.actor_ref, owner_name=self.user.name, sections=[])
        for key, value in values.items():
            setattr(document, key, value)
        with Session(self.engine) as session:
            return SqlModelDocumentRepository(session).create(document).id

    def test_legacy_entry_scope_and_edit_links(self):
        original = self.save_legacy(DocumentType.ANNUAL_PLAN, school_year=2026)
        self.save_legacy(DocumentType.MONTHLY_PLAN, classroom_ref="B組")
        self.save_legacy(DocumentType.WEEKLY_PLAN, nursery_ref="別の園")
        self.save_legacy(DocumentType.INDIVIDUAL_PLAN)
        self.assertIn('href="/plans/legacy/"', self.client.get("/plans/").text)
        page = self.client.get("/plans/legacy/")
        self.assertEqual([d.id for d in page.context["documents"]], [original])
        self.assertIn('href="/plans/bunrei/annual"', page.text)
        detail = f"/plans/documents/{original}"
        self.assertIn(f'href="{detail}"', page.text)
        self.assertIn(f'href="{detail}/edit"', self.client.get(detail).text)
        self.assertIn(f'action="{detail}"', self.client.get(detail + "/edit").text)
        self.user.role = Role.VIEW_ONLY
        page = self.client.get("/plans/legacy/")
        self.assertIn(f'href="{detail}"', page.text)
        self.assertNotIn('href="/plans/annual-plans/new"', page.text)
        self.assertNotIn(f'href="{detail}/edit"', self.client.get(detail).text)
        self.user.actor_ref = None
        self.assertEqual(self.client.get("/plans/legacy/", follow_redirects=False).status_code, 303)

    def test_calendar_status_and_link_match_each_format(self):
        month = self.save_legacy(DocumentType.MONTHLY_PLAN, target_month="2026-11")
        week = self.save_legacy(DocumentType.WEEKLY_PLAN, week_start_date="2026-11-02", age_class="1歳児")
        self.save_legacy(DocumentType.MONTHLY_PLAN, target_month="2026-11", age_class="4歳児")
        self.save_legacy(DocumentType.WEEKLY_PLAN, week_start_date="2026-11-02", status=DocumentStatus.ARCHIVED)
        def inspect(period, key, legacy, standard=None):
            params = {"age": 1, "classroom_id": 1, "month": "2026-11", "year": 2026}
            page = self.client.get(f"/plans/{period}-plans/", params=params)
            card = next(c for c in page.context["cards"] if c["key"] == key)
            self.assertEqual([d.id for d in card["old_documents"]], [legacy])
            self.assertEqual([d.id for d in card["documents"]], [standard] if standard else [])
            markup = page.text.split(f'data-period="{key}"', 1)[1].split("</article>", 1)[0]
            self.assertIn(f'href="/plans/documents/{legacy}"', markup)
            self.assertIn("自園の帳票を開く" if standard else "自園の帳票で作成", markup)
            self.assertEqual(self.client.get(card["url"]).status_code, 200)
        inspect("monthly", "2026-11", month)
        inspect("weekly", "2026-11-02", week)
        boot = fixtures.MonthlyLibraryTests.context(self, month="2026-11", age=1).json()
        payload = fixtures.MonthlyLibraryTests.payload(self, boot, {"common:goal": {"body": "見本のねらい"}})
        saved = self.client.post("/plans/monthly-library/save", json=payload).json()
        inspect("monthly", "2026-11", month, saved["document_id"])
        response = self.client.post("/plans/weekly-library/save", json={
            "classroom_id": 1, "month": "2026-11", "age": 1, "items": [{"week_start": "2026-11-02",
            "lock_version": 0, "sheet": blank_sheet(), "owner_name": self.user.name}]})
        current = next(r for r in response.json()["records"] if r["week_start"] == "2026-11-02")
        inspect("weekly", "2026-11-02", week, current["document_id"])
