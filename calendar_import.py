"""Import a bounded ICS snapshot with reviewed, immutable batches and UID deduplication."""
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
from uuid import UUID
from zoneinfo import ZoneInfo

import icalendar
from dateutil.rrule import rruleset, rrulestr
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, update
from sqlalchemy.exc import IntegrityError
from sqlmodel import Session, select

from auth import get_current_staff_user
from calendar_service import get_calendar_context, list_calendar_contexts
from database import get_session
from models import CalendarActivityKind, CalendarActivityLog, CalendarImportBatch, CalendarImportSource, Event, EventVisibility
from routers.calendar import _require_calendar_user
from template_utils import create_templates
from time_utils import local_today, utc_now

router = APIRouter(prefix="/calendar/import", tags=["calendar"])
templates = create_templates()
MAX_FILE = 5 * 1024 * 1024
MAX_EVENTS = 2000


def parse_ics(content: bytes, start: date, end: date) -> list[dict]:
    if not content or len(content) > MAX_FILE:
        raise ValueError("ICSファイルは5MB以内で指定してください。")
    if end < start or (end - start).days > 366:
        raise ValueError("取込期間は開始日から367日以内で指定してください。")
    try:
        calendar = icalendar.Calendar.from_ical(content)
        if calendar.name != "VCALENDAR":
            raise ValueError()
        zone = ZoneInfo(str(calendar.get("X-WR-TIMEZONE", "Asia/Tokyo")))
        components = calendar.walk("VEVENT")
        if len(components) > MAX_EVENTS:
            raise ValueError("ファイル内の予定が多すぎます。カレンダーを分けて取り込んでください。")

        def stamp(value):
            if isinstance(value, datetime):
                return value if value.tzinfo else value.replace(tzinfo=zone)
            if isinstance(value, date):
                return datetime.combine(value, time.min, zone)
            raise ValueError("予定の日付が不正です。")

        def decoded(component, key):
            prop = component.get(key)
            if prop is None:
                return None
            tzid = prop.params.get("TZID")
            if tzid and isinstance(prop.dt, datetime) and prop.dt.tzinfo is None:
                raise ValueError("対応できないタイムゾーンが含まれています。")
            return prop.dt

        def key(value):
            return stamp(value).astimezone(timezone.utc).isoformat()

        masters, overrides = {}, {}
        for component in components:
            uid = str(component.get("UID", "")).strip()
            if not uid:
                raise ValueError("UIDのない予定は重複を判定できません。Googleから書き出し直してください。")
            recurrence_id = component.get("RECURRENCE-ID")
            if recurrence_id:
                if recurrence_id.params.get("RANGE"):
                    raise ValueError("以降の予定をまとめて変更する例外指定には対応していません。")
                identity = (uid, key(recurrence_id.dt))
                if identity in overrides:
                    raise ValueError("同じ予定の変更回が重複しています。")
                overrides[identity] = component
            else:
                if uid in masters:
                    raise ValueError("同じUIDの予定が重複しています。1つのカレンダーを指定してください。")
                masters[uid] = component
        if any(uid not in masters for uid, _ in overrides):
            raise ValueError("繰り返しの元予定がありません。カレンダー全体を書き出してください。")
        lower = datetime.combine(start, time.min, zone)
        upper = datetime.combine(end + timedelta(days=1), time.min, zone)
        result = {}

        def add(uid, original, component, actual=None):
            if str(component.get("STATUS", "")).upper() == "CANCELLED":
                return
            raw_start = decoded(component, "DTSTART")
            base_start = stamp(raw_start)
            actual = actual or base_start
            raw_end = decoded(component, "DTEND")
            duration = (stamp(raw_end) - base_start) if raw_end is not None else component.decoded("DURATION", None)
            if duration is None:
                duration = timedelta(0) if isinstance(raw_start, datetime) else timedelta(days=1)
            if not isinstance(duration, timedelta) or duration < timedelta(0) or duration > timedelta(days=367):
                raise ValueError("予定の期間が不正か長すぎます。")
            finish = actual + duration
            if actual >= upper or finish < lower or (finish == lower and actual != finish):
                return
            all_day = not isinstance(raw_start, datetime)
            title = str(component.get("SUMMARY", "名称未設定の予定"))
            location = str(component.get("LOCATION", ""))
            if len(title) > 200 or len(location) > 255:
                raise ValueError("予定名は200文字、場所は255文字以内にしてください。")
            identity = sha256((uid + "\0" + original).encode()).hexdigest()
            result[identity] = {
                "source_key": identity, "title": title,
                "description": str(component.get("DESCRIPTION", "")), "location": location,
                "start_at": actual.astimezone(timezone.utc).isoformat(),
                "end_at": finish.astimezone(timezone.utc).isoformat(),
                "timezone": str(zone), "is_all_day": all_day,
                "visibility": "private" if str(component.get("CLASS", "PUBLIC")).upper() in {"PRIVATE", "CONFIDENTIAL"} else "normal",
                "display_start": actual.astimezone(zone).strftime("%Y-%m-%d" if all_day else "%Y-%m-%d %H:%M"),
            }
            if len(result) > MAX_EVENTS:
                raise ValueError("取込予定が2000件を超えます。期間を短くしてください。")

        for uid, master in masters.items():
            if str(master.get("STATUS", "")).upper() == "CANCELLED":
                continue
            initial = stamp(decoded(master, "DTSTART"))
            if master.get("EXRULE"):
                raise ValueError("EXRULE形式の除外には対応していません。EXDATE形式で書き出してください。")
            recurrence = master.get("RRULE")
            dates = rruleset()
            dates.rdate(initial)
            if recurrence:
                if isinstance(recurrence, list) or str(recurrence.get("FREQ", [""])[0]) not in {"DAILY", "WEEKLY", "MONTHLY", "YEARLY"}:
                    raise ValueError("繰り返しは日・週・月・年単位に対応しています。")
                if any(k in recurrence for k in ("BYHOUR", "BYMINUTE", "BYSECOND")):
                    raise ValueError("時分秒を複数指定する繰り返しには対応していません。")
                dates.rrule(rrulestr(recurrence.to_ical().decode(), dtstart=initial))
            for prop_name, fn in (("RDATE", dates.rdate), ("EXDATE", dates.exdate)):
                props = master.get(prop_name, [])
                for prop in props if isinstance(props, list) else [props]:
                    for value in prop.dts:
                        fn(stamp(value.dt))
            # Include overlapping multi-day events; cap expansion before materializing.
            for number, occurrence in enumerate(dates.xafter(lower - timedelta(days=367), inc=True)):
                if occurrence >= upper:
                    break
                if number > 4000:
                    raise ValueError("繰り返し予定が多すぎます。期間を短くしてください。")
                original = key(occurrence) if recurrence or master.get("RDATE") else "single"
                if (uid, original) not in overrides:
                    add(uid, original, master, occurrence)
            for (override_uid, original), component in overrides.items():
                if override_uid == uid:
                    add(uid, original, component)
        return sorted(result.values(), key=lambda item: (item["start_at"], item["title"]))
    except ValueError as exc:
        if str(exc) and any("\u3000" <= ch <= "\u9fff" for ch in str(exc)):
            raise
        raise ValueError("ICSの形式・日付・繰り返し指定を読み取れません。ファイルを確認してください。") from exc
    except Exception as exc:
        raise ValueError("ICSファイルを読み取れません。Googleカレンダーから書き出し直してください。") from exc


def _context(session, user, calendar_id):
    context = get_calendar_context(session, user.id, calendar_id, include_archived=False)
    if not context or not context.can_create_events:
        raise HTTPException(403, "このカレンダーには取り込めません。")
    return context


def _page(request, session, user, current_user, **extra):
    contexts = [c for c in list_calendar_contexts(session, user.id) if c.can_create_events and not c.calendar.is_archived]
    return templates.TemplateResponse(request, "calendar/import.html", {
        "current_user": current_user, "contexts": contexts, "today": local_today(),
        "end_date": local_today() + timedelta(days=365), **extra,
    })


@router.get("")
def import_page(request: Request, session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    return _page(request, session, _require_calendar_user(session, request), current_user)


@router.post("/preview")
async def preview(request: Request, calendar_id: UUID = Form(...), start: date = Form(...), end: date = Form(...),
                  file: UploadFile = File(...), session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    user = _require_calendar_user(session, request)
    context = _context(session, user, calendar_id)
    try:
        if not (file.filename or "").lower().endswith(".ics"):
            raise ValueError("ZIPは展開し、カレンダーの.icsファイルを選択してください。")
        items = parse_ics(await file.read(MAX_FILE + 1), start, end)
    except ValueError as exc:
        return _page(request, session, user, current_user, error=str(exc))
    existing = set(session.exec(select(CalendarImportSource.source_key).where(CalendarImportSource.calendar_id == calendar_id)).all())
    for item in items:
        item["skip"] = item["source_key"] in existing
    session.exec(delete(CalendarImportBatch).where(CalendarImportBatch.expires_at < utc_now()))
    batch = CalendarImportBatch(user_id=user.id, calendar_id=calendar_id, items=items, expires_at=utc_now() + timedelta(minutes=30))
    session.add(batch)
    session.commit()
    return _page(request, session, user, current_user, batch=batch, import_calendar=context.calendar,
                 add_count=sum(not item["skip"] for item in items), skip_count=sum(item["skip"] for item in items))


@router.post("/commit")
def commit(request: Request, batch_id: UUID = Form(...), session: Session = Depends(get_session), current_user=Depends(get_current_staff_user)):
    user = _require_calendar_user(session, request)
    batch = session.get(CalendarImportBatch, batch_id)
    if not batch or batch.user_id != user.id or batch.used_at or batch.expires_at.replace(tzinfo=timezone.utc) <= utc_now():
        return _page(request, session, user, current_user, error="確認の有効期限が切れたか、取込済みです。ファイルを選び直してください。")
    _context(session, user, batch.calendar_id)
    claimed = session.execute(update(CalendarImportBatch).where(CalendarImportBatch.id == batch.id, CalendarImportBatch.used_at.is_(None)).values(used_at=utc_now()))
    if claimed.rowcount != 1:
        session.rollback()
        return _page(request, session, user, current_user, error="この確認内容は既に取り込まれています。")
    try:
        existing = set(session.exec(select(CalendarImportSource.source_key).where(CalendarImportSource.calendar_id == batch.calendar_id)).all())
        added = 0
        for item in batch.items:
            if item["source_key"] in existing:
                continue
            values = {k: item[k] for k in ("title", "description", "location", "timezone", "is_all_day")}
            event = Event(**values, calendar_id=batch.calendar_id, created_by_user_id=user.id,
                          start_at=datetime.fromisoformat(item["start_at"]), end_at=datetime.fromisoformat(item["end_at"]),
                          visibility=EventVisibility(item["visibility"]))
            session.add(event)
            session.flush()
            session.add(CalendarImportSource(calendar_id=batch.calendar_id, source_key=item["source_key"], event_id=event.id))
            added += 1
        if added:
            session.add(CalendarActivityLog(calendar_id=batch.calendar_id, actor_user_id=user.id,
                actor_name=user.display_name, action=CalendarActivityKind.event_created,
                summary=f"Googleカレンダーから予定を{added}件取り込みました。"))
        session.commit()
    except IntegrityError:
        session.rollback()
        return _page(request, session, user, current_user, error="別の取込が先に完了しました。ファイルを選び直してください。")
    return RedirectResponse("/calendar", status_code=303)
