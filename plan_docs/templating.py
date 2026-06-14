from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates


templates = Jinja2Templates(directory="templates")


def render_template(request: Request, template_name: str, **context):
    if not template_name.startswith("plan_docs/"):
        template_name = f"plan_docs/{template_name}"
    user = context.get("user")
    if user is not None and "current_user" not in context:
        context["current_user"] = user
    return templates.TemplateResponse(request, template_name, {"request": request, **context})

