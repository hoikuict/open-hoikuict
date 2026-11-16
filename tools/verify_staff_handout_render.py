"""Render the implemented handout using fictional, in-memory route responses."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.update({"PYTHON_DOTENV_DISABLED": "1", "HOIKUICT_ENV": "test", "HOIKUICT_DATABASE_URL": "sqlite://"})

from sqlmodel import Session
from test_local_staff_auth import LocalStaffAuthenticationTests
from models import User
from routers.staff_auth import templates
from staff_auth_handout import prepare_staff_code_handout


def main():
    destination = ROOT / ".local-dev/staff-handout-verification"
    destination.mkdir(parents=True, exist_ok=True)
    os.environ["HOIKUICT_FACILITY_NAME"] = "みほん保育園"
    case = LocalStaffAuthenticationTests()
    case.setUp()
    try:
        case._activate()
        case._login()
        with Session(case.engine) as session:
            teacher = User(email="hana@example.invalid", display_name="見本 はな", staff_role="can_edit")
            session.add(teacher)
            session.commit()
            teacher_id = teacher.id
        response = case.client.post(f"/staff/users/{teacher_id}/authentication/activate", data={"login_id": "hana@example.invalid", "reason": "管理者だけに表示する架空の理由"})
        assert response.status_code == 200
        (destination / "activate.html").write_text(response.text, encoding="utf-8")
        long_context = dict(response.context)
        long_origin = "https://" + ".".join(["a" * 63, "b" * 63, "c" * 63, "example", "invalid"])
        os.environ["HOIKUICT_STAFF_RECOVERY_BASE_URL"] = long_origin
        long_context.update(prepare_staff_code_handout("activate"))
        long_context.update(target_name="名" * 100, facility_name="見本保育園" * 16, login_id="a" * 230 + "@example.invalid")
        (destination / "long.html").write_text(templates.get_template("staff_auth/action_code.html").render(**long_context), encoding="utf-8")
        os.environ["HOIKUICT_STAFF_RECOVERY_BASE_URL"] = "https://staff.example.invalid"
        activated = case.client.post("/staff/activate", data={"activation_code": case._action_code_from(response), "login_id": "hana@example.invalid", "password": case.PASSWORD, "password_confirmation": case.PASSWORD}, follow_redirects=False)
        assert activated.status_code == 303
        reset = case.client.post(f"/staff/users/{teacher_id}/authentication/reset", data={"reason": "管理者だけに表示する架空の理由"})
        assert reset.status_code == 200
        (destination / "reset.html").write_text(reset.text, encoding="utf-8")
        (destination / "fixture.json").write_text(json.dumps({"fictional_only": True, "code": {"activate": case._action_code_from(response), "reset": case._action_code_from(reset)}, "db": "in-memory; destroyed after render"}, indent=2), encoding="utf-8")
        print("Rendered actual authenticated route responses and long-field fixture.")
    finally:
        case.tearDown()


if __name__ == "__main__":
    main()
