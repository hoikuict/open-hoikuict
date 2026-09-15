import json
import re
from fastapi import FastAPI
from fastapi.testclient import TestClient
from auth import Role, StaffUser, get_current_staff_user
from csrf import CsrfTokenMiddleware
from routers.data_transfers import router


def test_converter_uses_current_schema_and_local_assets_with_permission_checks():
    app = FastAPI()
    app.add_middleware(CsrfTokenMiddleware)
    app.include_router(router)
    user = StaffUser(role=Role.ADMIN, name="確認職員")
    app.dependency_overrides[get_current_staff_user] = lambda: user
    with TestClient(app) as client:
        response = client.get("/data-transfers/converter")
        assert response.status_code == 200
        schemas = json.loads(re.search(r'<script id="schemas" type="application/json">(.*?)</script>', response.text, re.S).group(1))
        assert "保護者①勤務先電話番号" in next(s for s in schemas if s["id"] == "families")["headers"]
        assert '"staff_users"' in response.text
        assert 'https://' not in response.text
        assert "script-src 'self'" in response.headers["content-security-policy"]
        assert response.headers["cache-control"] == "no-store"
        for filename in ("app.js", "core.js", "files.js", "style.css"):
            assert client.get(f"/data-transfers/converter/assets/{filename}").status_code == 200
        assert client.get("/data-transfers/converter/assets/database.py").status_code == 404
        user = StaffUser(role=Role.CAN_EDIT, name="台帳担当", can_manage_child_records=True)
        response = client.get("/data-transfers/converter")
        assert response.status_code == 200 and '"staff_users"' not in response.text
        user = StaffUser(role=Role.VIEW_ONLY, name="閲覧職員")
        assert client.get("/data-transfers/converter").status_code == 403
        assert client.get("/data-transfers/converter/assets/core.js").status_code == 403
