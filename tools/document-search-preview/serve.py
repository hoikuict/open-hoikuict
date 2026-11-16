"""Read-only, localhost preview. Run with the project venv and --source <deployed checkout>."""
import argparse
from datetime import date
import json
import os
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from uuid import UUID

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=8088)
parser.add_argument("--source", type=Path, default=ROOT / ".local-dev/plan-navigation-rollout-20261108/source")
args = parser.parse_args()
source = args.source.resolve(strict=True)
os.chdir(source)
sys.path.insert(0, str(source))
os.environ.update(HOIKUICT_ENV="test", PYTHON_DOTENV_DISABLED="1", HOIKUICT_DATABASE_URL="sqlite://",
                  HOIKU_WEEKLY_LIBRARY_SOURCES="{}", HOIKU_MONTHLY_LIBRARY_SOURCES="{}")

from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine
from starlette.middleware.trustedhost import TrustedHostMiddleware
import uvicorn
import child_records.models
import database
from models import Child, Classroom, StaffClassroomAssignment, User
from plan_docs.auth_adapter import resolve_plan_docs_staff_user, StaffUser
from plan_docs.contracts import DocumentStatus as Status, DocumentType as Kind, Role
from plan_docs.models import PlanDocument, SectionBlock
from plan_docs.routers import documents, home
from plan_docs.services.annual_library import import_sheet
from plan_docs.store import SqlModelDocumentRepository
from plan_docs.templating import templates
from test_annual_library import source_fixture

user = StaffUser(Role.CAN_EDIT, "staff:00000000-0000-0000-0000-000000000123", "見本保育園",
                 ("さくら組", "すみれ組"), "見本 はなこ", UUID(int=0x123))
engine = create_engine("sqlite://", connect_args={"check_same_thread":False}, poolclass=StaticPool)

def seed(directory):
    annual = source_fixture()
    annual["source"].update(className="さくら組",title="さくら組 年間指導計画（見本）")
    annual_file = directory / "annual.json"
    annual_file.write_text(json.dumps(annual,ensure_ascii=False),encoding="utf-8")
    os.environ["HOIKU_ANNUAL_LIBRARY_SOURCES"] = json.dumps({user.nursery_ref:[{"id":"sample","path":str(annual_file)}]})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(User(id=user.user_id,email="staff@example.invalid",display_name=user.name,staff_role="can_edit"))
        session.add_all([Classroom(id=i,name=name) for i,name in enumerate((*user.classroom_refs,"対象外の組"),1)])
        session.commit()
        for i, name, room in [(1,"あおい",1),(2,"はる",2),(3,"なつ",1)]:
            session.add(Child(id=i,last_name="見本",first_name=name,last_name_kana="ミホン",
                first_name_kana=name,birth_date=date(2024,5,1),enrollment_date=date(2025,4,1),classroom_id=room))
        for i in (1,2):
            session.add(StaffClassroomAssignment(staff_user_id=user.user_id,classroom_id=i,starts_on=date(2025,4,1)))
        session.commit()
        repo = SqlModelDocumentRepository(session)

        def add(kind,title,room,status=Status.DRAFT,owner=user.name,**values):
            repo.create(PlanDocument(id=0,document_type=kind,title=title,status=status,nursery_ref=user.nursery_ref,
                classroom_ref=room,actor_ref=user.actor_ref,owner_name=owner,
                sections=[SectionBlock("goal","ねらい","季節の遊びを楽しむ。",["form.sample"],["入力"])],**values))

        def progress(child,child_name,room,status,start,end,owner):
            title = f"{child_name} 児童票（{start.replace('-','/')}〜{end.replace('-','/')}）"
            add(Kind.CHILD_PROGRESS_RECORD,title,room,status,owner,child_id=child,child_name=child_name,
                period_start=start,period_end=end)

        add(Kind.MONTHLY_PLAN,"表示対象外の見本","対象外の組",owner="対象外の職員",target_month="2026-11")
        add(Kind.WEEKLY_PLAN,"2026-11-02週 週案（すみれ組）","すみれ組",Status.REJECTED,
            "見本 たろう",week_start_date="2026-11-02",age_class="2歳児")
        add(Kind.INDIVIDUAL_PLAN,"見本 なつ 個別指導計画（11月）","さくら組",child_id=3,child_name="見本 なつ")
        add(Kind.MONTHLY_PLAN,"2026-11 月案（すみれ組）","すみれ組",Status.APPROVED,"見本 たろう",target_month="2026-11")
        progress(1,"見本 あおい","さくら組",Status.APPROVED,"2026-08-01","2026-09-30","見本 ゆい")
        progress(2,"見本 はる","すみれ組",Status.IN_REVIEW,"2026-10-01","2026-11-30","見本 たろう")
        progress(1,"見本 あおい","さくら組",Status.DRAFT,"2026-10-01","2026-11-30",user.name)
        sheet = import_sheet(user.nursery_ref,1,"sample")
        add(Kind.ANNUAL_PLAN,"2026年度 年間指導計画（さくら組・1歳児）","さくら組",annual_sheet=sheet,school_year=2026)
        add(Kind.DAILY_PLAN,"2026-11-11 日案（さくら組）","さくら組",Status.IN_REVIEW,target_date="2026-11-11")

def original(name):
    return (source/"templates"/name).read_text(encoding="utf-8")

def substitute(text, old, new):
    if text.count(old) != 1:
        raise ValueError(f"配備版のテンプレートを確認してください: {old}")
    return text.replace(old,new)

base = original("base.html").replace("https://cdn.tailwindcss.com","/preview/tailwind.js")
base = base.replace('<script src="https://unpkg.com/htmx.org@1.9.10"></script>', "")
base = substitute(base,"</head>", """<link rel="stylesheet" href="/preview/search.css">
<script defer src="/preview/scope.js"></script><script defer src="/preview/search.js"></script></head>""")
base = substitute(base, "{% block content %}", """<aside class="preview-controls no-print">
  <span>確認用モック · 架空データ</span>
  {% if current_path == '/plans/documents/' %}
  <label>試す場面 <select id="search-scene"><option value="">選んでください</option>
  <option value="empty">条件なし</option><option value="partial">園児名で探す</option>
  <option value="filled">条件を組み合わせる</option><option value="none">該当なし</option>
  <option value="error">検索エラー</option></select></label>
  {% endif %}</aside>{% block content %}""")
list_path = "plan_docs/documents/list.html"
listing = substitute(original(list_path), '<section class="section-block">','''<section class="section-block search-panel">
    {% include "search-form.html" %}<div id="document-results">''')
listing = substitute(listing,'{% include "plan_docs/documents/_list.html" %}','{% include "plan_docs/documents/_list.html" %}</div>')
rows_path = "plan_docs/documents/_list.html"
rows = substitute(original(rows_path),'class="document-row"', '''class="document-row"
      {% if request.url.path == '/plans/documents/' %}
        data-title="{{ document.title }}" data-child="{{ document.child_name or '' }}"
        data-owner="{{ document.owner_name }}" data-room="{{ document.classroom_label }}"
        data-kind="{{ document.document_type_label }}" data-status="{{ document.status_label }}"
        data-format="{{ document.plan_format_label }}"
      {% endif %}''')
detail_path = "plan_docs/documents/detail.html"
detail = substitute(original(detail_path),'{% block content %}','''{% block content %}
  <a class="preview-return no-print" id="back-to-list" href="/plans/documents/">‹ 帳票一覧に戻る</a>''')
templates.env.loader = ChoiceLoader([DictLoader({"base.html":base,list_path:listing,rows_path:rows,detail_path:detail}),
                                    FileSystemLoader(HERE),templates.env.loader])

app = FastAPI(docs_url=None,redoc_url=None,openapi_url=None)
app.add_middleware(TrustedHostMiddleware,allowed_hosts=["127.0.0.1","localhost"])
def sample_session():
    with Session(engine) as session:
        yield session
app.dependency_overrides[database.get_session] = sample_session
app.dependency_overrides[resolve_plan_docs_staff_user] = lambda: user
app.get("/plans/documents/")(documents.list_documents)
app.get("/plans/documents/{document_id}")(documents.document_detail)
app.get("/plans/")(home.home)

@app.get("/")
def index():
    return RedirectResponse("/plans/documents/")

assets = {"tailwind.js": ROOT/"tools/staff-manual-preview/dist/assets/tailwind.js",
          **{name: HERE/name for name in ("search.css","scope.js","search.js")}}
@app.get("/preview/{name}")
def preview_asset(name: str):
    from fastapi import HTTPException
    if name not in assets:
        raise HTTPException(404)
    return FileResponse(assets[name])

for folder in ("css","fonts","js"):
    app.mount("/static/"+folder,StaticFiles(directory=source/"static"/folder))

if __name__ == "__main__":
    with TemporaryDirectory() as temp:
        seed(Path(temp))
        uvicorn.run(app,host="127.0.0.1",port=args.port,access_log=False)
