from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from auth import get_current_staff_user, require_child_record_manager
from database import get_session
from family_care_service import bootstrap, save_family, deactivate_family
from models import Family
from routers.children import templates
from routers.extended_care_bands import read_payload

router = APIRouter(prefix="/families", tags=["family-care"])


def get_family(session, family_id):
    family = session.get(Family, family_id)
    if family is None:
        raise HTTPException(404, "家族が見つかりません。")
    return family


@router.get("/{family_id}/care-certifications")
def page(family_id: int, request: Request, session: Session = Depends(get_session),
         current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    family = get_family(session, family_id)
    return templates.TemplateResponse(request, "families/care_certifications.html", dict(
        current_user=current_user, family=family, care_state=bootstrap(session, family)),
        headers={"Cache-Control": "private, no-store"})


@router.post("/{family_id}/care-certifications/{action}")
async def update(family_id: int, action: str, request: Request,
                 session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    if action not in ("save", "deactivate", "preview"):
        raise HTTPException(404)
    payload = await read_payload(request)
    if session.get_bind().dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    family = get_family(session, family_id)
    try:
        result = (deactivate_family if action == "deactivate" else save_family)(session, family, payload, current_user)
        if action == "preview":
            session.rollback()
            return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
        session.commit()
        result = bootstrap(session, family)
    except ValueError as exc:
        session.rollback()
        raise HTTPException(400, str(exc)) from exc
    return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
