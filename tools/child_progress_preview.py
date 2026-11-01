"""Local UI verification using only an isolated SQLite fixture and synthetic data."""
from datetime import date
from pathlib import Path
import os
import sys
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1]
os.chdir(SOURCE)
sys.path.insert(0, str(SOURCE))
os.environ["HOIKUICT_ENV"] = "test"
os.environ["HOIKUICT_DATABASE_URL"] = "sqlite://"

from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
import uvicorn

from child_records.models import ChildObservationLog, ChildRecordSettingVersion
from child_records.settings import default_config
from models import Child, ChildStatus
from test_child_records import ChildRecordFeatureTests


def main():
    fixture = ChildRecordFeatureTests()
    fixture.setUp()
    app = fixture.app
    app.mount("/static", StaticFiles(directory=SOURCE / "static"), name="static")
    config = default_config()
    for rule in config["age_rules"].values():
        rule["child_progress_record"]["interval_months"] = 1
    with Session(fixture.engine) as session:
        child = session.get(Child, fixture.child_id)
        child.last_name, child.first_name = "園児", "A（架空）"
        session.add(child)
        session.add(Child(last_name="園児", first_name="B（架空）", last_name_kana="エンジ", first_name_kana="ビー",
            birth_date=date(2024, 3, 1), enrollment_date=date(2025, 4, 1),
            withdrawal_date=date(2026, 9, 30), status=ChildStatus.withdrawn, classroom_id=fixture.classroom_id))
        session.add(ChildRecordSettingVersion(version_no=1, effective_from=date(2000, 1, 1), config=config))
        for day, body in [(date(2026, 9, 5), "友だちのそばで砂遊びを楽しみ、カップを差し出していた。"),
                          (date(2026, 9, 16), "午睡後の着替えを自分でやってみようとする姿があった。"),
                          (date(2026, 10, 3), "10月の記録。秋の自然に関心をもって遊んだ。")]:
            session.add(ChildObservationLog(child_id=fixture.child_id, observed_on=day, child_state=body,
                visibility="shared", sensitivity="normal", created_by_name="確認用の職員"))
        session.commit()
    with patch("child_records.router.local_today", return_value=date(2026, 10, 8)):
        uvicorn.run(app, host="127.0.0.1", port=8802)


if __name__ == "__main__":
    main()
