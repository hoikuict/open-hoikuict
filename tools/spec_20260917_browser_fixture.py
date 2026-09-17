"""Isolated synthetic app for the September 17 interaction checks."""
from sqlmodel import Session

from child_records.router import progress_router
from models import HealthCheckRecord, HealthCheckType, Survey, User
from routers import child_health, surveys
from time_utils import local_today
from tools.spec_20260916_browser_fixture import app, actor, fixture

for router in (child_health.router, surveys.router, progress_router):
    app.include_router(router)

with Session(fixture.engine) as session:
    user = User(email="browser-admin@example.test", display_name="画面検証職員", staff_role="admin")
    survey = Survey(title="結果閲覧の検証")
    measurement = HealthCheckRecord(child_id=fixture.child_id, check_type=HealthCheckType.periodic,
                                    checked_at=local_today(), height_cm=95, weight_kg=15)
    session.add_all([user, survey, measurement])
    session.commit()
    actor.user_id = user.id
    survey_id, record_id = survey.id, measurement.id


@app.get('/__fixture17')
def ids17():
    return {'parent_id': fixture.parent_account_id, 'child_id': fixture.child_id,
            'survey_id': survey_id, 'record_id': record_id, 'today': str(local_today())}
