"""Run the actual contact routes with fictional in-memory data, bound to loopback."""
import os
from datetime import date, timedelta
from pathlib import Path

os.environ.update(HOIKUICT_ENV='development', HOIKUICT_DATABASE_URL='sqlite://',
                  HOIKUICT_ENABLE_MOCK_AUTH='1', HOIKUICT_PARENT_MAIL_TRANSPORT='capture',
                  HOIKUICT_COOKIE_SECURE='0', HOIKUICT_CSRF_ENFORCE='1',
                  HOIKUICT_SECRET_KEY='fictional-contact-content-browser-verification')

from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, DictLoader
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
from auth import Role, StaffUser, get_current_staff_user
from csrf import CsrfTokenMiddleware, verify_csrf
from database import get_session
from models import AttendanceRecord, Child, Classroom, DailyContactEntry, DailyContactReply, ParentAccount, User
from routers import daily_contacts
from time_utils import local_today

engine = create_engine('sqlite://', connect_args={'check_same_thread':False}, poolclass=StaticPool)
SQLModel.metadata.create_all(engine)
day = local_today()
with Session(engine) as session:
    user = User(email='contact-fixture@example.test',display_name='実装検証 職員',staff_role='admin')
    parent = ParentAccount(display_name='架空の保護者', email='fictional-parent@example.test')
    classes = [Classroom(name=name,display_order=i) for i,name in enumerate(['ひよこ組','りす組','うさぎ組（対象なし）'])]
    session.add_all([user,parent,*classes]); session.flush()
    actor = StaffUser(role=Role.ADMIN,name=user.display_name,user_id=user.id)
    names = ['青葉 はる','朝日 そら','小野 ひなた','川原 つむぎ','高木 みなと','中原 あおい','花村 こはる','藤野 りく','森川 すず','若葉 ゆう']
    for i,name in enumerate(names):
        last,first=name.split(' ')
        child=Child(last_name=last,first_name=first,last_name_kana=f'{i:02}',first_name_kana=f'{i:02}',
                    birth_date=date(2024,4,1),enrollment_date=date(2026,4,1),classroom_id=classes[i//6].id)
        session.add(child);session.flush()
        for offset in (0,1):
            target=day-timedelta(days=offset)
            if i not in (1,8):
                partial=i==3
                kind='absent_sick' if i==5 else 'absent_private' if i==9 else 'present'
                session.add(DailyContactEntry(child_id=child.id,parent_account_id=parent.id,target_date=target,contact_type=kind,
                    temperature='36.6' if kind=='present' else None,mood=None if partial else '普通',
                    sleep_notes=None if partial else '夜中に一度起きました。',breakfast_status='完食',
                    bowel_movement_status=None if partial else '前日夕方から連絡時まで',
                    cough='なし',runny_nose='少し',medication='なし',
                    condition_note=None if partial else '体調はいつもどおりです。',
                    contact_note='週末は公園でたくさん歩きました。落ち葉を見つけるたびに立ち止まって、色や形をじっくり見ていました。\n今朝は朝食をしっかり食べています。着替えを1組多めに入れました。',
                    absence_temperature='38.0' if kind=='absent_sick' else None,
                    absence_symptoms='発熱、咳' if kind=='absent_sick' else None,
                    absence_diagnosis='未受診' if kind=='absent_sick' else None,
                    absence_note='今日はお休みします。' if kind!='present' else None,
                    extra_data={'wakeup_time':'06:30'} if partial else {'bedtime':'20:30','wakeup_time':'06:30',
                        'stool_consistency':'none' if i==4 else 'normal','stool_count':0 if i==4 else 1,
                        'breakfast_contents':'ごはん、豆腐のみそ汁、卵焼き、バナナ'}))
            if i<5 or i in (6,7):
                session.add(AttendanceRecord(child_id=child.id,attendance_date=target,planned_pickup_time='16:30',
                    pickup_person=None if i==3 else '父' if i==1 else '母',snack_required=i==1,pickup_snack_confirmed=i!=3))
            if i%4!=1:
                session.add(DailyContactReply(child_id=child.id,target_date=target,status='published' if i%4 in (0,3) else 'draft',
                    field_values={'nap_time':'12:30-14:00','temperature':'36.7','bowel_movement':'あり','appetite':'完食'},
                    message='園庭で遊びました。',staff_name=actor.name,pending_draft={'message':'未送信の変更'} if i%4==3 else None))
    session.commit()

app=FastAPI(dependencies=[Depends(verify_csrf)])
app.add_middleware(CsrfTokenMiddleware)
app.include_router(daily_contacts.router)
app.mount('/static',StaticFiles(directory=Path(__file__).resolve().parents[1]/'static'),name='static')
def sessions():
    with Session(engine) as session:
        yield session
app.dependency_overrides[get_session]=sessions
app.dependency_overrides[get_current_staff_user]=lambda:actor
env=daily_contacts.templates.env
base=env.loader.get_source(env,'base.html')[0]
base=base.replace('<body class="bg-slate-50 text-slate-800">', '<body class="bg-slate-50 text-slate-800"><div class="bg-amber-50 border-b border-amber-200 p-2 text-sm text-amber-900">実装の検証用・架空データのみ（本番未反映）</div>')
env.loader=ChoiceLoader([DictLoader({'base.html':base}),env.loader])

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8907)
