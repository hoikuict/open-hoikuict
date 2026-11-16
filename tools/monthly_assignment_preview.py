"""Isolated permission-design mock. Run: python -m tools.monthly_assignment_preview.

Reuses the deployed monthly sheet and save/export storage against an in-memory
test database. Assignment, presence and cell-merge overlays belong only to this
mock; production authorization and save routes are not changed by these files.
"""
from calendar import monthrange
from datetime import date
import json
import os
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlmodel import Session, select
import uvicorn

from models import Child, Classroom
from plan_docs.auth_adapter import StaffUser, resolve_plan_docs_staff_user
from plan_docs.contracts import DocumentStatus, DocumentType, Role
from plan_docs.models import PlanDocument
from plan_docs.routers import monthly_library as monthly
from plan_docs.store import SqlModelDocumentRepository
from test_monthly_library import MonthlyLibraryTests
from tools.monthly_library_preview_data import COMMON, PERSONAL, GROUP, seed_preview_phrases
from tools.monthly_cell_merge_preview import CellMergePreview

ROOT = Path(__file__).resolve().parents[1]
ACTORS = {
    "teacher_a": ("架空職員A（A組の主担当）", Role.CAN_EDIT, [(1, "2026-09-01", "2026-10-31", "主担当")]),
    "teacher_b": ("架空職員B（B組の主担当）", Role.CAN_EDIT, [(2, "2026-10-01", None, "主担当")]),
    "support": ("架空職員C（A組・B組の補助）", Role.CAN_EDIT, [(1, "2026-10-01", None, "補助"), (2, "2026-10-01", None, "補助")]),
    "temporary": ("架空職員D（10月31日だけA組）", Role.CAN_EDIT, [(1, "2026-10-31", "2026-10-31", "臨時")]),
    "unassigned": ("架空職員E（担当なし）", Role.CAN_EDIT, []),
    "admin_none": ("架空管理者（担当なし）", Role.ADMIN, []),
    "admin_a": ("架空管理者（A組担当）", Role.ADMIN, [(1, "2026-10-01", None, "主担当")]),
    "viewer": ("架空職員F（A組担当・閲覧のみ）", Role.VIEW_ONLY, [(1, "2026-10-01", None, "主担当")]),
}
DATASETS = {"partial": "一部入力", "filled": "入力済み", "empty": "未入力", "approved": "承認済み"}


def assignment_permission(actor, classroom_id, target_month, revoked=False):
    """Mock policy: a single inclusive day of overlap counts as an assignment."""
    label, role, assignments = ACTORS[actor]
    year, month = map(int, target_month.split("-"))
    first, last = date(year, month, 1), date(year, month, monthrange(year, month)[1])
    if role == Role.VIEW_ONLY:
        return False, "閲覧のみの職員権限です。担当割当があっても編集はできません。"
    if revoked:
        return False, "担当割当が解除されました。この月案は保存できません。"
    matching = [a for a in assignments if a[0] == classroom_id and date.fromisoformat(a[1]) <= last
                and (a[2] is None or date.fromisoformat(a[2]) >= first)]
    if matching:
        return True, f"対象月の担当（{matching[0][3]}）として編集できます。変更は「下書きを保存」で保存します。"
    return False, "このクラス・対象月の担当に割り当てられていないため、閲覧のみです。管理者も担当割当が必要です。"


class AssignmentPreview:
    def __init__(self):
        self.fixture = MonthlyLibraryTests()
        self.fixture.setUp()
        self.app = self.fixture.app
        # setUp exercised the fixture once; rebuild its stack with mock-only guards.
        self.app.middleware_stack = None
        self.app.state.monthly_library_fixture = True
        os.environ["HOIKUICT_COOKIE_SECURE"] = "0"
        os.environ["HOIKU_MONTHLY_OLLAMA_SOURCES"] = "{}"
        self.revoked = set()
        seed_preview_phrases(self.fixture.corpus)
        self.fixture.corpus_bytes = self.fixture.corpus.read_bytes()
        os.environ["HOIKU_MONTHLY_LIBRARY_SOURCES"] = json.dumps({
            f"assignment-preview-{key}": {"id": "fixture", "path": str(self.fixture.corpus)} for key in DATASETS})
        self.original_context = monthly._context
        self.cell_merge = CellMergePreview(self, ACTORS)
        self.seed()
        monthly._context = self.context
        self.app.dependency_overrides[resolve_plan_docs_staff_user] = self.user
        self.install_routes()

    def seed(self):
        with Session(self.fixture.engine) as session:
            for i in range(3, 19):
                session.add(Child(id=i, last_name="架空", first_name=str(i), last_name_kana="カクウ",
                    first_name_kana=str(i), birth_date=date(2025, 5, 1), enrollment_date=date(2025, 6, 1),
                    classroom_id=1 if i <= 9 else 2))
            session.commit()
            repository = SqlModelDocumentRepository(session)
            for dataset in ("partial", "filled", "approved"):
                for classroom in session.exec(select(Classroom)).all():
                    for month in ("2026-07", "2026-08", "2026-09", "2026-10", "2026-11"):
                        for age in range(6):
                            sheet = monthly.new_sheet(session, classroom, month, age)
                            examples = {key: value[0] for key, value in COMMON.items()}
                            if age < 3:
                                for child in sheet["children"]:
                                    examples.update({f"{child['ref']}:{key}": value[0] for key, value in PERSONAL[age].items()})
                            else:
                                examples.update({f"group:{domain}:{column}": text[0]
                                    for domain, values in GROUP.items()
                                    for column, text in zip(("goal", "environment", "expected", "support"), values)})
                                examples["group:food"] = "食材の色や香りに興味をもつ。"
                                examples["event:10"] = "秋の散歩（架空）"
                            allowed = monthly.field_definitions(sheet, month)
                            examples = {k: v for k, v in examples.items() if k in allowed}
                            if dataset == "partial":
                                examples = {k: v for i, (k, v) in enumerate(examples.items()) if i % 3 == 0}
                            sheet["fields"] = {k: {"body": v, "origins": []} for k, v in examples.items()}
                            repository.create(PlanDocument(id=0, document_type=DocumentType.MONTHLY_PLAN,
                                title=f"{month} 月案（{classroom.name}・{age}歳児）", nursery_ref=f"assignment-preview-{dataset}",
                                classroom_ref=classroom.name, actor_ref="staff:preview-seed", owner_name="架空の担任",
                                status=DocumentStatus.APPROVED if dataset == "approved" else DocumentStatus.DRAFT,
                                sections=[], monthly_sheet=sheet, target_month=month, age_class=f"{age}歳児", school_year=2026))

    def user(self, request: Request):
        actor = request.cookies.get("assignment_presence_actor", "teacher_a")
        dataset = request.cookies.get("assignment_presence_dataset", "partial")
        actor = actor if actor in ACTORS else "teacher_a"
        dataset = dataset if dataset in DATASETS else "partial"
        name, role, _ = ACTORS[actor]
        return StaffUser(role=role, actor_ref=f"staff:{actor}", nursery_ref=f"assignment-preview-{dataset}",
                         classroom_refs=("A組", "B組"), name=name)

    def context(self, user, repository, classroom_id, target_month, age, document_id=None):
        result = self.original_context(user, repository, classroom_id, target_month, age, document_id)
        permitted, reason = assignment_permission(user.staff_id, classroom_id, target_month, user.staff_id in self.revoked)
        if permitted and not result["editable"]:
            reason = "承認済みなど、本文を編集できない状態の月案です。担当者も閲覧のみです。"
        result["editable"] = result["editable"] and permitted
        result["preview_permission"] = reason
        document = repository.get(result["document_id"]) if result["document_id"] else None
        result["preview_peer_names"] = [values[0].split("（")[0] for actor, values in ACTORS.items()
            if actor != user.staff_id and (document is None or document.can_edit_body)
            and assignment_permission(actor, classroom_id, target_month, actor in self.revoked)[0]]
        result["preview_base_token"] = self.cell_merge.issue(user, result)
        return result

    def install_routes(self):
        app = self.app
        template = Environment(loader=FileSystemLoader([str(ROOT / "tools/monthly_assignment_preview"),
            str(ROOT / "templates")]), autoescape=select_autoescape()).get_template("page.html")

        @app.middleware("http")
        async def restrict_mock(request, call_next):
            path = request.url.path
            # Limit this test app to the sheet, its resources, and mock controls.
            if not (path in ("/", "/preview", "/preview/state", "/preview/revoke", "/preview/restore", "/preview/ui.js", "/preview/presence.js", "/preview/cell-save", "/preview/cell-peer")
                    or path.startswith(("/static/", "/plans/monthly-library"))):
                return HTMLResponse("この画面見本では月案の帳票だけ操作できます。ブラウザーの戻るで戻ってください。", status_code=404)
            if request.method == "POST" and path.startswith("/plans/monthly-library"):
                if path == "/plans/monthly-library/export-file":
                    from urllib.parse import parse_qs
                    form = parse_qs((await request.body()).decode())
                    payload = json.loads(form.get("snapshot", ["{}"])[0])
                else:
                    payload = await request.json()
                if path.endswith(("/save", "/generate")) or payload.get("mode") == "current":
                    user = self.user(request)
                    allowed, reason = assignment_permission(user.staff_id, int(payload.get("classroom_id", 0)),
                        payload.get("target_month", "2026-10"), user.staff_id in self.revoked)
                    if not allowed:
                        return JSONResponse({"detail": reason}, status_code=403)
            response = await call_next(request)
            response.headers["Cache-Control"] = "no-store"
            return response

        @app.get("/")
        def home():
            return RedirectResponse("/preview")

        @app.get("/preview", response_class=HTMLResponse)
        def page(request: Request, classroom_id: int = 1, target_month: str = "2026-10", age: int = 1):
            user = self.user(request)
            with Session(self.fixture.engine) as session:
                boot = self.context(user, SqlModelDocumentRepository(session), classroom_id, target_month, age)
                classrooms = session.exec(select(Classroom)).all()
            return HTMLResponse(template.render(request=request, boot=boot, classrooms=classrooms,
                actor=user.staff_id, dataset=user.nursery_ref.removeprefix("assignment-preview-"),
                actors=ACTORS, datasets=DATASETS, csrf_token=request.state.csrf_token,
                static_asset_url=lambda path: "/preview/ui.js" if path == "js/monthly-library.js" else "/static/" + path))

        @app.post("/preview/state")
        async def state(request: Request):
            data = await request.json()
            if data.get("actor") not in ACTORS or data.get("dataset") not in DATASETS:
                raise HTTPException(422, "確認用の職員・入力状態を選んでください")
            self.revoked.discard(data["actor"])
            response = JSONResponse({"ok": True})
            for key in ("actor", "dataset"):
                response.set_cookie("assignment_presence_" + key, data[key], httponly=True, samesite="strict")
            return response

        @app.post("/preview/revoke")
        def revoke(request: Request):
            self.revoked.add(self.user(request).staff_id)
            return {"ok": True}

        @app.post("/preview/restore")
        def restore(request: Request):
            self.revoked.discard(self.user(request).staff_id)
            return {"ok": True}

        @app.get("/preview/ui.js")
        def script():
            script = (ROOT / "static/js/monthly-library.js").read_text(encoding="utf-8")
            for before, after in (
                ("function status() {", "function status() { window.renderPreviewPermission(ctx());"),
                ("function highlight() {", "function highlight() { window.renderPreviewPresence?.(ctx(), current.field);"),
                ("q('#save').hidden = !editable();", "q('#save').hidden = false;"),
                ("q('#save').disabled = saving;", "q('#save').disabled = saving || !editable();"),
                ("q('#save').textContent = saving ? '保存中…' : '下書きを保存';", "q('#save').textContent = !editable() ? '閲覧のみ（保存不可）' : saving ? '保存中…' : '下書きを保存';"),
                ("閲覧中です。修正は月案の編集画面から行います。", "閲覧中です。この月案には文例を追記できません。"),
            ):
                assert script.count(before) == 1, "Recheck mock hooks after changing the deployed sheet"
                script = script.replace(before, after)
            start = script.index("  async function save() {")
            end = script.index("  function exportMonthly(kind)", start)
            script = script[:start] + (ROOT / "tools/monthly_assignment_preview/cell-save.js").read_text(encoding="utf-8") + "\n" + script[end:]
            return Response(script, media_type="application/javascript")

        @app.get("/preview/presence.js")
        def presence_script():
            return Response((ROOT / "tools/monthly_assignment_preview/presence.js").read_text(encoding="utf-8"),
                            media_type="application/javascript")

        app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
        self.cell_merge.install(app)

    def close(self):
        monthly._context = self.original_context
        self.fixture.tearDown()


if __name__ == "__main__":
    preview = AssignmentPreview()
    try:
        uvicorn.run(preview.app, host="127.0.0.1", port=int(os.getenv("MONTHLY_ASSIGNMENT_PREVIEW_PORT", "8902")), log_level="warning")
    finally:
        preview.close()
