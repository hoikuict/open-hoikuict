"""Serve the deployed planning forms on loopback with disposable example data for capture."""
import json
import os
from pathlib import Path
from shutil import copyfile
import socket
import sqlite3
import sys

root = Path(__file__).resolve().parents[4]
source = root / ".local-dev/document-search-rollout-20261108/source"
os.chdir(source)
sys.path.insert(0, str(source))
os.environ.update(HOIKUICT_ENV="test", PYTHON_DOTENV_DISABLED="1", HOIKUICT_DATABASE_URL="sqlite://")

import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, create_engine
from models import Child, Classroom, User
from plan_docs.routers import annual_library, reflections
from test_annual_library import source_fixture
from test_plan_docs import PlanDocsIntegrationTests
from test_plan_navigation import PlanNavigationTests

fixture = PlanNavigationTests()
fixture.setUp()
try:
    temp = Path(fixture.temp.name)
    # The browser sends presence and editing requests concurrently. Give each
    # connection its own transaction on the same disposable file.
    db_path = temp / "plans.sqlite"
    with fixture.engine.connect() as src, sqlite3.connect(db_path) as dest:
        src.connection.driver_connection.backup(dest)
    fixture.engine.dispose()
    fixture.engine = create_engine(f"sqlite:///{db_path.as_posix()}", connect_args={"check_same_thread":False})
    user = fixture.user
    user.name, user.actor_ref = "見本 はなこ", f"staff:{user.user_id}"
    user.nursery_ref = "見本保育園"
    user.classroom_refs = ("さくら組", "そら組")
    with Session(fixture.engine) as session:
        staff = session.get(User, user.user_id)
        staff.display_name = user.name
        for key, name in enumerate(user.classroom_refs, start=1):
            session.get(Classroom, key).name = name
        for key, name in enumerate(("あおい", "ひなた"), start=1):
            child = session.get(Child, key)
            child.last_name, child.first_name = "見本", name
        session.commit()
    annual = source_fixture()
    annual["source"].update(className="さくら組", title="さくら組 年間指導計画（見本）", ownerText="見本 はなこ")
    field = annual["fields"][0]
    field["text"] = annual["rawCells"]["I1"] = "安心して好きな遊びを楽しむ。"
    fields = {"goal": ("ねらい", "好きな遊びを見つける。"), "care": ("配慮", "一人ひとりの気持ちを受け止める。"), "content": ("内容", "園庭で自然に触れる。")}
    for field in annual["fields"][1:]:
        field["label"], field["text"] = fields[field["id"].split(":")[0]]
    for section in annual["sections"]:
        for item in section["items"]:
            item["text"] = item["rawLine"] = "好きな遊びを一緒に楽しむ。"
    annual_file = temp / "annual.json"
    annual_file.write_text(json.dumps(annual, ensure_ascii=False), encoding="utf-8")
    os.environ["HOIKU_ANNUAL_LIBRARY_SOURCES"] = json.dumps({user.nursery_ref: [{"id":"sample", "path":str(annual_file)}]})
    monthly_file = temp / "november.sqlite"
    copyfile(fixture.corpus, monthly_file)
    with sqlite3.connect(monthly_file) as db:
        db.execute("UPDATE phrase SET month=11, text=?, norm=? WHERE item='生活・健康'",
                   ("手を洗ったら、自分のタオルで手を拭く。", "手を洗ったら、自分のタオルで手を拭く。"))
    os.environ["HOIKU_MONTHLY_LIBRARY_SOURCES"] = json.dumps({user.nursery_ref: {"id":"sample","path":str(monthly_file)}})
    weekly_file = temp / "weekly.json"
    example = {"id":"sample-leaves","age":1,"month":11,"title":"落ち葉を集める",
               "aim":"秋の自然に親しむ。","activity":"園庭で落ち葉を集める。",
               "support_preparation":"落ち葉を入れるかごを用意する。","source_label":"見本の週案",
               "days":[{"activity":"","support":"","preparation":""} for _ in range(6)]}
    weekly_file.write_text(json.dumps({"schema_version":1, "examples":[example]}), encoding="utf-8")
    os.environ["HOIKU_WEEKLY_LIBRARY_SOURCES"] = json.dumps({user.nursery_ref: {"path":str(weekly_file)}})
    daily = PlanDocsIntegrationTests()
    daily.corpus_path = temp / "daily.sqlite"
    daily._create_example_corpus()
    os.environ["HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH"] = str(daily.corpus_path)
    fixture.app.include_router(annual_library.router, prefix="/plans")
    fixture.app.include_router(reflections.router, prefix="/plans")
    fixture.app.mount("/static", StaticFiles(directory=source / "static"), name="static")
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        print(f"http://127.0.0.1:{listener.getsockname()[1]}", flush=True)
        uvicorn.Server(uvicorn.Config(fixture.app, log_level="warning", lifespan="off")).run(sockets=[listener])
finally:
    fixture.tearDown()
