"""Loopback-only layout mock using deployed code and an in-memory fake nursery."""
import importlib.util
import os
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/truenas-spec-20260925/source'
if not SOURCE.joinpath('templates/attendance_checks/list.html').is_file():
    raise RuntimeError('The verified September 25 production source is required')
sys.path.insert(0, str(SOURCE))
sys.path.insert(1, str(ROOT))
os.chdir(SOURCE)
os.environ['HOIKUICT_DATABASE_URL'] = 'sqlite://'
spec = importlib.util.spec_from_file_location('desktop_fake_nursery', ROOT / 'tools/spec_20260924_browser_fixture.py')
fixture = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture)
app, engine = fixture.app, fixture.engine

from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, DictLoader
from sqlmodel import Session, select, delete
from models import AttendanceVerification, AttendanceVerificationHistory, AttendanceAlarmHistory, AttendanceAlarmState, Child
from routers import attendance_checks

# Use the deployed assets and templates; only this preview injects layout controls.
for route in app.routes:
    if route.path == '/static':
        route.app = StaticFiles(directory=SOURCE / 'static')
app.mount('/__preview__/assets', StaticFiles(directory=HERE), name='preview-assets')
template = (SOURCE / 'templates/attendance_checks/list.html').read_text(encoding='utf-8')
chrome = '''
<link rel="stylesheet" href="/__preview__/assets/layout.css">
<script src="/__preview__/assets/layout.js" defer></script>
<section class="desktop-review" aria-label="配置を比較するモック">
  <div><strong>配置の確認用モック</strong><span>架空100人・本番未反映</span></div>
  <div class="review-options">
    <label>配置<select id="preview-arrangement"><option value="compact">1列でコンパクト</option><option value="current">現在の配置</option></select></label>
    <label>入力状態<select id="preview-scenario">{% for value, label in [('partial', '一部入力'), ('empty', '未入力'), ('filled', '入力済み')] %}<option value="{{ value }}" {% if preview_scenario() == value %}selected{% endif %}>{{ label }}</option>{% endfor %}</select></label>
    <label class="review-error"><input id="preview-error" type="checkbox">目視確認の保存エラー（1回）</label>
    <span id="preview-layout-note"></span>
  </div>
</section>
'''
template = template.replace('{% block content %}', '{% block content %}' + chrome, 1)
attendance_checks.templates.env.loader = ChoiceLoader([
    DictLoader({'attendance_checks/list.html': template}), attendance_checks.templates.env.loader,
])
preview_state = {'scenario': 'partial'}
attendance_checks.templates.env.globals['preview_scenario'] = lambda: preview_state['scenario']

# No notification can leave this mock, including the optional unknown-state notice.
attendance_checks.notify_attendance_confirmation_needed = lambda *args, **kwargs: None

@app.middleware('http')
async def preview_safety(request: Request, call_next):
    if request.method == 'POST' and request.headers.get('x-preview-save-error') == '1':
        return JSONResponse({'detail': 'モックの保存エラーです。入力内容は残っています。もう一度「記録する」を押すと保存できます。'}, status_code=503)
    response = await call_next(request)
    response.headers['Cache-Control'] = 'no-store'
    return response

@app.get('/')
def home():
    return RedirectResponse('/attendance-checks/')

@app.post('/__preview__/scenario')
def scenario(value: str):
    if value not in {'empty', 'partial', 'filled'}:
        raise HTTPException(status_code=400)
    with Session(engine) as session:
        for model in (AttendanceVerificationHistory, AttendanceVerification, AttendanceAlarmHistory, AttendanceAlarmState):
            session.exec(delete(model))
        for child in session.exec(select(Child)).all():
            if value == 'filled' or value == 'partial' and child.id % 10 < 8:
                session.add(AttendanceVerification(child_id=child.id, target_date=fixture.today,
                    status='sick_absent' if child.id % 10 == 7 else 'present', updated_by_name=fixture.actor.name))
        session.commit()
    preview_state['scenario'] = value
    return {'scenario': value}

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8888)
