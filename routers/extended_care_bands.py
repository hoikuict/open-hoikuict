from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlmodel import Session

from auth import get_current_staff_user, require_can_edit
from database import get_session
from extended_care_bands import evaluate_plan, normalize_plan, revision, rule_plan, rule_values
from extended_care_fee_service import validate_fee_rule
from models import CareTimeCategory, ExtendedCareFeeRule
from time_utils import local_today, utc_now

router = APIRouter(prefix="/settings/bands")


def settings_bootstrap(rules, user):
    return dict(today=local_today().isoformat(), canEdit=user.can_edit, isAdmin=user.is_admin,
                rules={category.value: [rule_plan(r) for r in rules if r.care_time_category == category]
                       for category in CareTimeCategory})


async def read_payload(request):
    body = await request.body()
    if len(body) > 65536:
        raise HTTPException(413, "入力が大きすぎます。")
    try:
        payload = json.loads(body)
        if not isinstance(payload, dict):
            raise ValueError
        return payload
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(400, "入力の形式が正しくありません。") from None


@router.post("/preview")
async def preview(request: Request, current_user=Depends(get_current_staff_user)):
    payload = await read_payload(request)
    try:
        result = evaluate_plan(payload.get("plan"), payload.get("date", ""), payload.get("arrival", ""), payload.get("departure", ""))
        return JSONResponse(result, headers={"Cache-Control": "private, no-store"})
    except (ValueError, TypeError) as exc:
        return JSONResponse(dict(errors=[str(exc)], warnings=[], lines=[], total=None, subtotal=0), headers={"Cache-Control": "private, no-store"})


@router.post("/{category}")
async def save(category: CareTimeCategory, request: Request, session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    require_can_edit(current_user)
    payload = await read_payload(request)
    try:
        plan = normalize_plan(payload)
        values = rule_values(plan, category)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Serialize overlap validation and write on the production SQLite database.
    if session.get_bind().dialect.name == "sqlite":
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
    rule_id = payload.get("id")
    if rule_id is not None and (type(rule_id) is not int or rule_id < 1):
        raise HTTPException(400, "ルールIDが不正です。")
    rule = session.get(ExtendedCareFeeRule, rule_id) if rule_id else None
    if rule_id and (rule is None or rule.care_time_category != category):
        raise HTTPException(404, "この区分の料金ルールが見つかりません。")
    if rule is not None and payload.get("revision") != revision(rule):
        raise HTTPException(409, "別の画面で設定が更新されています。入力を控え、画面を再読み込みして最新の設定を確認してください。")
    errors = validate_fee_rule(session, rule_id=rule_id, **values)
    if errors:
        raise HTTPException(400, " / ".join(errors))
    if rule is None:
        rule = ExtendedCareFeeRule(**values)
    else:
        for key, value in values.items():
            setattr(rule, key, value)
    rule.updated_at = utc_now()
    session.add(rule)
    session.commit()
    session.refresh(rule)
    return JSONResponse(rule_plan(rule), headers={"Cache-Control": "private, no-store"})
