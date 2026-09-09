"""Presentation and response handling for a shared guardian terminal."""
from fastapi import HTTPException, Request
from fastapi.routing import APIRoute

from security_config import secure_cookie_enabled
from template_utils import create_templates
from time_utils import local_today

TERMINAL_COOKIE = "hoikuict_guardian_terminal"
TERMINAL_START = "/guardian/terminal"
TERMINAL_IDLE_SECONDS = 90
templates = create_templates()


def is_terminal(request: Request) -> bool:
    return bool(getattr(request.state, "guardian_terminal", False) or request.cookies.get(TERMINAL_COOKIE) == "1")


def render_guardian(request: Request, name: str, context: dict, *, status_code: int = 200):
    return templates.TemplateResponse(request, name, {
        **context,
        "terminal_mode": is_terminal(request),
        "terminal_today": local_today().isoformat(),
        "terminal_start": TERMINAL_START,
        "terminal_idle_seconds": TERMINAL_IDLE_SECONDS,
        "terminal_ready": name not in {"guardian/activate.html", "guardian/terminal_error.html"},
    }, status_code=status_code)


def remember_terminal(response) -> None:
    # This cookie changes presentation only; the signed device cookie still grants access.
    response.set_cookie(TERMINAL_COOKIE, "1", max_age=365 * 24 * 60 * 60,
                        httponly=True, secure=secure_cookie_enabled(), samesite="strict", path="/guardian")


class GuardianRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handle(request: Request):
            try:
                response = await original(request)
            except HTTPException as exc:
                if not is_terminal(request) or request.url.path == "/guardian/setup":
                    raise
                response = render_guardian(request, "guardian/terminal_error.html", {
                    "request": request,
                    "message": str(exc.detail) if exc.status_code in {400, 409} else "端末登録または接続を確認してください。職員にお知らせください。",
                }, status_code=exc.status_code)
            response.headers["Cache-Control"] = "no-store"
            response.headers["Referrer-Policy"] = "no-referrer"
            return response

        return handle
