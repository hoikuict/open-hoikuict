"""Render monthly attendance without changing records; print aggregate results only."""
from calendar import monthrange
from datetime import timedelta
import hashlib
import json
from pathlib import Path

from fastapi import HTTPException
from sqlmodel import Session
from starlette.requests import Request

from attendance_monthly_service import save_times
from auth import Role, StaffUser
from database import engine
from routers.attendance import router
from routers.attendance_monthly import page
from time_utils import local_today


def verify():
    required = {("/attendance/monthly", "GET"),
                ("/attendance/monthly/{child_id}/day", "POST"),
                ("/attendance/monthly/{child_id}/bulk", "POST")}
    routes = {(route.path, method) for route in router.routes for method in route.methods}
    assert required <= routes
    today = local_today().replace(day=1)
    months = [today.strftime("%Y-%m"), (today - timedelta(days=1)).strftime("%Y-%m")]
    rendered = children_checked = 0
    with Session(engine) as session:
        session.connection().exec_driver_sql("PRAGMA query_only=ON")
        session.connection().exec_driver_sql("BEGIN")
        for month in months:
            request = Request({"type": "http", "method": "GET", "path": "/attendance/monthly", "headers": []})
            initial = page(request, session, StaffUser(role=Role.ADMIN, name="Verification"), month)
            children = initial.context["children"]
            for child in children or [None]:
                for role in (Role.ADMIN, Role.CAN_EDIT, Role.VIEW_ONLY):
                    actor = StaffUser(role=role, name="Verification")
                    response = page(request, session, actor, month, child.id if child else None)
                    assert response.status_code == 200
                    assert response.headers["cache-control"] == "private, no-store"
                    context = response.context
                    rows = context["rows"]
                    assert len(rows) == (monthrange(*map(int, month.split("-")))[1] if child else 0)
                    assert len({row["date"] for row in rows}) == len(rows)
                    assert all(not row["bulk_eligible"] for row in rows if row["locked"] or row["absent"] or not row["allowed"])
                    assert context["data"]["can_edit"] == actor.can_edit
                    markup = response.body.decode("utf-8")
                    assert ('id="open-bulk"' in markup) == (role == Role.ADMIN and child is not None)
                    assert ('id="bulk-form"' in markup) == (role == Role.ADMIN and child is not None)
                    for asset in ("css/attendance-monthly.css", "js/attendance-monthly.js"):
                        assert "/static/" + asset + "?v=20261004" in markup
                    rendered += 1
                children_checked += int(child is not None)
        for role, bulk in ((Role.VIEW_ONLY, False), (Role.CAN_EDIT, True)):
            try:
                save_times(session, child_id=-1, month=months[0], items=[], reason="", actor=StaffUser(role=role, name="Verification"), bulk=bulk)
            except HTTPException as exc:
                assert exc.status_code == 403
            else:
                raise AssertionError("Unauthorized save was accepted")
        assert not session.new and not session.dirty and not session.deleted
        session.rollback()
    assets = {name: hashlib.sha256(Path("static", name).read_bytes()).hexdigest()
              for name in ("css/attendance-monthly.css", "js/attendance-monthly.js")}
    return {"verified": True, "read_only": True, "records_written": 0,
            "months": len(months), "child_months": children_checked, "pages": rendered,
            "roles_verified": True, "asset_sha256": assets}


if __name__ == "__main__":
    print("ATTENDANCE_MONTHLY_LIVE=" + json.dumps(verify()))
