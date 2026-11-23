"""Local-only synthetic data for the first unpublished manual batch."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '.local-dev/document-search-rollout-20261108/source'
os.chdir(SOURCE)
sys.path.insert(0, str(SOURCE))
os.environ.update(PYTHON_DOTENV_DISABLED='1', HOIKUICT_ENV='test', HOIKUICT_DATABASE_URL='sqlite://',
                  HOIKUICT_COOKIE_SECURE='0', HOIKUICT_PARENT_MAIL_TRANSPORT='capture', HOIKUICT_CLASS_KIOSK_WORKER='0')

from datetime import datetime
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session, select
from auth import Role, StaffUser, get_current_staff_user
from models import AttendanceRecord, Child, Family, ParentAccount, ParentChildLink
from routers import attendance, attendance_checks, children
from test_parent_portal import ParentPortalTests
from time_utils import local_today
import uvicorn

t = ParentPortalTests()
t.setUp()
app = t.app
for router in (attendance.router, attendance_checks.router, children.router):
    app.include_router(router)
actor = {'role': Role.CAN_EDIT}
app.dependency_overrides[get_current_staff_user] = lambda: StaffUser(role=actor['role'], name='見本職員', can_manage_child_records=True)
day = local_today()
with Session(t.engine) as db:
    for i, child in enumerate(db.exec(select(Child)).all()):
        child.last_name = '見本'
        child.first_name = ['あおい', 'ひなた', 'そら'][i]
        child.last_name_kana = 'ミホン'
        child.first_name_kana = ['アオイ', 'ヒナタ', 'ソラ'][i]
        db.add(child)
    for i, family in enumerate(db.exec(select(Family)).all()):
        family.family_name = f'見本家庭{i+1}'
        family.home_address = '見本市 見本町1-1'
        family.home_phone = '000-0000-0000'
        family.shared_profile = {'guardians': [
            {'order': 1, 'relationship': '母', 'first_name': 'はな', 'phone': '080-0000-0101', 'workplace_phone': '000-0000-0102'},
            {'order': 2, 'relationship': '父', 'first_name': 'たろう', 'phone': '090-0000-0103', 'workplace_phone': '000-0000-0104'}]}
        db.add(family)
    for i, parent in enumerate(db.exec(select(ParentAccount)).all()):
        parent.display_name = f'見本 保護者{i+1}'
        parent.email = f'manual{i+1}@example.invalid'
        parent.phone = '080-0000-0101'
        parent.home_address = '見本市 見本町1-1'
        db.add(parent)
    for child_id in (t.child_id, t.second_child_id):
        if not db.exec(select(ParentChildLink).where(ParentChildLink.child_id == child_id, ParentChildLink.parent_account_id == t.parent_account_id)).first():
            db.add(ParentChildLink(child_id=child_id, parent_account_id=t.parent_account_id))
    db.add(AttendanceRecord(child_id=t.child_id, attendance_date=day, check_in_at=datetime.combine(day, datetime.min.time()).replace(hour=8, minute=30)))
    db.add(AttendanceRecord(child_id=t.other_child_id, attendance_date=day,
                            check_in_at=datetime.combine(day, datetime.min.time()).replace(hour=8, minute=45),
                            check_out_at=datetime.combine(day, datetime.min.time()).replace(hour=9, minute=15)))
    db.commit()
t._login_parent(t.parent_account_id)

@app.get('/__review/login')
def login():
    response = JSONResponse({'child': t.child_id, 'sibling': t.second_child_id, 'other': t.other_child_id, 'day': day.isoformat()})
    for key, value in t.client.cookies.items():
        response.set_cookie(key, value)
    return response

@app.get('/__review/role/{role}')
def set_role(role: str):
    actor['role'] = Role.VIEW_ONLY if role == 'view' else Role.CAN_EDIT
    return {'role': actor['role'].value}

@app.get('/__review/state')
def state():
    from models import AttendanceCorrection, AttendanceVerification, ChildEmergencyOrder, DailyContactEntry
    with Session(t.engine) as db:
        return {model.__name__: [item.model_dump(mode='json') for item in db.exec(select(model)).all()]
                for model in (AttendanceRecord, AttendanceCorrection, AttendanceVerification, ChildEmergencyOrder, DailyContactEntry)}

app.mount('/static', StaticFiles(directory=SOURCE / 'static'), name='static')
@app.get('/__review/tailwind.js')
def tailwind():
    return FileResponse(ROOT / 'tools/staff-manual-preview/dist/assets/tailwind.js', media_type='text/javascript')

inner = app
app = FastAPI()
app.mount('/', inner)
@app.middleware('http')
async def local_assets(request, call_next):
    response = await call_next(request)
    if 'text/html' not in response.headers.get('content-type', ''):
        return response
    body = b''.join([x async for x in response.body_iterator]).decode('utf-8').replace('https://cdn.tailwindcss.com', '/__review/tailwind.js')
    # The filters retain ordinary HTML form submission in this isolated fixture.
    body = body.replace('<script src="https://unpkg.com/htmx.org@1.9.10"></script>', '')
    headers = dict(response.headers)
    headers.pop('content-length', None)
    return Response(body, status_code=response.status_code, headers=headers)

if __name__ == '__main__':
    try:
        uvicorn.run(app, host='127.0.0.1', port=8173, access_log=False)
    finally:
        t.tearDown()
