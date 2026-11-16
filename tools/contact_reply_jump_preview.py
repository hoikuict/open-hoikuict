"""Preview a reply shortcut using deployed templates and fictional in-memory data.

Run from the repository: python tools/contact_reply_jump_preview.py
This is a mock: production POST handlers are removed, including reply sending.
"""
import os
import re
import subprocess
import sys
from copy import deepcopy
from datetime import date
from pathlib import Path
from urllib.parse import urlencode

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / '.local-dev/truenas-monthly-export-20260927/source'
BASELINE = 'f79846c31e361da6fed3f02f13798c4e4720a534'
FILES = (
    'templates/base.html', 'templates/daily_contacts/list.html',
    'templates/daily_contacts/_content_table.html', 'templates/daily_contacts/detail.html',
    'routers/daily_contacts.py', 'daily_contact_reply_fields.py',
    'static/css/daily-contact-list.css', 'static/js/daily-contact-list.js',
    'static/css/daily-contact-reply.css', 'static/js/daily-contact-reply.js',
)
for name in FILES:
    committed = subprocess.check_output(['git', '-C', str(SOURCE), 'show', f'{BASELINE}:{name}'])
    assert committed.replace(b'\r\n', b'\n') == (SOURCE / name).read_bytes().replace(b'\r\n', b'\n'), name

# The fixture sets sqlite:// and development/capture mode BEFORE importing the app.
sys.path.insert(0, str(SOURCE))
os.chdir(SOURCE)
import contact_content_browser_fixture as fixture
from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from jinja2 import ChoiceLoader, DictLoader, FileSystemLoader
from sqlmodel import Session, select
from auth import Role, StaffUser, get_current_staff_user
from models import Child, DailyContactReply, DailyContactReplyStatus
from time_utils import utc_now

assert Path(fixture.daily_contacts.__file__).resolve().is_relative_to(SOURCE)
assert fixture.engine.url.database is None
app = fixture.app
app.router.routes[:] = [route for route in app.router.routes
                       if getattr(route, 'methods', None) and route.methods <= {'GET', 'HEAD'}]
app.mount('/static', StaticFiles(directory=SOURCE / 'static'), name='static')

SCENARIOS = {'mixed': '混在', 'empty': '未入力', 'filled': '入力済み',
             'partial': '一部入力', 'error': '保存エラー'}
scenario = 'mixed'
fixture.actor.name = '確認用職員'
with Session(fixture.engine) as session:
    for reply in session.exec(select(DailyContactReply)).all():
        reply.staff_name = fixture.actor.name
        if reply.pending_draft:
            reply.pending_draft = {'field_values': {'nap_time': '12:30-14:00'},
                                   'message': '午後の様子を追記しています。', 'staff_name': fixture.actor.name}
        session.add(reply)
    session.commit()
    INITIAL_REPLIES = [deepcopy(reply.model_dump()) for reply in session.exec(select(DailyContactReply)).all()]


def preview_actor(request: Request):
    return StaffUser(role=Role.VIEW_ONLY if request.cookies.get('reply_preview_role') == 'read' else Role.ADMIN,
                     name=fixture.actor.name, user_id=fixture.actor.user_id)


app.dependency_overrides[get_current_staff_user] = preview_actor
env = fixture.daily_contacts.templates.env
loader = FileSystemLoader(SOURCE / 'templates')
base = loader.get_source(env, 'base.html')[0]
table = loader.get_source(env, 'daily_contacts/_content_table.html')[0]
detail = loader.get_source(env, 'daily_contacts/detail.html')[0]

# Only the proposed shortcut and its destination emphasis differ from the deployed UI.
table = re.sub(r'<span class="contact-reply-draft">([^<]+)</span>',
    r'{% if current_user.can_edit %}<a class="contact-reply-draft contact-reply-action" '
    r'href="/daily-contacts/{{ child.id }}?{{ detail_query_string }}#daily-reply-form" '
    r'aria-label="{{ child.full_name }} の返信を記入（\1）">\1</a>'
    r'{% else %}<span class="contact-reply-draft">\1</span>{% endif %}', table)
detail = detail.replace('action="/daily-contacts/{{ child.id }}/reply"',
                        'action="/preview/reply/{{ child.id }}"')
detail = detail.replace('<p>{{ child.full_name }} / {{ target_date_value }}</p>',
                        '<p>{{ child.full_name }} / {{ target_date_value }}</p><p>モック内で公開を再現します。保護者には送信されません。</p>')

controls = '''<div class="preview-controls" aria-label="モックの確認条件">
  <div><strong>確認用モック</strong> 架空データのみ・本番未反映 <span>「未送信」を押して返信欄へ移動</span></div>
  <nav aria-label="入力状態の切替">{% for key, label in preview_scenarios.items() %}
    <a href="/preview/scenario/{{ key }}?{{ preview_return_query(request) }}" {% if preview_scenario() == key %}aria-current="true"{% endif %}>{{ label }}</a>
  {% endfor %}
    <a href="/preview/role?{{ preview_return_query(request) }}">{{ '編集できる職員に戻す' if not current_user.can_edit else '閲覧のみの職員で確認' }}</a>
  </nav>
</div>'''
style = '''<style>
.preview-controls {background:#fffbeb;border-bottom:1px solid #fcd34d;padding:10px 20px;color:#78350f;font-size:13px;line-height:1.8}
.preview-controls strong {margin-right:10px}.preview-controls span {margin-left:16px}
.preview-controls nav {display:flex;gap:6px;flex-wrap:wrap;margin-top:5px}
.preview-controls a {padding:3px 10px;border:1px solid #e7cfaa;background:#fff;border-radius:5px}
.preview-controls a[aria-current] {background:#78350f;color:white}
.contact-reply-action {display:inline-flex;align-items:center;min-height:38px;padding:6px 10px;border:1px solid #d9a864;border-radius:6px;background:#fffbeb;line-height:1.5}
.contact-reply-action:hover {background:#fef3c7;border-color:#b45309;text-decoration:underline}
#daily-reply-form {scroll-margin-top:20px}
#daily-reply-form:target {border-color:#818cf8;box-shadow:0 0 0 2px #e0e7ff}
</style>'''
base = base.replace('</head>', style + '</head>')
base = base.replace('<body class="bg-slate-50 text-slate-800">',
                    '<body class="bg-slate-50 text-slate-800">' + controls)
env.loader = ChoiceLoader([DictLoader({'base.html': base,
    'daily_contacts/_content_table.html': table, 'daily_contacts/detail.html': detail}), loader])
env.cache.clear()
env.globals.update(preview_scenarios=SCENARIOS, preview_scenario=lambda: scenario,
    preview_return_query=lambda request: urlencode({'next': request.url.path + ('?' + request.url.query if request.url.query else '')}))


def return_url(request):
    target = request.query_params.get('next', '/daily-contacts/')
    return target if re.match(r'^/daily-contacts/(?:\d+(?:/history)?)?(?:\?|$)', target) else '/daily-contacts/'


@app.get('/')
def home():
    return RedirectResponse('/daily-contacts/?sort=unsent_first')


@app.get('/preview/role')
def change_role(request: Request):
    response = RedirectResponse(return_url(request))
    response.set_cookie('reply_preview_role', 'edit' if request.cookies.get('reply_preview_role') == 'read' else 'read', samesite='strict')
    return response


@app.get('/preview/scenario/{value}')
def change_scenario(value: str, request: Request):
    global scenario
    if value not in SCENARIOS:
        return JSONResponse({'detail': 'Unknown preview scenario'}, status_code=404)
    scenario = value
    with Session(fixture.engine) as session:
        for reply in session.exec(select(DailyContactReply)).all():
            session.delete(reply)
        session.flush()
        if value == 'mixed':
            session.add_all([DailyContactReply(**deepcopy(values)) for values in INITIAL_REPLIES])
        elif value != 'empty':
            for child in session.exec(select(Child)).all():
                values = {'nap_time': '12:30-14:00'}
                if value == 'filled':
                    values.update(temperature='36.7', bowel_movement='あり', appetite='完食')
                session.add(DailyContactReply(child_id=child.id, target_date=fixture.day, status='draft',
                    field_values=values, message='園庭で遊びました。' if value == 'filled' else '', staff_name=fixture.actor.name))
        session.commit()
    return RedirectResponse(return_url(request))


@app.post('/preview/reply/{child_id}')
async def mock_save(child_id: int, request: Request):
    """Update only the disposable fixture. No production save or send function is called."""
    if not preview_actor(request).can_edit:
        return JSONResponse({'detail': '閲覧のみのため保存できません。'}, status_code=403)
    if scenario == 'error':
        return JSONResponse({'detail': '確認用の保存エラーです。入力内容は残っています。'}, status_code=503)
    data = await request.form()
    target = date.fromisoformat(str(data['date']))
    action = data.get('action', 'draft')
    values = {name: str(data.get('reply_' + name, '')).strip()
              for name in ('nap_time', 'temperature', 'bowel_movement', 'appetite')}
    message = str(data.get('reply_message', '')).strip()
    with Session(fixture.engine) as session:
        reply = session.exec(select(DailyContactReply).where(DailyContactReply.child_id == child_id,
                            DailyContactReply.target_date == target)).first()
        if reply is None:
            reply = DailyContactReply(child_id=child_id, target_date=target)
        if reply.status == DailyContactReplyStatus.published and action == 'draft':
            reply.pending_draft = {'field_values': values, 'message': message, 'staff_name': fixture.actor.name}
        else:
            reply.field_values, reply.message, reply.staff_name = values, message, fixture.actor.name
            reply.pending_draft = None
            reply.status = DailyContactReplyStatus.published if action == 'publish' else DailyContactReplyStatus.draft
            reply.published_at = utc_now() if action == 'publish' else None
        reply.updated_at = utc_now()
        session.add(reply)
        session.commit()
        return {'revision': reply.updated_at.isoformat(),
                'status': '未送信の変更あり' if reply.pending_draft else '公開済み' if action == 'publish' else '未送信',
                'notice': 'モック内で公開しました（送信はしていません）。' if action == 'publish' else 'モック内に下書きを保存しました。'}


assert not any('POST' in (getattr(route, 'methods', set()) or set())
               and not route.path.startswith('/preview/') for route in app.routes)

if __name__ == '__main__':
    import uvicorn
    print(f'Reply shortcut mock: deployed baseline {BASELINE}; fictional in-memory data only.', flush=True)
    uvicorn.run(app, host='127.0.0.1', port=8908)
