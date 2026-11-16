"""Local-only planning navigation review against the deployed templates and routers.

venv/Scripts/python tools/plan-navigation-mock/serve.py [--source DEPLOYED_CHECKOUT] [--port 8087]
"""
import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--source", type=Path, default=ROOT / ".local-dev/child-review-rollout-20261108/source")
parser.add_argument("--port", type=int, default=8087)
args = parser.parse_args()
src = args.source.resolve(strict=True)
os.chdir(src)
sys.path.insert(0, str(src))
os.environ.update(PYTHON_DOTENV_DISABLED="1", HOIKUICT_ENV="test", HOIKUICT_DATABASE_URL="sqlite://",
                  HOIKU_MONTHLY_OLLAMA_SOURCES="{}", HOIKU_WEEKLY_LIBRARY_SOURCES="{}")

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.testclient import TestClient
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from sqlmodel import Session, create_engine
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn

import database
from csrf import CsrfTokenMiddleware, verify_csrf
from models import Classroom, User
from plan_docs.auth_adapter import CurrentUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentStatus, DocumentType
from plan_docs.routers import annual_library, bunrei, documents, home, monthly_library, plans, weekly_library
from plan_docs.services.weekly_library import blank_sheet
from plan_docs.store import DocumentRepositoryDep, SqlModelDocumentRepository
from plan_docs.templating import render_template, templates
from test_annual_library import source_fixture
from test_monthly_library import MonthlyLibraryTests
from test_plan_docs import PlanDocsIntegrationTests

# The deployed monthly integration fixture supplies a synthetic classroom, two children,
# a phrase corpus, CSRF, permissions, and the real monthly/document routers.
fixture = MonthlyLibraryTests()
fixture.setUp()
app = FastAPI(dependencies=[Depends(verify_csrf)], docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(CsrfTokenMiddleware)
tmp = Path(fixture.temp.name)
user = fixture.user
user.name = "見本 はなこ"
user.classroom_refs = ("さくら組",)
user.actor_ref = f"staff:{user.user_id}"
user.nursery_ref = "見本保育園"
with Session(fixture.engine) as session:
    session.get(Classroom, 1).name = user.classroom_refs[0]
    session.get(User, user.user_id).display_name = user.name
    session.commit()

source = source_fixture()
source["source"].update(className="さくら組", title="さくら組 年間指導計画（見本）")
annual_path = tmp / "annual.json"
annual_path.write_text(json.dumps(source, ensure_ascii=False), encoding="utf-8")
daily = PlanDocsIntegrationTests()
daily.corpus_path = tmp / "daily.sqlite"
daily._create_example_corpus()
shared_path = tmp / "old-examples.sqlite"
with closing(sqlite3.connect(shared_path)) as connection:
    connection.executescript("""
        create table bunrei(id text,plan_type text,age_class text,time_unit text,month integer,
            item text,ryoiki text,direction text,juu_no_sugata text,text text,needs_review integer);
        insert into bunrei values('annual01','年案','5歳児','通年',null,'年間目標',null,null,null,'友だちと季節の遊びを楽しむ。',0);
        insert into bunrei values('month01','月案','5歳児',null,null,'活動内容',null,null,null,'園庭で季節の変化を見つける。',0);
    """)
os.environ.update(HOIKUICT_ENV="test", HOIKUICT_COOKIE_SECURE="0",
    HOIKU_ANNUAL_LIBRARY_SOURCES=json.dumps({user.nursery_ref: [{"id": "sample", "path": str(annual_path)}]}),
    HOIKU_MONTHLY_LIBRARY_SOURCES=json.dumps({user.nursery_ref: {"id": "sample", "path": str(fixture.corpus)}}),
    HOIKU_DAILY_PLAN_EXAMPLES_DB_PATH=str(daily.corpus_path), HOIKU_BUNREI_DB_PATH=str(shared_path),
    HOIKU_FACILITY_BUNREI_DB_PATH=str(tmp / "old-facility.sqlite"))

MODES = {"partial": "入力途中・新旧が混在", "empty": "未入力", "filled": "入力済み", "error": "一覧の読込エラー"}
engines = {}
for name in ("partial", "empty", "filled"):
    path = tmp / f"{name}.sqlite"
    with fixture.engine.connect() as initial, closing(sqlite3.connect(path)) as dest:
        initial.connection.driver_connection.backup(dest)
    engines[name] = create_engine(f"sqlite:///{path.as_posix()}", connect_args={"check_same_thread": False})

def scene(request):
    key = request.cookies.get("plan_mock_scene", "partial")
    return key if key in MODES else "partial"

def engine_for(request):
    return engines.get(scene(request), engines["partial"])

def preview_session(request: Request):
    with Session(engine_for(request)) as session:
        yield session

app.dependency_overrides[database.get_session] = preview_session
app.dependency_overrides[resolve_plan_docs_staff_user] = lambda: user
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"])
for module in (home, annual_library, monthly_library, weekly_library, documents, bunrei, plans):
    app.include_router(module.router, prefix="/plans")

def format_name(document):
    sheet_fields = {DocumentType.ANNUAL_PLAN: "annual_sheet", DocumentType.MONTHLY_PLAN: "monthly_sheet",
                    DocumentType.WEEKLY_PLAN: "weekly_sheet"}
    if document.document_type == DocumentType.DAILY_PLAN:
        return "自園の帳票"
    field = sheet_fields.get(document.document_type)
    if field:
        return "旧式" if getattr(document, field) is None else "自園の帳票"
    return ""

@app.get("/plans/legacy/")
def legacy(request: Request, user: CurrentUser, repository: DocumentRepositoryDep):
    visible = repository.list(nursery_ref=user.nursery_ref, classroom_refs=None if user.is_admin else user.classroom_refs)
    old = [d for d in visible if format_name(d) == "旧式" and documents._can_view_document(d, user, repository)]
    return render_template(request, "legacy.html", user=user, documents=old)

def calendar_template(request, template_name, **context):
    if template_name == "weekly_library/calendar.html":
        monthly, teacher, classroom = context["monthly"], context["user"], context["classroom"]
        kind = DocumentType.MONTHLY_PLAN if monthly else DocumentType.WEEKLY_PLAN
        with Session(engine_for(request)) as session:
            found = SqlModelDocumentRepository(session).list(nursery_ref=teacher.nursery_ref,
                classroom_refs=(classroom.name,), document_type=kind)
        ages = ("", None, f'{context["age"]}歳児')
        old = [d for d in found if format_name(d) == "旧式" and d.status != DocumentStatus.ARCHIVED and d.age_class in ages]
        for card in context["cards"]:
            card["documents"] = [d for d in card["documents"] if format_name(d) == "自園の帳票"]
            card["old_documents"] = [d for d in old if (d.target_month if monthly else d.week_start_date) == card["key"]]
    return render_template(request, template_name, **context)

# Only the review process overlays the deployed templates.
weekly_library.render_template = calendar_template
def original(name):
    return (src / "templates" / name).read_text(encoding="utf-8")

calendar_name = "plan_docs/weekly_library/calendar.html"
calendar = original(calendar_name)
begin = calendar.index("{% for d in card.documents %}")
end = calendar.index("</article>", begin)
calendar = calendar[:begin] + """{% for d in card.old_documents %}<p class="old-in-calendar">
    <a href="/plans/documents/{{ d.id }}">旧式を開く · {{ d.title }}</a>
    <small>{{ d.status_label }}</small></p>{% endfor %}""" + calendar[end:]
calendar = (calendar.replace('<span class="status">{{ card.documents', '<span class="status">自園の帳票 · {{ card.documents')
            .replace("'計画を開く'", "'自園の帳票を開く'").replace("'＋ 作成'", "'自園の帳票で作成'")
            .replace("この月の計画はまだありません。", "この月の自園の帳票はまだありません。"))
home_source = original("plan_docs/home.html")
base = original("base.html").replace("https://cdn.tailwindcss.com", "/mock/tailwind.js")
base = base.replace('<script src="https://unpkg.com/htmx.org@1.9.10"></script>', "")
base = base.replace("{% block content %}", '{% include "controls.html" %}{% block content %}')
base = base.replace("</head>", '<link rel="stylesheet" href="/mock/preview.css"></head>')
base = base.replace("</body>", '{% include "preview-scope.html" %}</body>')
list_name = "plan_docs/documents/_list.html"
rows = original(list_name).replace("<small>クラス:", """<small>{% set label = format_name(document) %}
    {% if label %}<span class="format-label {{ 'old' if label == '旧式' else '' }}">{{ label }}</span>{% endif %}クラス:""")
rows = rows.replace("年案または月案の作成から始められます。", "保存すると、ここに表示されます。")
rows = """{% if scene(request) == 'error' %}<div class="preview-error" role="alert">
    <p>帳票の一覧を読み込めませんでした。</p><a href="/mock/retry?view={{ request.url.path }}">もう一度読み込む</a>
    </div>{% else %}""" + rows + "{% endif %}"
annual_form = "plan_docs/annual_plans/form.html"
overrides = {"base.html": base, calendar_name: calendar, list_name: rows,
    "review-notices.html": home_source[home_source.index("{% if reflection_reminders %}"):home_source.index('<section class="work-grid">')],
    annual_form: original(annual_form).replace("既存の年案を引き継ぐ・開く（1歳児）", "自園の年案を引き継ぐ・開く")}
templates.env.loader = ChoiceLoader([FileSystemLoader(HERE / "templates"), DictLoader(overrides), templates.env.loader])
templates.env.globals.update(format_name=format_name, preview_modes=MODES, scene=scene)

for directory in ("css", "js", "fonts"):
    app.mount(f"/static/{directory}", StaticFiles(directory=src / "static" / directory))

@app.get("/mock/tailwind.js")
def tailwind():
    return FileResponse(ROOT / "tools/staff-manual-preview/dist/assets/tailwind.js")

@app.get("/mock/preview.css")
def css():
    return FileResponse(HERE / "preview.css")

def change_scene(key, path):
    response = RedirectResponse(path, status_code=303)
    response.set_cookie("plan_mock_scene", key, httponly=True, samesite="strict")
    return response

@app.get("/mock/scenes/{key}")
def switch(key: str):
    if key not in MODES:
        raise HTTPException(404)
    return change_scene(key, "/plans/")

@app.get("/mock/retry")
def retry(view: str):
    allowed = {"/plans/", "/plans/legacy/", "/plans/documents/"}
    return change_scene("partial", view if view in allowed else "/plans/")

@app.get("/")
def index():
    return RedirectResponse("/plans/")

def seed(name):
    with TestClient(app) as client:
        client.get(f"/mock/scenes/{name}")
        client.headers["X-CSRF-Token"] = client.cookies["hoikuict_csrf"]
        def post(path, **options):
            result = client.post("/plans/" + path, follow_redirects=False, **options)
            if result.status_code not in (200, 303):
                raise RuntimeError(f"{path}: {result.status_code} {result.text[:400]}")
            return result
        def old(slug, **values):
            return post(slug, data={"classroom_ref": "さくら組", "owner_name": user.name, **values})
        old("annual-plans", school_year="2026", class_outlook="園庭での発見を友だちと楽しむ。")
        for month in ("2026-10", "2026-11"):
            old("monthly-plans", target_month=month, play_interests="木の実を集めて遊ぶ。")
        for week in ("2026-W45", "2026-W46"):
            old("weekly-plans", target_week=week, age_class="0歳児", weekly_activities_note="落ち葉の手触りを楽しむ。")
        boot = client.get("/plans/monthly-library/context", params={"target_month": "2026-11", "age": 0, "classroom_id": 1}).json()
        post("monthly-library/save", json=fixture.payload(boot, {"common:goal": {"body": "保育者と一緒に秋の自然に触れる。"}}))
        sheet = blank_sheet()
        sheet.update(aim="落ち葉の音に耳をすます。", activity="園庭を散歩する。")
        post("weekly-library/save", json={"classroom_id": 1, "month": "2026-11", "age": 0,
            "items": [{"week_start": "2026-11-09", "lock_version": 0, "sheet": sheet, "owner_name": user.name}]})
        if name == "filled":
            old("daily-plans", target_date="2026-11-09", age_class="0歳児", daily_aims="安心して外気に触れる。",
                daily_content="園庭で秋を感じる。", timeline_time="10:00", timeline_activity="園庭で散歩",
                timeline_children="葉に手を伸ばす。", timeline_support="そばで見守る。", timeline_considerations="防寒を確かめる。")
            annual = client.get("/plans/annual-library/context", params={"classroom_id": 1, "school_year": 2026, "source_key": "sample"}).json()
            from test_annual_library import AnnualLibraryTests
            post("annual-library/save", json=AnnualLibraryTests().payload(annual))

if __name__ == "__main__":
    try:
        for name in ("partial", "filled"):
            seed(name)
        uvicorn.run(app, host="127.0.0.1", port=args.port, access_log=False)
    finally:
        for engine in engines.values():
            engine.dispose()
        fixture.tearDown()
