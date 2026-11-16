"""Capture November review/validation changes using disposable fictional data."""
import os
from pathlib import Path
import socket
import sqlite3
import sys
from datetime import date
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[4]
SOURCE = ROOT / ".local-dev/document-search-rollout-20261108/source"
os.chdir(SOURCE)
sys.path.insert(0, str(SOURCE))
os.environ.update(HOIKUICT_ENV="test", PYTHON_DOTENV_DISABLED="1", HOIKUICT_DATABASE_URL="sqlite://")
os.environ.pop("HOIKU_NURSERY_REF", None)

import uvicorn
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, create_engine
from models import Child, Classroom, User
from test_monthly_library import MonthlyLibraryTests
from test_plan_navigation import PlanNavigationTests
from test_plan_docs import PlanDocsIntegrationTests

fixture = PlanNavigationTests()
fixture.setUp()
try:
    temp = Path(fixture.temp.name)
    db = temp / "fictional-plans.sqlite"
    with fixture.engine.connect() as connection, sqlite3.connect(db) as target:
        connection.connection.driver_connection.backup(target)
    fixture.engine.dispose()
    fixture.engine = create_engine(f"sqlite:///{db.as_posix()}", connect_args={"check_same_thread": False})
    os.environ["HOIKUICT_COOKIE_SECURE"] = "0"
    os.environ["HOIKU_MONTHLY_OLLAMA_SOURCES"] = "{}"
    os.environ["HOIKU_WEEKLY_LIBRARY_SOURCES"] = "{}"
    fixture.app.state.monthly_library_fixture = True
    fixture.user.name = "見本 はなこ"
    fixture.user.nursery_ref = "見本保育園"
    fixture.user.actor_ref = f"staff:{fixture.user.user_id}"
    fixture.user.classroom_refs = ("さくら組", "そら組")
    names = ("あおい", "ひなた", "そら", "はる", "ゆい", "なぎ", "りく", "いろは")
    with Session(fixture.engine) as session:
        session.get(User, fixture.user.user_id).display_name = fixture.user.name
        for key, name in enumerate(fixture.user.classroom_refs, 1):
            session.get(Classroom, key).name = name
        for key, name in enumerate(names, 1):
            child = session.get(Child, key)
            if child is None:
                child = Child(id=key, last_name="見本", first_name=name, last_name_kana="ミホン",
                              first_name_kana="ミホン", birth_date=date(2024, 5, 1),
                              enrollment_date=date(2024, 6, 1), classroom_id=1)
                session.add(child)
            child.last_name, child.first_name = "見本", name
        session.commit()
    daily = PlanDocsIntegrationTests()
    daily.corpus_path = temp / "daily-examples.sqlite"
    daily._create_example_corpus()
    os.environ["HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH"] = str(daily.corpus_path)

    @fixture.app.get("/fixture/monthly")
    def monthly(mode: str = "partial", age: int = 1):
        context = MonthlyLibraryTests.context(fixture, month="2026-11", age=age).json()
        if not context["editable"]:
            fixture.client.post(f"/plans/documents/{context['document_id']}/status", data={
                "status": "draft", "lock_version": context["lock_version"]}).raise_for_status()
            context = MonthlyLibraryTests.context(fixture, month="2026-11", age=age).json()
        texts = {
            "common:goal": "戸外で落ち葉の色や音を楽しむ。",
            "common:home": "散歩で見つけた秋の自然を家庭にも伝える。",
            "life": "手を洗ったら、自分のタオルで手を拭く。",
            "play": "落ち葉の色や形を見つけて楽しむ。",
            "help": "かごを用意し、一人ひとりの発見を受け止める。",
        }
        fields = {item["key"]: {"body": texts.get(item["key"], texts.get(item["key"].split(":")[-1], "身近な自然に触れて楽しむ。"))}
                  for item in context["review_fields"]}
        if mode == "partial":
            for item in context["review_fields"][-2:]:
                fields.pop(item["key"], None)
        payload = MonthlyLibraryTests.payload(fixture, context, fields) | {"base_token": context["base_token"]}
        response = fixture.client.post("/plans/monthly-library/save", json=payload)
        response.raise_for_status()
        return RedirectResponse(f"/plans/monthly-library?document_id={response.json()['document_id']}", status_code=303)

    fixture.app.mount("/static", StaticFiles(directory=SOURCE / "static"), name="static")
    with patch("plan_docs.services.monthly_presence.cache_path", return_value=temp / "presence.sqlite"):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            print(f"http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
            uvicorn.Server(uvicorn.Config(fixture.app, log_level="warning", lifespan="off")).run(sockets=[listener])
finally:
    fixture.tearDown()
