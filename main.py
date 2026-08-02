import asyncio
import os
from contextlib import asynccontextmanager
from contextlib import suppress
from urllib.parse import urlencode

from dotenv import load_dotenv

# Load local development settings before importing modules that inspect the
# environment. Existing process environment variables always take precedence.
# A development .env may exist beside the application. Never merge it into an
# explicitly production process, because development-only values (mock auth,
# open kiosk mode, disabled CSRF) must not leak into the production runtime.
if (os.getenv("HOIKUICT_ENV") or "").strip().lower() != "production":
    load_dotenv()

from fastapi import Depends, FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from database import (
    bootstrap_health_records,
    bootstrap_family_records,
    create_db_and_tables,
    export_sqlite_snapshot,
    seed_calendar_data,
    seed_classroom_data,
    seed_debug_demo_data,
    seed_extended_care_fee_rules,
    seed_parent_portal_data,
    seed_sample_data,
    seed_staff_classroom_assignments,
)
from demo_runtime import (
    DEMO_SESSION_COOKIE_NAME,
    MUTATING_METHODS,
    get_demo_session_manager,
    is_public_demo_enabled,
    load_demo_settings,
    should_use_secure_cookies,
)
from routers.attendance import router as attendance_router
from routers.attendance_checks import router as attendance_checks_router
from routers.billing import router as billing_router
from routers.calendar import mock_login_router as calendar_mock_login_router
from routers.calendar import router as calendar_router
from routers.child_change_requests import router as child_change_requests_router
from routers.children import router as children_router
from routers.child_health import router as child_health_router
from routers.classrooms import router as classrooms_router
from routers.data_transfers import router as data_transfers_router
from routers.data_transfers import _cleanup_stale_previews
from routers.daily_contacts import router as daily_contacts_router
from routers.extended_care_fees import router as extended_care_fees_router
from routers.families import router as families_router
from routers.guardian import router as guardian_router
from routers.institutional_records import event_series_router
from routers.institutional_records import highlights_router
from routers.institutional_records import router as institutional_records_router
from routers.meeting_notes import router as meeting_notes_router
from routers.notices import router as notices_router
from routers.parent_accounts import router as parent_accounts_router
from routers.parent_portal import mock_login_router as parent_portal_mock_login_router
from routers.parent_portal import router as parent_portal_router
from routers.staff_auth import mock_login_router as staff_mock_login_router
from routers.staff_auth import router as staff_auth_router
from routers.staff_portal import router as staff_portal_router
from routers.staff_rooms import router as staff_rooms_router
from routers.staff_surveys import router as staff_surveys_router
from routers.surveys import router as surveys_router
from routers.zengin import router as zengin_router
from plan_docs.runtime import ensure_runtime_files
from plan_docs.routers.bunrei import router as plan_docs_bunrei_router
from plan_docs.routers.documents import router as plan_docs_documents_router
from plan_docs.routers.home import router as plan_docs_home_router
from plan_docs.routers.plans import router as plan_docs_plans_router
from url_utils import safe_internal_redirect
from auth import mock_auth_enabled, require_mock_staff_auth, staff_auth_http_exception_handler
from csrf import CsrfTokenMiddleware, verify_csrf
from security_config import validate_runtime_security
from starlette.exceptions import HTTPException as StarletteHTTPException


def initialize_application() -> None:
    validate_runtime_security()
    _cleanup_stale_previews()
    ensure_runtime_files()
    if is_public_demo_enabled():
        from scripts.seed_demo_100 import seed as seed_demo_100

        seed_demo_100(wipe=True)
        seed_staff_classroom_assignments()
        get_demo_session_manager().prepare_base_database(export_sqlite_snapshot)
        return

    create_db_and_tables()
    seed_classroom_data()
    seed_extended_care_fee_rules()
    seed_sample_data()
    bootstrap_family_records()
    bootstrap_health_records()
    seed_parent_portal_data()
    seed_calendar_data()
    seed_staff_classroom_assignments()
    if mock_auth_enabled():
        seed_debug_demo_data()


@asynccontextmanager
async def lifespan(app: FastAPI):
    initialize_application()
    cleanup_task = asyncio.create_task(_preview_cleanup_loop())
    try:
        yield
    finally:
        cleanup_task.cancel()
        with suppress(asyncio.CancelledError):
            await cleanup_task


async def _preview_cleanup_loop() -> None:
    while True:
        await asyncio.sleep(60 * 60)
        await asyncio.to_thread(_cleanup_stale_previews)


app = FastAPI(
    title="open-hoikuict",
    version="0.1.0",
    lifespan=lifespan,
    dependencies=[Depends(verify_csrf)],
)
app.add_exception_handler(StarletteHTTPException, staff_auth_http_exception_handler)
app.add_middleware(CsrfTokenMiddleware)


def _content_length(header_value: str | None) -> int:
    if not header_value:
        return 0
    try:
        return max(int(header_value), 0)
    except (TypeError, ValueError):
        return 0


def _incoming_demo_session_id(request: Request) -> str | None:
    return (
        request.cookies.get(DEMO_SESSION_COOKIE_NAME)
        or request.headers.get("x-demo-session-id")
        or request.query_params.get(DEMO_SESSION_COOKIE_NAME)
    )


def _limit_response(status_code: int, title: str, message: str) -> HTMLResponse:
    return HTMLResponse(
        f"<h1>{title}</h1><p>{message}</p><p><a href='/'>デモに戻る</a></p>",
        status_code=status_code,
    )


@app.middleware("http")
async def public_demo_middleware(request: Request, call_next):
    if not is_public_demo_enabled():
        return await call_next(request)

    settings = load_demo_settings()
    manager = get_demo_session_manager()
    manager.cleanup_expired_sessions()

    cookie_session_id = request.cookies.get(DEMO_SESSION_COOKIE_NAME)
    session_id, should_set_cookie = manager.ensure_session_id(_incoming_demo_session_id(request))
    should_set_cookie = should_set_cookie or cookie_session_id != session_id
    request.state.demo_session_id = session_id
    manager.ensure_session_database(session_id)
    manager.touch_session(session_id)

    if request.method in MUTATING_METHODS:
        body_bytes = _content_length(request.headers.get("content-length"))
        if body_bytes > settings.max_request_body_bytes:
            return _limit_response(413, "Request too large", "1回の送信サイズが上限を超えました。")
        allowed, _ = manager.reserve_input_budget(session_id, body_bytes)
        if not allowed:
            return _limit_response(413, "Session input limit reached", "このデモセッションの書込み上限に達しました。")

    response = await call_next(request)
    response.headers["X-Demo-Session-Id"] = session_id
    if should_set_cookie:
        response.set_cookie(
            DEMO_SESSION_COOKIE_NAME,
            session_id,
            httponly=True,
            samesite="lax",
            secure=should_use_secure_cookies(request, settings),
            path="/",
        )
    return response

app.include_router(staff_portal_router)
app.include_router(classrooms_router)
app.include_router(data_transfers_router)
app.include_router(families_router)
app.include_router(children_router)
app.include_router(child_health_router)
app.include_router(child_change_requests_router)
app.include_router(attendance_router)
app.include_router(attendance_checks_router)
app.include_router(extended_care_fees_router)
app.include_router(billing_router)
app.include_router(guardian_router)
app.include_router(parent_accounts_router)
app.include_router(parent_portal_router)
app.include_router(calendar_router)
app.include_router(staff_auth_router)
app.include_router(institutional_records_router)
app.include_router(highlights_router)
app.include_router(event_series_router)
app.include_router(meeting_notes_router)
app.include_router(notices_router)
app.include_router(daily_contacts_router)
app.include_router(staff_rooms_router)
app.include_router(surveys_router)
app.include_router(staff_surveys_router)
app.include_router(zengin_router)
if mock_auth_enabled():
    app.include_router(staff_mock_login_router)
    app.include_router(parent_portal_mock_login_router)
    app.include_router(calendar_mock_login_router)
app.include_router(plan_docs_home_router, prefix="/plans")
app.include_router(plan_docs_plans_router, prefix="/plans")
app.include_router(plan_docs_documents_router, prefix="/plans")
app.include_router(plan_docs_bunrei_router, prefix="/plans")

@app.get("/switch-role", dependencies=[Depends(require_mock_staff_auth)])
def switch_role(redirect: str = "/"):
    target = safe_internal_redirect(redirect, "/")
    return RedirectResponse(url=f"/staff/login?{urlencode({'redirect': target})}", status_code=303)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
