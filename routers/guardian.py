from datetime import date, datetime
from typing import Optional
from urllib.parse import urlencode
from pathlib import Path

from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from sqlmodel import Session, select
from sqlalchemy import exists, or_, update
from sqlalchemy.exc import IntegrityError

from attendance_checks_service import sync_attendance_alarm
from database import get_session
from auth import get_current_staff_user
from security_config import kiosk_access_mode
from extended_care_fee_service import recalculate_attendance_charge
from models import AttendanceRecord, AttendanceVerification, AttendanceVerificationStatus, Child, ChildStatus, Classroom
from time_utils import local_naive_now, local_today, utc_now
from pickup_plan_service import pickup_revision, save_pickup_plan
from guardian_terminal import GuardianRoute, TERMINAL_START, is_terminal, remember_terminal, render_guardian
from guardian_arrival import issue_arrival_draft, read_arrival_draft
from kiosk_security import (
    KIOSK_DEVICE_COOKIE,
    issue_kiosk_device_cookie,
    kiosk_activation_token_is_valid,
    kiosk_device_cookie_is_valid,
    require_kiosk_activation_mode,
    require_kiosk_access,
)

router = APIRouter(prefix="/guardian", tags=["guardian"], route_class=GuardianRoute)
from template_utils import create_templates

templates = create_templates()

PICKUP_HOUR_OPTIONS = [f"{hour:02d}" for hour in range(7, 23)]
PICKUP_MINUTE_OPTIONS = ["00", "15", "30", "45"]
PICKUP_PERSON_OPTIONS = ["母", "父", "祖父", "祖母", "ファミリーサポート", "その他"]


@router.get("/setup", response_class=HTMLResponse)
def guardian_setup(request: Request, current_user=Depends(get_current_staff_user)):
    return templates.TemplateResponse(request, "guardian/setup.html", {
        "request": request, "current_user": current_user, "mode": kiosk_access_mode(),
    })


def _parse_target_date(raw: Optional[str], request: Request | None = None) -> date:
    if request is not None and is_terminal(request):
        today = local_today()
        if request.method == "POST" and raw != today.isoformat():
            raise HTTPException(status_code=409, detail="日付が変わりました。最初の画面からやり直してください。")
        return today
    if not raw:
        return local_today()
    try:
        return date.fromisoformat(raw)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="日付は YYYY-MM-DD 形式で指定してください") from exc


def _redirect_url(day: date, class_id: Optional[int], child_id: Optional[int], notice: Optional[str] = None) -> str:
    params: dict[str, str] = {"date": day.isoformat()}
    if class_id:
        params["class_id"] = str(class_id)
    if child_id:
        params["child_id"] = str(child_id)
    if notice:
        params["notice"] = notice
    return f"/guardian?{urlencode(params)}"


def _load_attendance_record(session: Session, child_id: int, day: date) -> Optional[AttendanceRecord]:
    return session.exec(
        select(AttendanceRecord).where(
            AttendanceRecord.child_id == child_id,
            AttendanceRecord.attendance_date == day,
        )
    ).first()


def _normalize_pickup_time(raw: str) -> Optional[str]:
    cleaned = (raw or "").strip()
    if not cleaned:
        return None
    try:
        parsed = datetime.strptime(cleaned, "%H:%M")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="お迎え予定時刻は HH:MM 形式で入力してください") from exc
    return parsed.strftime("%H:%M")


def _pickup_time_parts(value: str) -> tuple[str, str]:
    if len(value) == 5 and value[2] == ":":
        return value[:2], value[3:]
    return "", ""


def _is_truthy(raw: Optional[str]) -> bool:
    return (raw or "").strip().lower() in {"1", "true", "yes", "on"}


def _validate_pickup_inputs(raw_time: str, raw_person: str) -> tuple[str, str]:
    planned_pickup_time = _normalize_pickup_time(raw_time)
    pickup_person = (raw_person or "").strip()

    if not planned_pickup_time:
        raise HTTPException(status_code=400, detail="お迎え予定時刻を入力してください")
    if not pickup_person:
        raise HTTPException(status_code=400, detail="お迎え予定者を入力してください")

    return planned_pickup_time, pickup_person


def _load_valid_child(session: Session, child_id: int, class_id: Optional[int]) -> Child:
    child = session.get(Child, child_id)
    if not child:
        raise HTTPException(status_code=404, detail="園児が見つかりません")
    if child.status != ChildStatus.enrolled:
        raise HTTPException(status_code=400, detail="在園児のみ入力できます")
    if class_id and child.classroom_id != class_id:
        raise HTTPException(status_code=400, detail="クラス情報が不正です")
    return child


def _load_record_for_checkout(session: Session, child_id: int, day: date) -> AttendanceRecord | None:
    record = _load_attendance_record(session, child_id, day)
    if not (record and record.check_in_at) and not _visually_present(session, child_id, day):
        raise HTTPException(status_code=400, detail="登園打刻または職員の出席確認が必要です")
    if record and record.check_out_at is not None:
        raise HTTPException(status_code=400, detail="すでに降園済みです")
    return record


def _visually_present(session: Session, child_id: int, day: date) -> bool:
    return session.exec(select(AttendanceVerification.id).where(
        AttendanceVerification.child_id == child_id, AttendanceVerification.target_date == day,
        AttendanceVerification.status == AttendanceVerificationStatus.present,
    )).first() is not None


def _pickup_step(request, child, day, record, *, arrival_token="", values=None, confirm=False):
    arrival_at = None
    revision = pickup_revision(record)
    if arrival_token:
        arrival_at, expected_revision = read_arrival_draft(arrival_token, request, child, day)
        if revision != expected_revision or (record and (record.check_in_at or record.check_out_at)):
            raise HTTPException(409, "記録が変更されています。最初の画面からやり直してください。")
    values = values if values is not None else {
        "planned_pickup_time": record.planned_pickup_time or "" if record else "",
        "pickup_person": record.pickup_person or "" if record else "",
        "snack_required": ("1" if record.snack_required else "0") if record and record.pickup_snack_confirmed else "",
    }
    return render_guardian(request, "guardian/pickup_confirm.html" if confirm else "guardian/pickup_form.html", {
        "request": request, "selected_child": child,
        "selected_classroom": child.classroom, "target_date_value": day.isoformat(),
        "pickup_revision": revision, "arrival_token": arrival_token, "arrival_at": arrival_at,
        "pickup_values": values, "pickup_person_options": PICKUP_PERSON_OPTIONS,
        "planned_pickup_time": values["planned_pickup_time"], "pickup_person": values["pickup_person"],
        "snack_required": values["snack_required"] == "1",
    })


@router.get(
    "/",
    response_class=HTMLResponse,
    dependencies=[Depends(require_kiosk_access)],
)
def guardian_kiosk(
    request: Request,
    target_date: Optional[str] = Query(default=None, alias="date"),
    class_id: Optional[int] = Query(default=None),
    child_id: Optional[int] = Query(default=None),
    notice: Optional[str] = Query(default=None),
    draft_pickup_time: Optional[str] = Query(default=None),
    draft_pickup_person: Optional[str] = Query(default=None),
    draft_snack_required: Optional[str] = Query(default=None),
    session: Session = Depends(get_session),
):
    day = _parse_target_date(target_date, request)

    classrooms = session.exec(select(Classroom).order_by(Classroom.display_order, Classroom.id)).all()

    selected_child = session.get(Child, child_id) if child_id else None
    selected_classroom = session.get(Classroom, class_id) if class_id else None

    if selected_child and selected_child.status != ChildStatus.enrolled:
        raise HTTPException(status_code=400, detail="在園児のみ打刻できます")

    if not selected_classroom and selected_child and selected_child.classroom_id:
        selected_classroom = session.get(Classroom, selected_child.classroom_id)

    children: list[Child] = []
    if selected_classroom:
        children = session.exec(
            select(Child)
            .where(Child.status == ChildStatus.enrolled, Child.classroom_id == selected_classroom.id)
            .order_by(Child.last_name_kana, Child.first_name_kana)
        ).all()

    if selected_classroom and selected_child and selected_child.classroom_id != selected_classroom.id:
        raise HTTPException(status_code=400, detail="選択されたクラスに園児が存在しません")

    selected_record = None
    if selected_child:
        selected_record = _load_attendance_record(session, selected_child.id, day)

    raw_pickup_time = (draft_pickup_time or "").strip()
    if not raw_pickup_time and selected_record and selected_record.planned_pickup_time:
        raw_pickup_time = selected_record.planned_pickup_time
    current_pickup_time = _normalize_pickup_time(raw_pickup_time) or ""
    current_pickup_hour, current_pickup_minute = _pickup_time_parts(current_pickup_time)
    current_pickup_person = (draft_pickup_person or "").strip()
    if not current_pickup_person and selected_record and selected_record.pickup_person:
        current_pickup_person = selected_record.pickup_person
    if draft_snack_required is None:
        current_snack_required = bool(selected_record and selected_record.snack_required)
    else:
        current_snack_required = _is_truthy(draft_snack_required)

    notice_map = {
        "checked_in": "登園を受け付けました。",
        "checked_out": "降園を受け付けました。",
    }

    return render_guardian(
        request,
        "guardian/kiosk.html",
        {
            "request": request,
            "target_date": day,
            "target_date_value": day.isoformat(),
            "classrooms": classrooms,
            "selected_classroom": selected_classroom,
            "children": children,
            "selected_child": selected_child,
            "selected_record": selected_record,
            "can_depart": bool(selected_record and selected_record.check_in_at) or bool(selected_child and _visually_present(session, selected_child.id, day)),
            "pickup_revision": pickup_revision(selected_record),
            "notice_message": notice_map.get(notice, ""),
            "pickup_hour_options": PICKUP_HOUR_OPTIONS,
            "pickup_minute_options": PICKUP_MINUTE_OPTIONS,
            "pickup_person_options": PICKUP_PERSON_OPTIONS,
            "current_pickup_time": current_pickup_time,
            "current_pickup_hour": current_pickup_hour,
            "current_pickup_minute": current_pickup_minute,
            "current_pickup_person": current_pickup_person,
            "current_snack_required": current_snack_required,
        },
    )


@router.post("/child/{child_id}/check-in", dependencies=[Depends(require_kiosk_access)])
def guardian_check_in(
    child_id: int,
    request: Request,
    target_date: str = Form(..., alias="date"),
    class_id: Optional[int] = Form(default=None),
    session: Session = Depends(get_session),
):
    child = _load_valid_child(session, child_id, class_id)

    day = _parse_target_date(target_date, request)
    record = _load_attendance_record(session, child_id, day)

    if record and (record.check_in_at or record.check_out_at):
        raise HTTPException(409, "すでに打刻されています。最初の画面から確認してください。")
    if _visually_present(session, child_id, day):
        return RedirectResponse(_redirect_url(day, child.classroom_id, child_id), status_code=303)
    token = issue_arrival_draft(request, child, day, local_naive_now(), pickup_revision(record))
    complete = bool(record and record.planned_pickup_time and record.pickup_person and record.pickup_snack_confirmed)
    return _pickup_step(request, child, day, record, arrival_token=token, confirm=complete)


@router.post("/child/{child_id}/arrival/edit", dependencies=[Depends(require_kiosk_access)])
def guardian_arrival_edit(request: Request, child_id: int, target_date: str = Form(..., alias="date"),
                          class_id: Optional[int] = Form(None), arrival_token: str = Form(...),
                          planned_pickup_time: str = Form(""), pickup_person: str = Form(""),
                          snack_required: str = Form(""), session: Session = Depends(get_session)):
    child = _load_valid_child(session, child_id, class_id)
    day = _parse_target_date(target_date, request)
    record = _load_attendance_record(session, child_id, day)
    return _pickup_step(request, child, day, record, arrival_token=arrival_token, values={
        "planned_pickup_time": planned_pickup_time, "pickup_person": pickup_person, "snack_required": snack_required,
    })


@router.post("/child/{child_id}/pickup", dependencies=[Depends(require_kiosk_access)])
def guardian_pickup_confirm(
    request: Request,
    child_id: int,
    target_date: str = Form(..., alias="date"),
    class_id: Optional[int] = Form(default=None),
    revision: str = Form(""),
    planned_pickup_time: str = Form(""),
    pickup_person: str = Form(""),
    snack_required: Optional[str] = Form(default=None),
    arrival_token: str = Form(""),
    session: Session = Depends(get_session),
):
    child = _load_valid_child(session, child_id, class_id)
    day = _parse_target_date(target_date, request)
    record = _load_attendance_record(session, child_id, day)
    if record and record.check_out_at:
        raise HTTPException(400, "すでに降園済みです")
    if revision != pickup_revision(record):
        raise HTTPException(409, "予定が変更されています。画面を開き直してください")

    normalized_time, normalized_person = _validate_pickup_inputs(planned_pickup_time, pickup_person)
    if arrival_token and snack_required not in {"0", "1"}:
        raise HTTPException(400, "補食の必要・不要を選んでください。")
    return _pickup_step(request, child, day, record, arrival_token=arrival_token, confirm=True, values={
        "planned_pickup_time": normalized_time, "pickup_person": normalized_person,
        "snack_required": "1" if _is_truthy(snack_required) else "0",
    })


@router.post("/child/{child_id}/pickup/commit", dependencies=[Depends(require_kiosk_access)])
def guardian_pickup_commit(
    request: Request,
    child_id: int,
    target_date: str = Form(..., alias="date"),
    class_id: Optional[int] = Form(default=None),
    revision: str = Form(""),
    planned_pickup_time: str = Form(""),
    pickup_person: str = Form(""),
    snack_required: Optional[str] = Form(default=None),
    arrival_token: str = Form(""),
    session: Session = Depends(get_session),
):
    child = _load_valid_child(session, child_id, class_id)
    day = _parse_target_date(target_date, request)
    normalized_time, normalized_person = _validate_pickup_inputs(planned_pickup_time, pickup_person)
    arrival_at = None
    if arrival_token:
        arrival_at, expected_revision = read_arrival_draft(arrival_token, request, child, day)
        if revision != expected_revision:
            raise HTTPException(409, "登園の確認内容が変更されています。最初からやり直してください。")
        current = _load_attendance_record(session, child_id, day)
        if current and (current.check_in_at or current.check_out_at):
            raise HTTPException(409, "すでに打刻されています。最初の画面から確認してください。")
        if snack_required not in {"0", "1"}:
            raise HTTPException(400, "補食の必要・不要を選んでください。")
    record = save_pickup_plan(session, child_id=child_id, day=day, revision=revision,
        planned_pickup_time=normalized_time, pickup_person=normalized_person,
        snack_required=_is_truthy(snack_required), actor_name="保護者（KIOSK）", source="kiosk")
    if arrival_at is not None:
        changed = session.execute(update(AttendanceRecord).where(
            AttendanceRecord.id == record.id, AttendanceRecord.updated_at == record.updated_at,
            AttendanceRecord.check_in_at.is_(None), AttendanceRecord.check_out_at.is_(None),
        ).values(check_in_at=arrival_at, updated_at=utc_now()).execution_options(synchronize_session=False))
        if changed.rowcount != 1:
            session.rollback()
            raise HTTPException(409, "別の操作で更新されています。最初の画面から確認してください。")
        session.refresh(record)
        sync_attendance_alarm(session, child_id=child_id, target_date=day, record=record)
    session.commit()

    return render_guardian(
        request,
        "guardian/pickup_done.html",
        {
            "request": request,
            "message": "登園を受け付けました。" if arrival_at is not None else "お迎え予定を保存しました",
            "redirect_url": TERMINAL_START if is_terminal(request) else _redirect_url(day, None, None),
            "redirect_ms": 1000,
            "selected_child": child,
        },
    )


@router.post("/child/{child_id}/check-out", dependencies=[Depends(require_kiosk_access)])
def guardian_check_out_confirm(
    request: Request,
    child_id: int,
    target_date: str = Form(..., alias="date"),
    class_id: Optional[int] = Form(default=None),
    actual_pickup_person: str = Form(""),
    session: Session = Depends(get_session),
):
    return guardian_check_out_commit(child_id, request, target_date, class_id, actual_pickup_person, session)


@router.post("/child/{child_id}/check-out/commit", dependencies=[Depends(require_kiosk_access)])
def guardian_check_out_commit(
    child_id: int,
    request: Request,
    target_date: str = Form(..., alias="date"),
    class_id: Optional[int] = Form(default=None),
    actual_pickup_person: str = Form(""),
    session: Session = Depends(get_session),
):
    child = _load_valid_child(session, child_id, class_id)

    day = _parse_target_date(target_date, request)
    record = _load_record_for_checkout(session, child_id, day)
    if actual_pickup_person not in PICKUP_PERSON_OPTIONS:
        raise HTTPException(400, "お迎えに来た人を選んでください。")

    now = local_naive_now()
    audit_now = utc_now()
    if record is None:
        record = AttendanceRecord(child_id=child_id, attendance_date=day)
        session.add(record)
        try:
            session.flush()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "別の操作で更新されています。最初の画面から確認してください。") from exc
    visual_present = exists().where(
        AttendanceVerification.child_id == child_id, AttendanceVerification.target_date == day,
        AttendanceVerification.status == AttendanceVerificationStatus.present,
    )
    changed = session.execute(update(AttendanceRecord).where(
        AttendanceRecord.id == record.id, AttendanceRecord.updated_at == record.updated_at,
        AttendanceRecord.check_out_at.is_(None), or_(AttendanceRecord.check_in_at.is_not(None), visual_present),
    ).values(check_out_at=now, actual_pickup_person=actual_pickup_person, updated_at=audit_now)
      .execution_options(synchronize_session=False))
    if changed.rowcount != 1:
        session.rollback()
        raise HTTPException(409, "出席状況が変更されています。最初の画面から確認してください。")
    session.refresh(record)
    recalculate_attendance_charge(session, record)
    sync_attendance_alarm(session, child_id=child_id, target_date=day, record=record, now=audit_now)
    session.commit()

    if is_terminal(request):
        return render_guardian(request, "guardian/pickup_done.html", {
            "request": request, "message": "降園を受け付けました。",
            "redirect_url": TERMINAL_START, "redirect_ms": 1000, "selected_child": child,
        })
    return RedirectResponse(
        url=_redirect_url(day, class_id or child.classroom_id, child_id, notice="checked_out"),
        status_code=303,
    )


@router.get(
    "/activate",
    response_class=HTMLResponse,
    dependencies=[Depends(require_kiosk_activation_mode)],
)
def guardian_activate_page(request: Request):
    return render_guardian(
        request,
        "guardian/activate.html",
        {"request": request, "error": ""},
    )


@router.post("/activate", dependencies=[Depends(require_kiosk_activation_mode)])
def guardian_activate(request: Request, kiosk_token: str = Form("")):
    if not kiosk_activation_token_is_valid(kiosk_token):
        return render_guardian(
            request,
            "guardian/activate.html",
            {"request": request, "error": "トークンが一致しません。"},
            status_code=403,
        )
    response = RedirectResponse(url=TERMINAL_START if is_terminal(request) else "/guardian/", status_code=303)
    issue_kiosk_device_cookie(response)
    return response


@router.get("/terminal", response_class=HTMLResponse)
def guardian_terminal(request: Request, session: Session = Depends(get_session)):
    request.state.guardian_terminal = True
    if kiosk_access_mode() == "token" and not kiosk_device_cookie_is_valid(request.cookies.get(KIOSK_DEVICE_COOKIE)):
        response = render_guardian(request, "guardian/activate.html", {"request": request, "error": ""})
    else:
        require_kiosk_access(request)
        response = guardian_kiosk(request, target_date=None, class_id=None, child_id=None, notice=None,
                                  draft_pickup_time=None, draft_pickup_person=None, draft_snack_required=None, session=session)
    remember_terminal(response)
    return response


@router.get("/terminal/status", dependencies=[Depends(require_kiosk_access)])
def guardian_terminal_status(request: Request, session: Session = Depends(get_session)):
    from kiosk_security import KIOSK_DEVICE_COOKIE, kiosk_device_cookie_is_valid
    from models import GuardianTerminalStatus
    from sqlalchemy.exc import IntegrityError
    from time_utils import utc_now
    cookie = request.cookies.get(KIOSK_DEVICE_COOKIE)
    if kiosk_device_cookie_is_valid(cookie):
        device_id = cookie.split(".", 1)[0]
        terminal = session.get(GuardianTerminalStatus, device_id)
        if terminal is None:
            terminal = GuardianTerminalStatus(device_id=device_id, label="保護者端末 " + device_id[:6])
        terminal.last_seen_at = utc_now()
        session.add(terminal)
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
    result = {"kiosk": True, "today": local_today().isoformat(), "server_time": utc_now().isoformat()}
    if kiosk_device_cookie_is_valid(cookie):
        result.update(registration_number=terminal.registration_number, label=terminal.label)
    return result


@router.get("/manifest.webmanifest")
def guardian_manifest():
    return JSONResponse({
        "id": TERMINAL_START, "name": "保護者キオスク", "short_name": "登園・降園",
        "start_url": TERMINAL_START, "scope": "/guardian/", "display": "standalone", "lang": "ja",
        "background_color": "#f8fafc", "theme_color": "#4338ca", "prefer_related_applications": False,
        "icons": [{"src": f"/guardian/assets/icon-{size}.png", "sizes": f"{size}x{size}", "type": "image/png"} for size in (192, 512)],
    }, media_type="application/manifest+json")


@router.get("/assets/{filename}")
def guardian_asset(filename: str):
    if filename not in {"terminal.js", "icon-192.png", "icon-512.png"}:
        raise HTTPException(status_code=404, detail="Not Found")
    return FileResponse(Path(__file__).resolve().parent.parent / "assets" / "guardian" / filename)
