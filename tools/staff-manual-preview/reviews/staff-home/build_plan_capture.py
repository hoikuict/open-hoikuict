"""Render the staff planning guide's fictional examples with the deployed routes."""
from datetime import datetime
import os
from pathlib import Path
import sys
from unittest.mock import patch

root = Path(__file__).resolve().parents[4]
source = root / ".local-dev/document-search-rollout-20261108/source"
output = root / ".local-dev/manual-plan-capture"
output.mkdir(exist_ok=True)
os.chdir(source)
sys.path.insert(0, str(source))
os.environ.update(HOIKUICT_ENV="test", PYTHON_DOTENV_DISABLED="1", HOIKUICT_DATABASE_URL="sqlite://")

from sqlmodel import Session
from models import Classroom
from plan_docs.contracts import DocumentStatus as Status, DocumentType as Kind
from plan_docs.routers import annual_library
from plan_docs.services.review_notifications import create_review_outcome_notification
from plan_docs.store import SqlModelDocumentRepository
from test_plan_navigation import PlanNavigationTests

fixture = PlanNavigationTests()
fixture.setUp()
try:
    fixture.app.include_router(annual_library.router, prefix="/plans")
    user = fixture.user
    user.name = "見本 はなこ"
    user.actor_ref = f"staff:{user.user_id}"
    user.nursery_ref = "見本保育園"
    user.classroom_refs = ("さくら組",)
    with Session(fixture.engine) as session:
        room = session.get(Classroom, 1)
        room.name = "さくら組"
        session.add(room)
        session.commit()

    def save(kind, title, status, **fields):
        return fixture.save_legacy(kind, title=title, status=status, classroom_ref="さくら組", **fields)

    month = save(Kind.MONTHLY_PLAN, "2026-10 月案（さくら組）", Status.APPROVED, target_month="2026-10")
    week = save(Kind.WEEKLY_PLAN, "2026-11-02週 週案（さくら組）", Status.DRAFT, week_start_date="2026-11-02")
    save(Kind.DAILY_PLAN, "2026-11-10 日案（さくら組）", Status.APPROVED, target_date="2026-11-10")
    day = save(Kind.DAILY_PLAN, "2026-11-11 日案（さくら組）", Status.DRAFT, target_date="2026-11-11")
    with Session(fixture.engine) as session:
        repo = SqlModelDocumentRepository(session)
        create_review_outcome_notification(session, document=repo.get(month),
            review_revision_id=repo.head(month).id, decision_status="approved",
            decided_by_ref="staff:sample", decided_by_name="見本 ゆい")
        session.commit()

    paths = {"home": "/plans/", "search": "/plans/documents/", "legacy": "/plans/legacy/",
             "day": f"/plans/documents/{day}", "week": f"/plans/documents/{week}"}
    with patch("plan_docs.routers.home.local_now", return_value=datetime(2026,11,11,17,30)):
        for page, path in paths.items():
            res = fixture.client.get(path)
            assert res.status_code == 200, path
            (output / f"{page}.html").write_text(res.text, encoding="utf-8")
    for link in ("/plans/annual-library", "/plans/monthly-plans/", "/plans/weekly-plans/", "/plans/daily-plans/"):
        assert fixture.client.get(link).status_code == 200, link
    print("Captured planning home, list, legacy and two detail pages. All four standard entries open.")
finally:
    fixture.tearDown()
