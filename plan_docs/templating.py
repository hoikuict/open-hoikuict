from __future__ import annotations

from fastapi import Request
from template_utils import create_templates


templates = create_templates(directory="templates")


def render_template(request: Request, template_name: str, **context):
    if not template_name.startswith("plan_docs/"):
        template_name = f"plan_docs/{template_name}"
    user = context.get("user")
    if user is not None and "current_user" not in context:
        context["current_user"] = user
    return templates.TemplateResponse(request, template_name, {"request": request, **context})

