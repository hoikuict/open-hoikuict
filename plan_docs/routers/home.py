from __future__ import annotations

from fastapi import APIRouter, Request

from ..auth_adapter import CurrentUser
from ..store import document_store
from ..templating import render_template


router = APIRouter(tags=["home"])


@router.get("/")
def home(request: Request, user: CurrentUser):
    classroom_refs = None if user.is_admin else user.classroom_refs
    documents = document_store.list(nursery_ref=user.nursery_ref, classroom_refs=classroom_refs)
    return render_template(
        request,
        "home.html",
        user=user,
        documents=documents[:8],
    )
