"""Serve the implementation with fictional, disposable in-memory records."""
from datetime import date, datetime
from pathlib import Path

from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session
import uvicorn

from auth import Role
from models import AttendanceRecord, CareTimeCategory, ChildCareCertification, ExtendedCareCalculationSetting
from test_extended_care_bands import plan
from test_extended_care_fees import ExtendedCareFeeTests
from extended_care_fee_service import recalculate_period
from routers.extended_care_fees import templates


if __name__ == '__main__':
    case = ExtendedCareFeeTests(); case.setUp(); case.current_user.role=Role.ADMIN
    case.current_user.name='操作検証用・架空園長'
    templates.env.globals['fee_preview']=True
    standard=case.client.post('/extended-care-fees/settings/bands/standard',json=plan());standard.raise_for_status()
    short=plan();short.update(name='短時間の延長',normalStart='09:00',normalEnd='17:00',morningEnabled=True,
        morningBands=[dict(start='07:30',end='09:00',mode='unit',unit='15',price='100')])
    short['eveningBands'].insert(0,dict(start='17:00',end='18:00',mode='unit',unit='15',price='100'))
    case.client.post('/extended-care-fees/settings/bands/short',json=short).raise_for_status()
    with Session(case.engine) as session:
        session.add(ExtendedCareCalculationSetting(mode='category_aware',category_aware_from=date(2026,4,1)))
        session.add(ChildCareCertification(child_id=case.child_id,care_time_category=CareTimeCategory.standard,effective_from=date(2026,4,1)))
        for i,leave in enumerate([(18,50),(19,20),(19,10),(20,10)],5):
            session.add(AttendanceRecord(child_id=case.child_id,attendance_date=date(2026,9,i),check_in_at=datetime(2026,9,i,8,30),check_out_at=datetime(2026,9,i,*leave)))
        session.commit();recalculate_period(session,date(2026,9,1),date(2026,9,30));session.commit()
    app=case.app
    app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[1]/'static'),name='static')
    @app.get('/')
    def index(): return RedirectResponse('/extended-care-fees/settings')
    try: uvicorn.run(app,host='127.0.0.1',port=8897)
    finally: case.tearDown()
