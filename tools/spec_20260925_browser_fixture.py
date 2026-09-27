"""Memory-only implementation QA, using the September 24 synthetic nursery."""
from tools.spec_20260924_browser_fixture import app, engine
from child_records.router import router, progress_router
from child_records.models import ChildRecordSettingVersion
from child_records.settings import default_config
from sqlmodel import Session, SQLModel
from datetime import date
from models import User

SQLModel.metadata.create_all(engine)
app.include_router(router)
app.include_router(progress_router)
with Session(engine) as session:
    config = default_config()
    for field in config["record_types"]["observation_log"]["fields"]:
        field["enabled"] = True
    session.add(ChildRecordSettingVersion(version_no=1, effective_from=date(2000, 1, 1), config=config))
    session.add(User(email="spec25-recipient@example.test", display_name="共有先 見本職員"))
    session.commit()
