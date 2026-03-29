from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from auth import MOCK_ROLE_COOKIE, Role
from database import (
    bootstrap_family_records,
    create_db_and_tables,
    initialize_demo_template_database,
    seed_classroom_data,
    seed_staff_data,
    seed_parent_portal_data,
    seed_sample_data,
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
from routers.child_change_requests import router as child_change_requests_router
from routers.children import router as children_router
from routers.classrooms import router as classrooms_router
from routers.daily_contacts import router as daily_contacts_router
from routers.families import router as families_router
from routers.guardian import router as guardian_router
from routers.meeting_notes import router as meeting_notes_router
from routers.notices import router as notices_router
from routers.parent_accounts import router as parent_accounts_router
from routers.parent_portal import router as parent_portal_router
from routers.staff_auth import router as staff_auth_router
from routers.staff import router as staff_router
from routers.staff_rooms import router as staff_rooms_router

app = FastAPI(title="open-hoikuict", version="0.1.0")
app.include_router(staff_router)
app.include_router(staff_auth_router)
app.include_router(classrooms_router)
app.include_router(families_router)
app.include_router(children_router)
app.include_router(child_change_requests_router)
app.include_router(attendance_router)
app.include_router(attendance_checks_router)
app.include_router(guardian_router)
app.include_router(parent_accounts_router)
app.include_router(parent_portal_router)
app.include_router(meeting_notes_router)
app.include_router(notices_router)
app.include_router(daily_contacts_router)
app.include_router(staff_rooms_router)


def _content_length(header_value: str | None) -> int:
    if not header_value:
        return 0
    try:
        return max(int(header_value), 0)
    except (TypeError, ValueError):
        return 0


def _limit_response(status_code: int, title: str, message: str) -> HTMLResponse:
    body = f"""
    <!doctype html>
    <html lang="en">
      <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>{title}</title>
        <style>
          body {{
            font-family: sans-serif;
            margin: 0;
            background: #f7f4ee;
            color: #222;
          }}
          main {{
            max-width: 720px;
            margin: 48px auto;
            padding: 24px;
            background: white;
            border-radius: 16px;
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.08);
          }}
          a {{
            color: #0b57d0;
          }}
        </style>
      </head>
      <body>
        <main>
          <h1>{title}</h1>
          <p>{message}</p>
          <p><a href="/">Return to the demo</a></p>
        </main>
      </body>
    </html>
    """
    return HTMLResponse(body, status_code=status_code)


@app.middleware("http")
async def public_demo_middleware(request: Request, call_next):
    if not is_public_demo_enabled():
        return await call_next(request)

    settings = load_demo_settings()
    manager = get_demo_session_manager()
    manager.cleanup_expired_sessions()

    incoming_session_id = request.cookies.get(DEMO_SESSION_COOKIE_NAME)
    session_id, should_set_cookie = manager.ensure_session_id(incoming_session_id)
    request.state.demo_session_id = session_id
    manager.ensure_session_database(session_id)
    manager.touch_session(session_id)

    if request.method in MUTATING_METHODS:
        body_bytes = _content_length(request.headers.get("content-length"))
        if body_bytes > settings.max_request_body_bytes:
            return _limit_response(
                413,
                "Request too large",
                f"Each write request is limited to {settings.max_request_body_bytes} bytes in public demo mode.",
            )

        allowed, _ = manager.reserve_input_budget(session_id, body_bytes)
        if not allowed:
            return _limit_response(
                413,
                "Session input limit reached",
                "This demo session has reached its write limit. Start a new browser session to reset the data.",
            )

    response = await call_next(request)
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


@app.on_event("startup")
def on_startup():
    if is_public_demo_enabled():
        get_demo_session_manager().prepare_base_database(initialize_demo_template_database)
        return

    create_db_and_tables()
    seed_classroom_data()
    seed_staff_data()
    seed_sample_data()
    bootstrap_family_records()
    seed_parent_portal_data()


@app.get("/")
def root():
    return RedirectResponse(url="/children")


@app.get("/switch-role")
def switch_role(request: Request, role: str = "can_edit", redirect: str = "/children/"):
    """
    モック用：権限レベルを切り替える。
    role: view_only | can_edit | admin
    """
    if role in [r.value for r in Role]:
        response = RedirectResponse(url=redirect, status_code=303)
        settings = load_demo_settings()
        cookie_options = {
            "httponly": True,
            "samesite": "lax",
            "secure": should_use_secure_cookies(request, settings),
        }
        if not settings.enabled:
            cookie_options["max_age"] = 60 * 60 * 24
        response.set_cookie(MOCK_ROLE_COOKIE, role, **cookie_options)
        return response
    return RedirectResponse(url=redirect, status_code=303)
