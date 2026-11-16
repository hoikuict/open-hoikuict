"""Loopback capture of the deployed health screens using only fictional records."""
from datetime import date, timedelta
import json
import os
from pathlib import Path
import socket
import sys

root = Path(__file__).resolve().parents[4]
source = Path(os.environ.get("HEALTH_MANUAL_SOURCE", root / ".local-dev/document-search-rollout-20261108/source")).resolve()
os.chdir(source)
sys.path.insert(0, str(source))
os.environ.update(PYTHON_DOTENV_DISABLED="1", HOIKUICT_ENV="development", HOIKUICT_DATABASE_URL="sqlite://",
                  HOIKUICT_ENABLE_MOCK_AUTH="1")

import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
import child_health_service
from models import Child, ChildStatus, Family, HealthCheckRecord, HealthCheckType
from routers import child_health
from test_child_health import ChildHealthRouterTests
from testing_helpers import authenticate_mock_staff

today = date(2026, 11, 9)
child_health.local_today = child_health_service.local_today = lambda: today
fixture = ChildHealthRouterTests()
fixture.setUp()
try:
    authenticate_mock_staff(fixture.client, name="見本 はなこ")
    with Session(fixture.engine) as session:
        first = session.get(Child, fixture.child_id)
        first.last_name, first.first_name = "見本", "あおい"
        first.last_name_kana, first.first_name_kana = "ミホン", "アオイ"
        first.extra_data = {}
        session.get(Family, first.family_id).family_name = "見本家"
        second = Child(last_name="見本", first_name="ひなた", last_name_kana="ミホン",
                       first_name_kana="ヒナタ", birth_date=date(2022, 7, 4),
                       enrollment_date=date(2025, 4, 1), status=ChildStatus.enrolled,
                       family_id=first.family_id, classroom_id=first.classroom_id)
        session.add(second)
        session.flush()
        def measurement(child, day, kind, height=None, weight=None):
            session.add(HealthCheckRecord(child_id=child.id, checked_at=day, check_type=kind,
                        height_cm=height, weight_kg=weight, observer_name="見本 はなこ"))
        measurement(first, date(2025, 9, 12), HealthCheckType.entrance, 91.0, 13.5)
        measurement(first, date(2026, 6, 12), HealthCheckType.periodic, 94.5, 14.2)
        measurement(first, date(2026, 10, 12), HealthCheckType.periodic, 96.0, 14.6)
        # Mixed measurement dates and the 180-day boundary are intentional.
        measurement(second, today-timedelta(days=181), HealthCheckType.entrance, 93.0)
        measurement(second, today-timedelta(days=180), HealthCheckType.entrance, weight=14.0)
        session.commit()
    fixture.app.mount("/static", StaticFiles(directory=source/"static"), name="static")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        print(json.dumps({"origin":f"http://127.0.0.1:{sock.getsockname()[1]}",
                          "cookies":dict(fixture.client.cookies)}), flush=True)
        uvicorn.Server(uvicorn.Config(fixture.app, log_level="warning", lifespan="off")).run(sockets=[sock])
finally:
    fixture.tearDown()
