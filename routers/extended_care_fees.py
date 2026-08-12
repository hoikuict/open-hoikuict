from __future__ import annotations

from datetime import date
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlmodel import Session, select

from auth import get_current_staff_user, require_admin, require_can_edit
from database import get_session
from extended_care_billing_transfer_service import (
    ExtendedCareBillingTransferError,
    build_extended_care_transfer_preview,
    get_extended_care_billing_setting,
    remove_manual_extended_care_billing_conflict,
    revert_extended_care_transfer,
    transfer_extended_care_charges,
    validate_extended_care_billing_setting,
)
from extended_care_fee_service import (
    adjust_charge,
    build_monthly_csv,
    build_monthly_overview,
    confirm_charge,
    exclude_charge,
    parse_month,
    recalculate_period,
    validate_fee_rule,
)
from models import (
    Classroom,
    ExtendedCareBillingSetting,
    ExtendedCareCharge,
    ExtendedCareFeeRule,
)
from time_utils import local_today, utc_now


router = APIRouter(prefix="/extended-care-fees", tags=["extended-care-fees"])
from template_utils import create_templates

templates = create_templates()


@router.get("/", response_class=HTMLResponse)
def extended_care_fees_index(
    request: Request,
    month: Optional[str] = Query(default=None),
    classroom_id: Optional[str] = Query(default=None),
    child_name: Optional[str] = Query(default=None),
    unconfirmed_only: Optional[str] = Query(default=None),
    recalculated: Optional[str] = Query(default=None),
    message: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    open_child_id: Optional[int] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    filters = _build_filters(month, classroom_id, child_name, unconfirmed_only)
    overview = build_monthly_overview(session, **filters)
    billing_setting = get_extended_care_billing_setting(session)
    billing_preview = build_extended_care_transfer_preview(session, filters["month"])
    review_filters = {**filters, "unconfirmed_only": True}
    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()

    return templates.TemplateResponse(
        request,
        "extended_care_fees/list.html",
        {
            "request": request,
            "current_user": current_user,
            "overview": overview,
            "classroom_options": classrooms,
            "filters": filters,
            "current_query_string": urlencode(_query_params(filters)),
            "review_query_string": urlencode(_query_params(review_filters)),
            "current_url": _current_url(request),
            "recalculated": recalculated,
            "message": message,
            "error": error,
            "billing_setting": billing_setting,
            "billing_preview": billing_preview,
            "open_child_id": open_child_id,
        },
    )


@router.get("/export.csv")
def export_extended_care_fees_csv(
    month: Optional[str] = Query(default=None),
    classroom_id: Optional[str] = Query(default=None),
    child_name: Optional[str] = Query(default=None),
    unconfirmed_only: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    filters = _build_filters(month, classroom_id, child_name, unconfirmed_only)
    overview = build_monthly_overview(session, **filters)
    filename = f"extended-care-fees-{overview.month}.csv"
    return Response(
        content=build_monthly_csv(overview),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/recalculate")
def recalculate_extended_care_fees(
    month: str = Form(...),
    classroom_id: str = Form(default=""),
    child_name: str = Form(default=""),
    unconfirmed_only: Optional[str] = Form(default=None),
    include_locked: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    normalized_month, start_date, end_date = parse_month(month)
    updated_count = recalculate_period(
        session,
        start_date,
        end_date,
        include_locked=_as_bool(include_locked),
    )
    session.commit()
    params = {
        "month": normalized_month,
        "recalculated": str(updated_count),
    }
    if classroom_id:
        params["classroom_id"] = classroom_id
    if child_name:
        params["child_name"] = child_name
    if _as_bool(unconfirmed_only):
        params["unconfirmed_only"] = "1"
    return RedirectResponse(url=f"/extended-care-fees/?{urlencode(params)}", status_code=303)


@router.get("/billing-transfer", response_class=HTMLResponse)
def extended_care_billing_transfer_preview(
    request: Request,
    month: Optional[str] = Query(default=None),
    message: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    normalized_month, _, _ = parse_month(month)
    preview = build_extended_care_transfer_preview(session, normalized_month)
    return templates.TemplateResponse(
        request,
        "extended_care_fees/billing_transfer.html",
        {
            "request": request,
            "current_user": current_user,
            "preview": preview,
            "message": message,
            "error": error,
        },
    )


@router.post("/billing-transfer")
def execute_extended_care_billing_transfer(
    month: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    normalized_month, _, _ = parse_month(month)
    try:
        result = transfer_extended_care_charges(
            session,
            normalized_month,
            executed_by_user_id=current_user.user_id,
            executed_by_name=current_user.name,
        )
        session.commit()
    except ExtendedCareBillingTransferError as exc:
        session.rollback()
        params = {"month": normalized_month, "error": str(exc)}
        return RedirectResponse(
            url=f"/extended-care-fees/billing-transfer?{urlencode(params)}",
            status_code=303,
        )
    if result.action == "none":
        message = "転送済みの内容と一致しているため、変更はありませんでした。"
    elif result.action == "retransfer":
        message = f"{result.affected_child_count}名分の延長保育料金を再転送しました。"
    else:
        message = f"{result.affected_child_count}名分の延長保育料金を請求へ転送しました。"
    params = {"month": normalized_month, "message": message}
    return RedirectResponse(
        url=f"/extended-care-fees/billing-transfer?{urlencode(params)}",
        status_code=303,
    )


@router.post("/billing-transfer/revert")
def revert_extended_care_billing_transfer_route(
    month: str = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    normalized_month, _, _ = parse_month(month)
    try:
        result = revert_extended_care_transfer(
            session,
            normalized_month,
            executed_by_user_id=current_user.user_id,
            executed_by_name=current_user.name,
        )
        session.commit()
    except ExtendedCareBillingTransferError as exc:
        session.rollback()
        params = {"month": normalized_month, "error": str(exc)}
        return RedirectResponse(
            url=f"/extended-care-fees/billing-transfer?{urlencode(params)}",
            status_code=303,
        )
    params = {
        "month": normalized_month,
        "message": f"{result.affected_child_count}名分の請求転送を解除しました。",
    }
    return RedirectResponse(
        url=f"/extended-care-fees/billing-transfer?{urlencode(params)}",
        status_code=303,
    )


@router.post("/billing-transfer/manual-conflict")
def remove_extended_care_manual_conflict_route(
    month: str = Form(...),
    child_id: int = Form(...),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    normalized_month, _, _ = parse_month(month)
    try:
        removed_amount = remove_manual_extended_care_billing_conflict(
            session,
            normalized_month,
            child_id=child_id,
        )
        session.commit()
    except ExtendedCareBillingTransferError as exc:
        session.rollback()
        params = {"month": normalized_month, "error": str(exc)}
        return RedirectResponse(
            url=f"/extended-care-fees/billing-transfer?{urlencode(params)}",
            status_code=303,
        )
    params = {
        "month": normalized_month,
        "message": f"競合していた手入力の延長保育料 {removed_amount:,}円を削除しました。",
    }
    return RedirectResponse(
        url=f"/extended-care-fees/billing-transfer?{urlencode(params)}",
        status_code=303,
    )


@router.post("/{charge_id}/confirm")
def confirm_extended_care_charge(
    charge_id: int,
    return_url: str = Form(default="/extended-care-fees/"),
    open_child_id: Optional[int] = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    charge = _load_charge(session, charge_id)
    try:
        confirm_charge(charge, current_user.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(charge)
    session.commit()
    return RedirectResponse(
        url=_return_url_with_open_child(return_url, open_child_id),
        status_code=303,
    )


@router.post("/{charge_id}/adjust")
def adjust_extended_care_charge(
    charge_id: int,
    adjustment_amount: str = Form(default="0"),
    adjustment_reason: str = Form(default=""),
    return_url: str = Form(default="/extended-care-fees/"),
    open_child_id: Optional[int] = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    charge = _load_charge(session, charge_id)
    try:
        amount = int(adjustment_amount or "0")
        adjust_charge(charge, amount, adjustment_reason, current_user.name)
    except ValueError as exc:
        status_code = 409 if charge.billing_charge_line_id is not None else 400
        raise HTTPException(status_code=status_code, detail=str(exc)) from exc
    session.add(charge)
    session.commit()
    return RedirectResponse(
        url=_return_url_with_open_child(return_url, open_child_id),
        status_code=303,
    )


@router.post("/{charge_id}/exclude")
def exclude_extended_care_charge(
    charge_id: int,
    exclusion_reason: str = Form(default=""),
    return_url: str = Form(default="/extended-care-fees/"),
    open_child_id: Optional[int] = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    charge = _load_charge(session, charge_id)
    try:
        exclude_charge(charge, exclusion_reason, current_user.name)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    session.add(charge)
    session.commit()
    return RedirectResponse(
        url=_return_url_with_open_child(return_url, open_child_id),
        status_code=303,
    )


@router.get("/settings", response_class=HTMLResponse)
def extended_care_fee_settings(
    request: Request,
    message: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    rules = _list_rules(session)
    return templates.TemplateResponse(
        request,
        "extended_care_fees/settings.html",
        {
            "request": request,
            "current_user": current_user,
            "rules": rules,
            "errors": [],
            "form_values": _default_rule_form_values(),
            "billing_setting": get_extended_care_billing_setting(session),
            "billing_errors": [],
            "message": message,
        },
    )


@router.post("/settings", response_class=HTMLResponse)
def create_extended_care_fee_rule(
    request: Request,
    name: str = Form(...),
    effective_from: str = Form(...),
    effective_to: str = Form(default=""),
    start_time: str = Form(...),
    grace_minutes: str = Form(...),
    rounding_minutes: str = Form(...),
    unit_price: str = Form(...),
    daily_cap_amount: str = Form(default=""),
    is_active: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    values, errors = _parse_rule_form(
        name=name,
        effective_from=effective_from,
        effective_to=effective_to,
        start_time=start_time,
        grace_minutes=grace_minutes,
        rounding_minutes=rounding_minutes,
        unit_price=unit_price,
        daily_cap_amount=daily_cap_amount,
        is_active=is_active,
    )
    if not errors:
        errors.extend(validate_fee_rule(session, **values))
    if errors:
        return _settings_response(request, session, current_user, errors, _form_values_from_values(values))

    session.add(ExtendedCareFeeRule(**values))
    session.commit()
    return RedirectResponse(url="/extended-care-fees/settings", status_code=303)


@router.post("/settings/billing", response_class=HTMLResponse)
def update_extended_care_billing_setting(
    request: Request,
    is_enabled: Optional[str] = Form(default=None),
    fee_item_code: str = Form(default="monthly_childcare"),
    description_template: str = Form(default="延長保育料（{year}年{month}月分）"),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_admin(current_user)
    cleaned_code = fee_item_code.strip()
    cleaned_template = description_template.strip()
    errors = validate_extended_care_billing_setting(
        fee_item_code=cleaned_code,
        description_template=cleaned_template,
    )
    setting = get_extended_care_billing_setting(session)
    setting.is_enabled = _as_bool(is_enabled)
    setting.fee_item_code = cleaned_code
    setting.description_template = cleaned_template
    setting.transfer_mode = "manual_monthly"
    setting.target_month_rule = "same_month"
    if errors:
        return templates.TemplateResponse(
            request,
            "extended_care_fees/settings.html",
            {
                "request": request,
                "current_user": current_user,
                "rules": _list_rules(session),
                "errors": [],
                "form_values": _default_rule_form_values(),
                "billing_setting": setting,
                "billing_errors": errors,
                "message": None,
            },
            status_code=400,
        )
    setting.updated_at = utc_now()
    setting.updated_by_user_id = current_user.user_id
    setting.updated_by_name = current_user.name
    session.add(setting)
    session.commit()
    return RedirectResponse(
        url=f"/extended-care-fees/settings?{urlencode({'message': '請求連携設定を更新しました。'})}",
        status_code=303,
    )


@router.post("/settings/{rule_id}", response_class=HTMLResponse)
def update_extended_care_fee_rule(
    request: Request,
    rule_id: int,
    name: str = Form(...),
    effective_from: str = Form(...),
    effective_to: str = Form(default=""),
    start_time: str = Form(...),
    grace_minutes: str = Form(...),
    rounding_minutes: str = Form(...),
    unit_price: str = Form(...),
    daily_cap_amount: str = Form(default=""),
    is_active: Optional[str] = Form(default=None),
    session: Session = Depends(get_session),
    current_user=Depends(get_current_staff_user),
):
    require_can_edit(current_user)
    rule = session.get(ExtendedCareFeeRule, rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="料金ルールが見つかりません")

    values, errors = _parse_rule_form(
        name=name,
        effective_from=effective_from,
        effective_to=effective_to,
        start_time=start_time,
        grace_minutes=grace_minutes,
        rounding_minutes=rounding_minutes,
        unit_price=unit_price,
        daily_cap_amount=daily_cap_amount,
        is_active=is_active,
    )
    if not errors:
        errors.extend(validate_fee_rule(session, rule_id=rule_id, **values))
    if errors:
        return _settings_response(request, session, current_user, errors, _form_values_from_values(values))

    for key, value in values.items():
        setattr(rule, key, value)
    rule.updated_at = utc_now()
    session.add(rule)
    session.commit()
    return RedirectResponse(url="/extended-care-fees/settings", status_code=303)


def _build_filters(
    month: Optional[str],
    classroom_id: Optional[str],
    child_name: Optional[str],
    unconfirmed_only: Optional[str],
) -> dict:
    normalized_month, _, _ = parse_month(month)
    return {
        "month": normalized_month,
        "classroom_id": _parse_optional_int(classroom_id),
        "child_name": (child_name or "").strip(),
        "unconfirmed_only": _as_bool(unconfirmed_only),
    }


def _query_params(filters: dict) -> dict[str, str]:
    params = {"month": filters["month"]}
    if filters["classroom_id"] is not None:
        params["classroom_id"] = str(filters["classroom_id"])
    if filters["child_name"]:
        params["child_name"] = filters["child_name"]
    if filters["unconfirmed_only"]:
        params["unconfirmed_only"] = "1"
    return params


def _parse_rule_form(**raw_values) -> tuple[dict, list[str]]:
    errors: list[str] = []
    values: dict = {
        "name": str(raw_values["name"]).strip(),
        "start_time": str(raw_values["start_time"]).strip(),
        "is_active": _as_bool(raw_values.get("is_active")),
    }

    parsed_from = _parse_date(raw_values["effective_from"])
    if parsed_from is None:
        errors.append("適用開始日を入力してください。")
        parsed_from = local_today()
    values["effective_from"] = parsed_from

    parsed_to = _parse_date(raw_values.get("effective_to"))
    values["effective_to"] = parsed_to

    for field_name, label in [
        ("grace_minutes", "猶予時間"),
        ("rounding_minutes", "丸め単位"),
        ("unit_price", "単価"),
    ]:
        parsed = _parse_int(raw_values[field_name])
        if parsed is None:
            errors.append(f"{label}は整数で入力してください。")
            parsed = 0
        values[field_name] = parsed

    cap_raw = str(raw_values.get("daily_cap_amount") or "").strip()
    values["daily_cap_amount"] = None if not cap_raw else _parse_int(cap_raw)
    if cap_raw and values["daily_cap_amount"] is None:
        errors.append("日別上限額は整数で入力してください。")

    return values, errors


def _settings_response(
    request: Request,
    session: Session,
    current_user,
    errors: list[str],
    form_values: dict,
):
    return templates.TemplateResponse(
        request,
        "extended_care_fees/settings.html",
        {
            "request": request,
            "current_user": current_user,
            "rules": _list_rules(session),
            "errors": errors,
            "form_values": form_values,
            "billing_setting": get_extended_care_billing_setting(session),
            "billing_errors": [],
            "message": None,
        },
        status_code=400,
    )


def _list_rules(session: Session) -> list[ExtendedCareFeeRule]:
    return session.exec(
        select(ExtendedCareFeeRule).order_by(
            ExtendedCareFeeRule.effective_from.desc(),
            ExtendedCareFeeRule.id.desc(),
        )
    ).all()


def _default_rule_form_values() -> dict:
    return {
        "name": "標準延長保育料",
        "effective_from": local_today().replace(month=1, day=1).isoformat(),
        "effective_to": "",
        "start_time": "18:00",
        "grace_minutes": "5",
        "rounding_minutes": "15",
        "unit_price": "100",
        "daily_cap_amount": "",
        "is_active": True,
    }


def _form_values_from_values(values: dict) -> dict:
    return {
        "name": values.get("name", ""),
        "effective_from": values.get("effective_from", local_today()).isoformat(),
        "effective_to": values["effective_to"].isoformat() if values.get("effective_to") else "",
        "start_time": values.get("start_time", "18:00"),
        "grace_minutes": str(values.get("grace_minutes", "")),
        "rounding_minutes": str(values.get("rounding_minutes", "")),
        "unit_price": str(values.get("unit_price", "")),
        "daily_cap_amount": "" if values.get("daily_cap_amount") is None else str(values.get("daily_cap_amount")),
        "is_active": bool(values.get("is_active")),
    }


def _load_charge(session: Session, charge_id: int) -> ExtendedCareCharge:
    charge = session.get(ExtendedCareCharge, charge_id)
    if not charge:
        raise HTTPException(status_code=404, detail="延長保育料金が見つかりません")
    return charge


def _current_url(request: Request) -> str:
    query = str(request.query_params)
    return f"{request.url.path}?{query}" if query else request.url.path


def _safe_return_url(return_url: str) -> str:
    if return_url.startswith("/") and not return_url.startswith("//"):
        return return_url
    return "/extended-care-fees/"


def _return_url_with_open_child(return_url: str, child_id: Optional[int]) -> str:
    safe_url = _safe_return_url(return_url)
    if child_id is None:
        return safe_url
    parts = urlsplit(safe_url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    query["open_child_id"] = str(child_id)
    return urlunsplit(
        (
            parts.scheme,
            parts.netloc,
            parts.path,
            urlencode(query),
            f"extended-care-child-{child_id}",
        )
    )


def _parse_date(raw: Optional[str]) -> Optional[date]:
    if not raw:
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def _parse_int(raw: Optional[str]) -> Optional[int]:
    if raw is None:
        return None
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


def _parse_optional_int(raw: Optional[str]) -> Optional[int]:
    if not raw:
        return None
    return _parse_int(raw)


def _as_bool(raw: Optional[str]) -> bool:
    return str(raw or "").lower() in {"1", "true", "on", "yes"}
