"""Reproduce the three 2026-09-28 findings using isolated synthetic databases.

Run from the repository root with venv/Scripts/python.exe. This is a diagnostic
script: assertions validate the observed reproduction, not desired application
behavior. No production database, HTTP server, or external service is used.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html import unescape
import json
import os
from pathlib import Path
import re
import sys
from tempfile import TemporaryDirectory
from threading import Barrier, Lock
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# Set before importing database or any application modules.
os.environ["HOIKUICT_DATABASE_URL"] = "sqlite://"

from fastapi import Depends, Request  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import event as sql_event  # noqa: E402
from sqlmodel import Session, create_engine, select  # noqa: E402

import auth  # noqa: E402
import database  # noqa: E402
import routers.staff_auth as staff_routes  # noqa: E402
import test_extended_care_billing_transfer as billing_tests  # noqa: E402
from calendar_service import normalize_utc  # noqa: E402
from local_auth import activate_staff_password, create_staff_credential  # noqa: E402
from models import (  # noqa: E402
    BillingChargeLine,
    BillingClaim,
    BillingClaimStatus,
    BillingPaymentMethod,
    CalendarMember,
    Event,
    EventOverride,
    ExtendedCareBillingSetting,
    ExtendedCareBillingTransferLog,
    ExtendedCareCharge,
    FeeItem,
    User,
)
from test_calendar_feature import CalendarFeatureTests  # noqa: E402


def create_event(fixture, client, calendar_id, title, **extra):
    form = {
        "calendar_id": str(calendar_id), "title": title,
        "timezone": "Asia/Tokyo", "start_value": "2026-09-14T09:00",
        "end_value": "2026-09-14T10:00", **extra,
    }
    response = client.post("/events", data=form, follow_redirects=False)
    assert response.status_code == 303, response.text
    with Session(fixture.engine) as session:
        return session.exec(select(Event).where(Event.title == title)).one().id


def verify_downgrade():
    fixture = CalendarFeatureTests()
    fixture.setUp()
    fixture.app.include_router(staff_routes.router)
    fixture.app.include_router(staff_routes.local_login_router)

    @fixture.app.get("/verification/principal")
    def principal(user=Depends(auth.get_current_staff_user)):
        return {"role": user.role.value, "user_id": str(user.user_id)}

    env = {
        "HOIKUICT_ENV": "test", "HOIKUICT_ENABLE_MOCK_AUTH": "0",
        "HOIKUICT_STAFF_AUTH_MODE": "local_password",
        "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "verification-only-key-" * 3,
        "HOIKUICT_COOKIE_SECURE": "0", "HOIKUICT_CSRF_ENFORCE": "0",
    }
    password = "Synthetic verification password 2026!"
    try:
        with patch.dict(os.environ, env), patch.object(database, "engine", fixture.engine):
            auth.configure_auth_backends_from_environment()
            for user_id, login in ((fixture.user_a_id, "verify-admin"), (fixture.user_b_id, "verify-editor")):
                with Session(fixture.engine) as session:
                    _, code = create_staff_credential(session, user=session.get(User, user_id), login_id=login)
                    session.commit()
                    activate_staff_password(session, activation_code=code, password=password, password_confirmation=password)

            def login(client, name):
                response = client.post("/staff/login", data={"login_id": name, "password": password}, follow_redirects=False)
                assert response.status_code == 303, response.text

            with TestClient(fixture.app) as admin, TestClient(fixture.app) as editor:
                login(admin, "verify-admin")
                login(editor, "verify-editor")
                assert editor.get("/verification/principal").json()["role"] == "can_edit"
                cases = []
                for label, calendar_id, creator in (
                    ("personal_own", fixture.b_personal_id, editor),
                    ("shared_own", fixture.shared_calendar_id, editor),
                    ("shared_other", fixture.shared_calendar_id, admin),
                ):
                    event_ids = {op: create_event(fixture, creator, calendar_id, f"verify-{label}-{op}")
                                 for op in ("move", "resize", "delete", "update")}
                    cases.append((label, calendar_id, event_ids))
                change = admin.post(f"/staff/permissions/{fixture.user_b_id}", data={"staff_role": "view_only"}, follow_redirects=False)
                assert change.status_code == 303
                with Session(fixture.engine) as session:
                    assert session.get(User, fixture.user_b_id).staff_role == "view_only"

            # A new cookie jar and a fresh real password login, after the downgrade.
            with TestClient(fixture.app) as viewer:
                login(viewer, "verify-editor")
                resolved_principal = viewer.get("/verification/principal").json()
                assert resolved_principal["role"] == "view_only"
                assert viewer.get("/calendar").status_code == 200
                with Session(fixture.engine) as session:
                    memberships = {
                        "personal": session.exec(select(CalendarMember).where(CalendarMember.user_id == fixture.user_b_id, CalendarMember.calendar_id == fixture.b_personal_id)).one().role.value,
                        "shared": session.exec(select(CalendarMember).where(CalendarMember.user_id == fixture.user_b_id, CalendarMember.calendar_id == fixture.shared_calendar_id)).one().role.value,
                    }
                observations = []
                for label, calendar_id, ids in cases:
                    moved = viewer.post(f"/events/{ids['move']}/move", data={"start_at": "2026-09-15T00:00:00+00:00", "end_at": "2026-09-15T01:00:00+00:00"})
                    resized = viewer.post(f"/events/{ids['resize']}/resize", data={"end_at": "2026-09-14T02:00:00+00:00"})
                    deleted = viewer.post(f"/events/{ids['delete']}/delete", follow_redirects=False)
                    form = {"calendar_id": str(calendar_id), "title": "unauthorized edit", "timezone": "Asia/Tokyo", "start_value": "2026-09-14T09:00", "end_value": "2026-09-14T10:00"}
                    updated = viewer.post(f"/events/{ids['update']}", data=form, follow_redirects=False)
                    created = viewer.post("/events", data=form, follow_redirects=False)
                    statuses = {"move": moved.status_code, "resize": resized.status_code, "delete": deleted.status_code, "update": updated.status_code, "create": created.status_code}
                    assert statuses == {"move": 200, "resize": 200, "delete": 303, "update": 403, "create": 403}, statuses
                    with Session(fixture.engine) as session:
                        assert normalize_utc(session.get(Event, ids["move"]).start_at) == datetime(2026, 9, 15, tzinfo=timezone.utc)
                        assert normalize_utc(session.get(Event, ids["resize"]).end_at) == datetime(2026, 9, 14, 2, tzinfo=timezone.utc)
                        assert session.get(Event, ids["delete"]).is_deleted
                        assert session.get(Event, ids["update"]).title == f"verify-{label}-update"
                    observations.append({"case": label, "status": statuses, "database_changes_verified": True})
                return {"auth": "real local_password, fresh login after admin permissions POST", "principal": resolved_principal["role"], "membership_after_sync": memberships, "cases": observations}
    finally:
        auth.reset_auth_backends()
        fixture.tearDown()


def occurrence_link_count(response, event_id, original):
    assert response.status_code == 200, response.text
    count = 0
    for raw in re.findall(r'hx-get="([^"]+)"', response.text):
        url = urlsplit(unescape(raw))
        if url.path == f"/events/{event_id}" and parse_qs(url.query).get("original_start_at") == [original]:
            count += 1
    return count


def verify_recurrence():
    results = []
    original = "2026-09-21T00:00:00+00:00"
    for method in ("move", "edit_one"):
        for target in ("2026-09-22", "2026-09-29", "2026-11-03"):
            fixture = CalendarFeatureTests()
            fixture.setUp()
            try:
                fixture._login(fixture.user_a_id)
                title = f"verify-recurrence-{method}-{target}"
                event_id = create_event(fixture, fixture.client, fixture.a_personal_id, title, recurrence_mode="weekly", recurrence_count="3")
                params = {"original_start_at": original}
                if method == "move":
                    response = fixture.client.post(f"/events/{event_id}/move", data={**params, "start_at": f"{target}T00:00:00+00:00", "end_at": f"{target}T01:00:00+00:00"})
                    assert response.status_code == 200, response.text
                else:
                    response = fixture.client.post(f"/events/{event_id}", data={**params, "calendar_id": str(fixture.a_personal_id), "scope": "one", "title": title, "timezone": "Asia/Tokyo", "start_value": f"{target}T09:00", "end_value": f"{target}T10:00"}, follow_redirects=False)
                    assert response.status_code == 303, response.text
                with Session(fixture.engine) as session:
                    override = session.exec(select(EventOverride).where(EventOverride.series_event_id == event_id)).one()
                    assert normalize_utc(override.start_at).isoformat() == f"{target}T00:00:00+00:00"
                counts = {}
                for mode in ("day", "week", "month"):
                    page = fixture.client.get("/calendar/view", params={"mode": mode, "date": target})
                    counts[mode] = occurrence_link_count(page, event_id, original)
                counts["origin_day"] = occurrence_link_count(fixture.client.get("/calendar/view", params={"mode": "day", "date": "2026-09-21"}), event_id, original)
                for label, start, end in (("search_target", target, target), ("search_origin", "2026-09-21", "2026-09-21"), ("search_both", "2026-09-01", "2026-11-30")):
                    page = fixture.client.get("/search/events", params={"q": title, "date_from": start, "date_to": end})
                    counts[label] = occurrence_link_count(page, event_id, original)
                assert counts["day"] == counts["search_target"] == counts["origin_day"] == 0, counts
                assert counts["search_origin"] == counts["search_both"] == 1, counts
                results.append({"method": method, "original": "2026-09-21 09:00 JST", "destination": target + " 09:00 JST", "saved_override_verified": True, "displayed_occurrence_counts": counts})
            finally:
                fixture.tearDown()
    return results


def billing_snapshot(engine):
    with Session(engine) as session:
        claims = session.exec(select(BillingClaim)).all()
        lines = session.exec(select(BillingChargeLine)).all()
        charges = session.exec(select(ExtendedCareCharge).order_by(ExtendedCareCharge.id)).all()
        logs = session.exec(select(ExtendedCareBillingTransferLog)).all()
        assert len(claims) == len(lines) == len(logs) == 1
        assert claims[0].total_amount == lines[0].amount == 350
        assert lines[0].is_locked
        assert [c.transferred_amount for c in charges] == [100, 250]
        assert all(c.billing_charge_line_id == lines[0].id for c in charges)
        assert [log.action for log in logs] == ["transfer"]
        assert logs[0].total_amount == 350
        assert session.connection().exec_driver_sql("PRAGMA foreign_key_check").all() == []
        return {
            "claims": len(claims), "lines": len(lines), "logs": len(logs),
            "claim_total": claims[0].total_amount, "line_amount": lines[0].amount,
            "line_locked": lines[0].is_locked,
            "charge_amounts": [c.transferred_amount for c in charges],
            "charge_line_links_valid": True, "foreign_key_violations": 0,
        }


def verify_concurrent_transfer(stage, repetition):
    with TemporaryDirectory(prefix="hoikuict-billing-verify-") as tmp:
        engine = create_engine(f"sqlite:///{Path(tmp) / 'isolated.sqlite3'}", connect_args={"check_same_thread": False, "timeout": 15})

        @sql_event.listens_for(engine, "connect")
        def pragmas(connection, _):
            connection.execute("PRAGMA busy_timeout=15000")
            connection.execute("PRAGMA synchronous=NORMAL")
            connection.execute("PRAGMA foreign_keys=ON")

        with engine.connect() as connection:
            assert connection.exec_driver_sql("PRAGMA journal_mode=WAL").scalar_one() == "wal"
        fixture = billing_tests.ExtendedCareBillingTransferTests()
        # Reuse synthetic fixtures, but replace their single-connection memory DB.
        with patch.object(billing_tests, "create_engine", return_value=engine):
            fixture.setUp()
        try:
            fixture._create_charge(date(2026, 3, 2), datetime(2026, 3, 2, 18, 6))
            fixture._create_charge(date(2026, 3, 3), datetime(2026, 3, 3, 18, 21), adjustment=50)
            with Session(engine) as session:
                users = [User(email=f"actor-{i}@example.test", display_name=f"Actor {i}", staff_role="can_edit") for i in range(2)]
                session.add_all(users)
                session.flush()
                actor_ids = [u.id for u in users]
                if stage in {"claim", "line", "natural"}:
                    setting = session.exec(select(ExtendedCareBillingSetting)).one()
                    session.add(FeeItem(code=setting.fee_item_code, name="Verification fee", category="monthly", charge_unit="child"))
                if stage == "line":
                    child = session.get(billing_tests.Child, fixture.child_id)
                    session.add(BillingClaim(billing_cycle_id=fixture.cycle_id, family_id=child.family_id, payment_method=BillingPaymentMethod.direct_debit, status=BillingClaimStatus.confirmed))
                session.commit()

            def current_actor(request: Request):
                actor = int(request.headers["X-Verification-Actor"])
                return auth.StaffUser(role=auth.Role.CAN_EDIT, name=f"Actor {actor}", user_id=actor_ids[actor])

            fixture.app.dependency_overrides[billing_tests.extended_care_fees_module.get_current_staff_user] = current_actor
            gate = Barrier(2, timeout=15)
            start_gate = Barrier(2, timeout=15)
            lock = Lock()
            seen_connections = set()
            errors = []
            target_table = {"fee": "fee_items", "claim": "billing_claims", "line": "billing_charge_lines", "natural": None}[stage]

            def synchronize_insert(connection, cursor, statement, parameters, context, executemany):
                if target_table and statement.startswith(f"INSERT INTO {target_table} "):
                    connection_id = id(connection.connection.driver_connection)
                    with lock:
                        first_insert = connection_id not in seen_connections
                        seen_connections.add(connection_id)
                    if first_insert:
                        gate.wait()

            def capture_error(context):
                with lock:
                    errors.append({"type": type(context.original_exception).__name__, "message": str(context.original_exception)})

            sql_event.listen(engine, "before_cursor_execute", synchronize_insert)
            sql_event.listen(engine, "handle_error", capture_error)

            def transfer(actor):
                with TestClient(fixture.app, raise_server_exceptions=False) as client:
                    start_gate.wait()
                    response = client.post("/extended-care-fees/billing-transfer", data={"month": "2026-03"}, headers={"X-Verification-Actor": str(actor)}, follow_redirects=False)
                    return {"actor": actor, "status": response.status_code, "body": response.text, "location": unescape(response.headers.get("location", ""))}

            try:
                with ThreadPoolExecutor(max_workers=2) as executor:
                    outcomes = list(executor.map(transfer, range(2)))
            finally:
                sql_event.remove(engine, "before_cursor_execute", synchronize_insert)
                sql_event.remove(engine, "handle_error", capture_error)
            statuses = sorted(o["status"] for o in outcomes)
            if stage != "natural":
                assert len(seen_connections) == 2, seen_connections
                assert statuses == [303, 500], outcomes
                assert len(errors) == 1 and errors[0]["type"] == "IntegrityError", errors
            else:
                assert statuses in ([303, 303], [303, 500]), outcomes
            initial = billing_snapshot(engine)
            loser = next((o["actor"] for o in outcomes if o["status"] == 500), 1)
            with TestClient(fixture.app, raise_server_exceptions=False) as client:
                retry = client.post("/extended-care-fees/billing-transfer", data={"month": "2026-03"}, headers={"X-Verification-Actor": str(loser)}, follow_redirects=False)
            assert retry.status_code == 303, retry.text
            retry_message = parse_qs(urlsplit(retry.headers["location"]).query)["message"][0]
            assert "変更はありませんでした" in retry_message, retry_message
            assert billing_snapshot(engine) == initial
            return {"stage": stage, "repetition": repetition, "synchronization": "before INSERT, after both requests read missing row" if target_table else "request start only", "distinct_connections_at_insert": len(seen_connections) if target_table else None, "statuses": [o["status"] for o in outcomes], "db_errors": errors, "snapshot": initial, "retry_status": retry.status_code, "retry_message": retry_message}
        finally:
            fixture.tearDown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = {"environment": {"python": sys.version.split()[0], "database": "isolated SQLite; billing uses WAL, foreign_keys=ON, busy_timeout=15000", "scope": "current working tree, synthetic fixtures, HTTP through FastAPI TestClient"}}
    report["permission_downgrade"] = verify_downgrade()
    print("Verified: real-login permission downgrade and committed event mutations.", flush=True)
    report["recurrence_moves"] = verify_recurrence()
    print("Verified: 6 recurrence moves, destination/origin calendar and search results.", flush=True)
    report["concurrent_transfers"] = [verify_concurrent_transfer(stage, n) for stage in ("fee", "claim", "line", "natural") for n in range(1, 4)]
    print("Verified: 12 concurrent transfers, consistency, and retries.", flush=True)
    output = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(output + "\n", encoding="utf-8")
        print(f"Report: {args.output}")
    else:
        print(output)


if __name__ == "__main__":
    main()
