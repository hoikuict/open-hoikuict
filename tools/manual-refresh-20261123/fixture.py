"""Synthetic in-memory fixtures, using the selected deployed-source checkout."""
from pathlib import Path
import os,sys
ROOT=Path(__file__).resolve().parents[2]
SOURCE=Path(os.environ.get('MANUAL_SOURCE',ROOT/'.local-dev/document-search-rollout-20261108/source'))
os.chdir(SOURCE);sys.path.insert(0,str(SOURCE))
os.environ.update(PYTHON_DOTENV_DISABLED='1',HOIKUICT_ENV='test',HOIKUICT_DATABASE_URL='sqlite://',HOIKUICT_COOKIE_SECURE='0',HOIKUICT_PARENT_MAIL_TRANSPORT='capture',HOIKUICT_CLASS_KIOSK_WORKER='0')
from fastapi import FastAPI
from fastapi.responses import FileResponse,JSONResponse,Response
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session,select
from models import Child,ParentAccount,GuardianHoursSetting,Family
import uvicorn
mode=sys.argv[1]
if mode=='parent':
 from test_parent_medical import ParentMedicalTests
 from routers import children
 t=ParentMedicalTests();t.setUp();f=t.fixture;app=f.app;app.include_router(children.router)
 with Session(f.engine) as db:
  for i,child in enumerate(db.exec(select(Child)).all()):child.last_name='見本';child.first_name=['あおい','ひなた','そら'][i]
  for i,parent in enumerate(db.exec(select(ParentAccount)).all()):parent.display_name='見本 保護者'+str(i+1);parent.email='manual'+str(i+1)+'@example.invalid'
  for i,family in enumerate(db.exec(select(Family)).all()):family.family_name=f'見本家庭{i+1}';db.add(family)
  db.add(GuardianHoursSetting(id=1,closing_time='18:30'));db.commit()
 r=f.client.post(f'/parent-portal/children/{f.child_id}/emergency-contacts',data={'base_revision':0,'emergency_label':'母の職場','emergency_phone':'000-0000-0101'},follow_redirects=False);assert r.status_code==303
 @app.get('/__review/login')
 def login():
  response=JSONResponse({'child':f.child_id,'parent':f.parent_account_id,'contact':f'/parent-portal/children/{f.child_id}/contact','pickup':f'/parent-portal/children/{f.child_id}/pickup','medical':t.staff,'parent_medical':t.url})
  for k,v in f.client.cookies.items():response.set_cookie(k,v)
  return response
 @app.post('/__manual/closing')
 def closing(value:str):
  with Session(f.engine) as db:
   item=db.get(GuardianHoursSetting,1);item.closing_time=value;db.add(item);db.commit()
  return {'closing':value}
 cleanup=t.doCleanups
else:
 from test_billing_reopen import BillingReopenTests
 t=BillingReopenTests();t.setUp();app=t.client.app
 @app.get('/__review/login')
 def login():return {'cycle':t.cycle_id,'claim':t.claim_id,'export':t.export_id}
 cleanup=t.tearDown
app.mount('/static',StaticFiles(directory=SOURCE/'static'),name='static')
@app.get('/__review/tailwind.js')
def tailwind():return FileResponse(ROOT/'tools/staff-manual-preview/dist/assets/tailwind.js',media_type='text/javascript')
inner=app;app=FastAPI();app.mount('/',inner)
@app.middleware('http')
async def local_assets(request,call_next):
 response=await call_next(request)
 if 'text/html' not in response.headers.get('content-type',''):return response
 body=b''.join([x async for x in response.body_iterator]).decode('utf-8').replace('https://cdn.tailwindcss.com','/__review/tailwind.js')
 headers=dict(response.headers);headers.pop('content-length',None)
 return Response(body,status_code=response.status_code,headers=headers)
if __name__=='__main__':
 try:uvicorn.run(app,host='127.0.0.1',port={'parent':8171,'billing':8172}[mode],access_log=False)
 finally:cleanup()
