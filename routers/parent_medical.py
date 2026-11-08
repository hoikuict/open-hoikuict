from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlmodel import Session, select

from auth import get_current_staff_user, require_can_edit, require_child_record_manager
from child_health_service import get_or_create_child_health_profile
from database import get_session
from models import Child, ParentAccount, ParentAccountStatus, ParentChildLink, ParentMedicalResponse
from parent_medical_service import (
    BLOOD_TYPES, FIELDS, STATES, UNANSWERED, XRAY_CHOICES, XRAY_QUESTION,
    current_values, form_answers, latest_answer, latest_consent, lock_child, require_current, revision,
)
from routers.parent_portal import _get_parent_account
from template_utils import create_templates
from time_utils import utc_now


router = APIRouter(tags=["parent_medical"])
templates = create_templates()
PARENT = "/parent-portal/children/{child_id}/medical"
STAFF = "/children/{child_id}/health/parent-medical"


def linked_parents(child_id):
    return select(ParentAccount).join(ParentChildLink).where(
        ParentChildLink.child_id == child_id, ParentAccount.status == ParentAccountStatus.active
    )


@router.get("/parent-portal/medical")
def medical_menu(request: Request, session: Session = Depends(get_session)):
    parent = _get_parent_account(request, session)
    if not parent:
        return RedirectResponse("/parent-portal/login", status_code=303)
    children = session.exec(
        select(Child).join(ParentChildLink).where(ParentChildLink.parent_account_id == parent.id)
        .order_by(Child.last_name_kana, Child.first_name_kana, Child.id)
    ).all()
    if len(children) == 1:
        return RedirectResponse(PARENT.format(child_id=children[0].id), status_code=303)
    return templates.TemplateResponse(request, "parent_portal/medical_children.html", {
        "children": children, "current_parent_user": parent, "parent_portal_mode": True,
    }, headers={"Cache-Control": "private, no-store"})


@router.api_route(PARENT, methods=["GET", "POST"])
async def medical_form(request: Request, child_id: int, session: Session = Depends(get_session)):
    form = await request.form() if request.method == "POST" else None
    parent = _get_parent_account(request, session)
    if not parent:
        return RedirectResponse("/parent-portal/login", status_code=303)
    if form is not None and form.get("action") == "send":
        lock_child(session, child_id)
    if not session.exec(linked_parents(child_id).where(ParentAccount.id == parent.id)).first():
        raise HTTPException(404, "園児が見つかりません。")
    child = session.get(Child, child_id)
    latest = latest_answer(session, child_id, parent.id)
    consent = latest_consent(session, child_id)
    baseline = current_values(session, child_id)
    version = revision(child_id, parent.id, baseline, latest, consent)
    draft = dict(baseline)
    if latest and latest.status in ("pending", "returned"):
        for key in FIELDS:
            if latest.before.get(key) == baseline[key]:
                draft[key] = latest.answers.get(key, baseline[key])
    xray = consent.xray_answer if consent and consent.parent_account_id == parent.id else None
    clear = bool(baseline["hospital_name"] and not draft["hospital_name"])
    step = "edit"
    error = ""
    stale = form is not None and version != form.get("revision")
    if stale:
        error = "内容が更新されました。下の最新の内容を確かめてから、もう一度回答してください。"
    elif form is not None:
        clear = form.get("clear_hospital") == "yes"
        action = form.get("action")
        if action not in ("edit", "preview", "send"):
            raise HTTPException(400, "操作を選び直してください。")
        try:
            draft, xray = form_answers(form, baseline)
        except ValueError as exc:
            draft = {key: str(form.get(key) or "") for key in FIELDS}
            xray = form.get("xray_answer")
            error = str(exc)
        else:
            if action == "preview":
                step = "review"
            elif action == "send":
                if latest and latest.status == "requested":
                    answer = latest
                else:
                    if latest and latest.status == "pending":
                        latest.status = "superseded"
                        session.add(latest)
                    answer = ParentMedicalResponse(child_id=child_id, parent_account_id=parent.id, parent_name=parent.display_name)
                answer.status = "pending"
                answer.submitted_at = utc_now()
                answer.before, answer.answers = baseline, draft
                answer.xray_answer, answer.xray_question = xray, XRAY_QUESTION
                session.add(answer)
                session.commit()
                return RedirectResponse(PARENT.format(child_id=child_id) + "?sent=1", status_code=303)
    return templates.TemplateResponse(request, "parent_portal/medical.html", {
        "current_parent_user": parent, "parent_portal_mode": True, "child": child, "latest": latest, "labels": FIELDS,
        "draft": draft, "baseline": baseline, "revision": version, "clear": clear,
        "step": step, "error": error, "blood_types": BLOOD_TYPES, "statuses": STATES,
        "xray": xray, "choices": XRAY_CHOICES, "question": XRAY_QUESTION, "unanswered": UNANSWERED,
        "sent": form is None and request.query_params.get("sent") == "1" and latest and latest.status == "pending",
    }, status_code=409 if stale else 422 if error else 200, headers={"Cache-Control": "no-store"})


@router.get(STAFF)
def medical_staff(request: Request, child_id: int, session: Session = Depends(get_session),
                  current_user=Depends(get_current_staff_user)):
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(404, "園児が見つかりません。")
    records = session.exec(select(ParentMedicalResponse).where(ParentMedicalResponse.child_id == child_id)
                           .order_by(ParentMedicalResponse.id.desc())).all()
    return templates.TemplateResponse(request, "health/parent_medical.html", {
        "child": child, "current_user": current_user, "records": records, "labels": FIELDS,
        "current": current_values(session, child_id), "consent": latest_consent(session, child_id),
        "choices": XRAY_CHOICES, "statuses": STATES, "unanswered": UNANSWERED,
        "parents": session.exec(linked_parents(child_id).order_by(ParentAccount.id)).all(),
    }, headers={"Cache-Control": "no-store"})


@router.post(STAFF + "/request")
def request_medical(child_id: int, parent_id: int = Form(...), session: Session = Depends(get_session),
                    current_user=Depends(get_current_staff_user)):
    require_can_edit(current_user)
    lock_child(session, child_id)
    parent = session.exec(linked_parents(child_id).where(ParentAccount.id == parent_id)).first()
    if not parent:
        raise HTTPException(404, "この園児の保護者を選んでください。")
    previous = latest_answer(session, child_id, parent_id)
    if not previous or previous.status not in ("pending", "requested", "returned"):
        session.add(ParentMedicalResponse(child_id=child_id, parent_account_id=parent_id,
                                         parent_name=parent.display_name, requested_by=current_user.name))
        session.commit()
    return RedirectResponse(STAFF.format(child_id=child_id), status_code=303)


@router.post(STAFF + "/{response_id}")
def review_medical(child_id: int, response_id: int, action: str = Form(...), note: str = Form(""),
                   session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    lock_child(session, child_id)
    answer = session.get(ParentMedicalResponse, response_id)
    if not answer or answer.child_id != child_id:
        raise HTTPException(404, "回答が見つかりません。")
    require_current("pending", answer.status)
    if action == "approve":
        if not session.exec(linked_parents(child_id).where(ParentAccount.id == answer.parent_account_id)).first():
            raise HTTPException(409, "この保護者と園児の紐付けを確認してください。")
        current = current_values(session, child_id)
        edits = {key: value for key, value in answer.answers.items() if value != answer.before[key]}
        if any(current[key] not in (answer.before[key], value) for key, value in edits.items()):
            raise HTTPException(409, "回答後に登録内容が変わりました。保護者に書き直しをお願いしてください。")
        if edits:
            profile = get_or_create_child_health_profile(session, session.get(Child, child_id), actor_name=current_user.name)
            for key, value in edits.items():
                setattr(profile, key, value or None)
            profile.updated_at, profile.updated_by = utc_now(), current_user.name
            session.add(profile)
        answer.status = "approved"
    elif action == "return" and 0 < len(note.strip()) <= 500:
        answer.status, answer.review_note = "returned", note.strip()
    else:
        raise HTTPException(400, "書き直してほしい内容を500文字以内で入力してください。")
    answer.reviewed_by, answer.reviewed_at = current_user.name, utc_now()
    session.add(answer)
    session.commit()
    return RedirectResponse(STAFF.format(child_id=child_id), status_code=303)
