"""Real routes with fictional records in a disposable in-memory database."""
from datetime import date
from pathlib import Path
from fastapi.staticfiles import StaticFiles
from fastapi.responses import RedirectResponse
from sqlmodel import Session
import uvicorn
from auth import Role
from models import Child
from routers.family_care import router, templates
from test_care_certifications import CareCertificationTests

if __name__ == '__main__':
    case=CareCertificationTests();case.setUp();case.current_user.role=Role.ADMIN
    case.app.include_router(router)
    templates.env.globals['family_care_preview']=True
    with Session(case.engine) as session:
        first=session.get(Child,case.child_id);family_id=first.family_id
        for name,enroll in [('入園予定',date(2026,10,15)),('個別設定',date(2024,4,1))]:
            child=Child(last_name='架空',first_name=name,last_name_kana='カクウ',first_name_kana='エンジ',
                birth_date=date(2023,4,1),enrollment_date=enroll,family_id=family_id)
            session.add(child);session.flush()
            if name=='個別設定': individual_id=child.id
        session.commit()
    case.client.post(f'/children/{individual_id}/care-certifications',data=dict(
        care_time_category='short',effective_from='2026-04-01',guardian_reason_1='employment',guardian_reason_2='childcare_leave_continuation'))
    case.app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[1]/'static'),name='static')
    @case.app.get('/')
    def index():return RedirectResponse(f'/families/{family_id}/care-certifications')
    try:uvicorn.run(case.app,host='127.0.0.1',port=8899)
    finally:case.tearDown()
