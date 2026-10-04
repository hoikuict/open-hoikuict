from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import selectinload
from sqlmodel import Session, select

from auth import get_current_staff_user, require_child_record_manager
from child_care_certification_service import (
    create_certification,
    deactivate_certification,
    validate_certification,
    list_certifications, current_certification,
)
from database import get_session
from family_care_service import require_individual_mode
from models import (
    CareNeedReason,
    CareTimeCategory,
    Child,
    ChildCareCertification,
)


router = APIRouter(prefix="/children", tags=["care-certifications"])


@router.get("/{child_id}/care-certifications")
def child_care_editor(child_id: int, request: Request, care_message: str = "", care_error: str = "",
                      session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_child_record_manager(current_user)
    child = session.get(Child, child_id)
    if child is None:
        raise HTTPException(404, "園児が見つかりません")
    if child.family_id:
        return _redirect(session, child_id, care_message=care_message, care_error=care_error)
    from template_utils import create_templates
    records = list_certifications(session, child_id)
    return create_templates().TemplateResponse(request, "children/care_certifications.html", dict(
        child=child, current_user=current_user, care_message=care_message, care_error=care_error,
        care_certifications=records, active_care_certification=current_certification(session, child_id),
        care_time_categories=list(CareTimeCategory), care_need_reasons=list(CareNeedReason),
        guardian_profiles=[dict(last_name=f"保護者{i}", first_name="", relationship="") for i in (1, 2)]),
        headers={"Cache-Control": "private, no-store"})


@router.post("/{child_id}/care-certifications")
def create_child_care_certification(
    child_id: int,
    care_time_category: str = Form(...),
    effective_from: str = Form(...),
    effective_to: str = Form(default=""),
    internal_note: str = Form(default=""),
    guardian_reason_1: str = Form(default=""),
    guardian_other_1: str = Form(default=""),
    guardian_reason_2: str = Form(default=""),
    guardian_other_2: str = Form(default=""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    require_individual_mode(session, child_id)
    child = session.exec(
        select(Child).options(selectinload(Child.family)).where(Child.id == child_id)
    ).first()
    if child is None:
        raise HTTPException(status_code=404, detail="園児が見つかりません")

    errors: list[str] = []
    try:
        category = CareTimeCategory(care_time_category)
    except ValueError:
        category = CareTimeCategory.standard
        errors.append("保育必要量を選択してください。")
    start = _parse_required_date(effective_from, "適用開始日", errors)
    end = _parse_optional_date(effective_to, "適用終了日", errors)
    guardian_reasons = _guardian_reason_rows(
        child,
        [(guardian_reason_1, guardian_other_1), (guardian_reason_2, guardian_other_2)],
        errors,
    )
    if start is not None:
        errors.extend(
            validate_certification(
                session,
                child_id=child_id,
                care_time_category=category,
                effective_from=start,
                effective_to=end,
                guardian_reasons=guardian_reasons,
            )
        )
    if errors:
        return _redirect(session, child_id, care_error=" ".join(dict.fromkeys(errors)))

    create_certification(
        session,
        child=child,
        care_time_category=category,
        effective_from=start,
        effective_to=end,
        internal_note=internal_note,
        guardian_reasons=guardian_reasons,
        actor_user_id=current_user.user_id,
        actor_name=current_user.name,
    )
    session.commit()
    return _redirect(session, child_id, care_message="保育認定を登録しました。")


@router.post("/{child_id}/care-certifications/{certification_id}/deactivate")
def deactivate_child_care_certification(
    child_id: int,
    certification_id: int,
    deactivation_reason: str = Form(default=""),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_child_record_manager(current_user)
    require_individual_mode(session, child_id)
    certification = session.exec(
        select(ChildCareCertification)
        .options(selectinload(ChildCareCertification.reasons))
        .where(
            ChildCareCertification.id == certification_id,
            ChildCareCertification.child_id == child_id,
        )
    ).first()
    if certification is None:
        raise HTTPException(status_code=404, detail="保育認定が見つかりません")
    try:
        deactivate_certification(
            session,
            certification,
            reason=deactivation_reason,
            actor_user_id=current_user.user_id,
            actor_name=current_user.name,
        )
    except ValueError as exc:
        return _redirect(session, child_id, care_error=str(exc))
    session.commit()
    return _redirect(session, child_id, care_message="保育認定を無効化しました。")


def _guardian_reason_rows(
    child: Child,
    inputs: list[tuple[str, str]],
    errors: list[str],
) -> list[dict[str, object]]:
    profiles = child.family.guardian_profiles() if child.family else []
    rows: list[dict[str, object]] = []
    for index, (reason_raw, other_detail) in enumerate(inputs, start=1):
        if not reason_raw.strip():
            continue
        try:
            reason = CareNeedReason(reason_raw)
        except ValueError:
            errors.append(f"保護者{index}の事由が不正です。")
            continue
        profile = profiles[index - 1] if index <= len(profiles) else {}
        name = f"{profile.get('last_name', '')} {profile.get('first_name', '')}".strip()
        rows.append(
            {
                "guardian_order": index,
                "guardian_name_snapshot": name or f"保護者{index}",
                "relationship_snapshot": str(profile.get("relationship", "")),
                "reason": reason,
                "other_reason_detail": other_detail,
            }
        )
    return rows


def _parse_required_date(raw: str, label: str, errors: list[str]):
    try:
        return date.fromisoformat(raw.strip())
    except (AttributeError, ValueError):
        errors.append(f"{label}を正しく入力してください。")
        return None


def _parse_optional_date(raw: str, label: str, errors: list[str]):
    if not raw.strip():
        return None
    return _parse_required_date(raw, label, errors)


def _redirect(session: Session, child_id: int, **params: str) -> RedirectResponse:
    child = session.get(Child, child_id)
    destination = f"/families/{child.family_id}/care-certifications" if child and child.family_id else f"/children/{child_id}/care-certifications"
    return RedirectResponse(
        url=f"{destination}?{urlencode(params)}#child-{child_id}",
        status_code=303,
    )
