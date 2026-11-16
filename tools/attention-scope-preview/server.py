"""Read-only preview of the deployed portal, using only fictional Python data.

No application imports, database connections, POST handlers, or outbound requests.
"""
from datetime import date, datetime
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs, urlencode, urlsplit

from jinja2 import DictLoader, Environment, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/truenas-monthly-export-20260927/source'
COMMIT = '4581393839d40d0e4eddbf71b9b4b28a7ba461ea'
FILES = ['templates/base.html', 'templates/portal/index.html',
         'templates/portal/attention.html', 'templates/portal/_returned_documents.html',
         'templates/guardian/_monitor_alert.html', 'routers/staff_portal.py',
         'staff_portal_service.py']
sources, hashes = {}, {}
for name in FILES:
    raw = subprocess.check_output(['git', '-C', str(SOURCE), 'show', f'{COMMIT}:{name}'])
    raw = raw.replace(b'\r\n', b'\n')
    hashes[name] = hashlib.sha256(raw).hexdigest()
    if name.startswith('templates/'):
        sources[name.removeprefix('templates/')] = raw.decode('utf-8')

# Keep the deployed layout; remove active application scripts and polling.
base = re.sub(r'<script\b[^>]*>.*?</script>', '', sources['base.html'], flags=re.S)
base = base.replace('</head>', '''
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' 'unsafe-inline' 'unsafe-eval' https://cdn.tailwindcss.com; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'self'; object-src 'none'; base-uri 'none'">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="/review.css">
</head>''')
base = re.sub(r'(<body\b[^>]*>)', r'\1{% include "review.html" %}', base, count=1)
base = base.replace('</body>', '<script src="/preview.js"></script></body>')
sources['base.html'] = base
sources['review.html'] = (HERE / 'review.html').read_text(encoding='utf-8')
env = Environment(loader=DictLoader(sources), autoescape=select_autoescape())
env.filters['jst_datetime'] = lambda value, fmt='%m-%d %H:%M': value.strftime(fmt)

OPTIONS = dict(mode=('proposal', 'current'), role=('admin', 'can_edit'),
               policy=('assigned',), criterion=('unknown',),
               state=('empty', 'partial', 'filled', 'error'), assigned=('6', '4', '3', '0'),
               scope=('assigned', 'all'), page=('home', 'attention'), detail=('default', 'assigned', 'all'))
CLASSES = [('ひよこ', 7), ('うさぎ', 15), ('こあら', 20), ('りす', 20), ('きりん', 17), ('ぞう', 19)]
TODAY = date(2026, 9, 28)


def parameters(query):
    raw = parse_qs(query)
    return {key: raw.get(key, [values[0]])[0] if raw.get(key, [values[0]])[0] in values else values[0]
            for key, values in OPTIONS.items()}


def render(query=''):
    p = parameters(query)
    admin, proposal = p['role'] == 'admin', p['mode'] == 'proposal'
    assigned = int(p['assigned'])
    show_all = p['scope'] == 'all' or admin and assigned == 0
    summaries, all_items = [], []
    for i, (name, count) in enumerate(CLASSES):
        confirmed = 0 if p['state'] in ('empty', 'error') else count if p['state'] == 'filled' else count - 2
        alarm_count = int(p['state'] == 'partial' and i in (0, 3, 5))
        unknown = count - confirmed
        items = []
        for child in range(count):
            is_unknown, alarm = child >= confirmed, bool(alarm_count and child == 0)
            if alarm or (is_unknown and (not proposal or p['criterion'] == 'unknown')):
                items.append(dict(kind='attendance', kind_label='出欠', title=f'{name} 園児{child + 1:02d}（架空）',
                                  detail='出欠アラーム（架空）' if alarm else '出欠確認が未入力です',
                                  severity='high' if alarm else 'normal', url='/preview-outside'))
        all_items.append(items)
        summaries.append(dict(classroom_name=name, classroom_id=i + 1, enrolled_count=count,
                              checked_in_count=confirmed, present_count=confirmed, checked_out_count=0,
                              absent_count=0, not_checked_in_count=unknown, attention_count=unknown + alarm_count,
                              alarm_count=alarm_count, missing_punch_count=0, attendance_url='/preview-outside'))
    visible = list(range(6)) if show_all else list(range(min(assigned, 3)))
    if proposal:
        attention_all = False
        attention_classes = list(range(6 if attention_all else assigned))
    else:
        attention_all = show_all and admin
        attention_classes = visible
    if p['page'] == 'attention':
        if p['detail'] != 'default':
            attention_all = admin and (p['detail'] == 'all' or (not proposal and assigned == 0))
        elif not proposal:
            attention_all = admin and (show_all or assigned == 0)
        attention_classes = list(range(6 if attention_all else assigned))
    items = [item for index in attention_classes for item in all_items[index]]
    surveys = [] if p['state'] != 'partial' else [dict(kind='survey', kind_label='アンケート',
        title='研修希望アンケート（架空）', detail='本人宛ての未回答アンケートです。', severity='normal', url='/preview-outside')]
    error = p['state'] == 'error'
    attention_count = '取得不可' if error and proposal else 0 if error else len(items) + len(surveys)
    range_label = '全クラス' if attention_all else '担当する全クラス'
    times = [dict(time_label='終日', title=title, calendar_name='こもれび保育園（架空）',
                  calendar_color='#059669', state='current', location='')
             for title in ('園庭の点検', '職員研修', '保育補助', '絵本の入れ替え', '行事準備')]
    times.append(dict(time_label='09:50', title='うさぎ組 散歩', calendar_name='こもれび保育園（架空）',
                      calendar_color='#059669', state='upcoming', location=''))
    context = dict(
        request=SimpleNamespace(url=SimpleNamespace(path='/' if p['page'] == 'home' else '/staff/attention'), state=SimpleNamespace()),
        current_user=dict(is_admin=admin, staff_id=1, name='確認用職員', role_label='管理者' if admin else '職員', can_manage_child_records=admin),
        staff_record=dict(display_name='確認用職員', staff_role=p['role'], calendar_role_label='管理者' if admin else '職員'),
        greeting='おはようございます', portal_date='2026年9月28日（月）', target_date=TODAY, updated_time='09:35',
        assignment_names=[name for name, _ in CLASSES[:min(assigned, 3)]], assignment_remaining_count=max(0, assigned - 3),
        terminal_alerts=[], returned_documents=[], returned_document_count=0, returned_review_error='',
        approval_queue_count=2, approval_queue_errors=[], approval_queue_items=[
            dict(kind='plan', kind_label='月案', title='2026-09 月案（ひよこ・架空）', requester_name='職員A', requested_at=datetime(2026, 9, 28, 6, 28), url='/preview-outside'),
            dict(kind='plan', kind_label='児童票', title='園児01 児童票（架空）', requester_name='職員B', requested_at=datetime(2026, 9, 25, 8, 6), url='/preview-outside')],
        plan_notifications=[], plan_notification_error='', unread_plan_notification_count=0,
        attendance_summaries=[] if error else [summaries[i] for i in visible], classroom_remaining_count=max(0, assigned - len(visible)),
        attendance_error='出席情報を取得できませんでした。再読み込みしてください。' if error else '',
        present_count=sum(summaries[i]['present_count'] for i in visible),
        show_all=show_all if p['page'] == 'home' else attention_all, can_show_all=p['page'] == 'home' or admin,
        schedule_items=times, next_schedule=times[-1], schedule_remaining_count=0, schedule_error='',
        timeline_messages=[dict(id=1, author_name='職員A（架空）', created_at=datetime(2026, 9, 28, 8, 0), display_body='明日の活動について共有します。'),
                           dict(id=2, author_name='職員B（架空）', created_at=datetime(2026, 9, 27, 15, 0), display_body='園内研修の予定を確認してください。')], timeline_error='',
        attention_count=attention_count, attention_error='要確認情報を取得できませんでした。再読み込みしてください。' if error else '',
        attention_url='/staff/attention?scope=all' if attention_all else '/staff/attention',
        attention_items=[] if error else items + surveys, attendance_attention_count=0 if error else len(items),
        survey_attention_count=0 if error else len(surveys),
        p=p, range_label=range_label, proposal=proposal,
    )
    page = env.get_template('portal/index.html' if p['page'] == 'home' else 'portal/attention.html').render(**context)
    if proposal:
        note = f'<p class="mt-2 text-xs text-slate-500">集計対象：{range_label}の出欠・本人宛ての未回答アンケート</p>'
        page = page.replace('<h2 class="mt-1 text-xl font-bold text-slate-900">要確認</h2>', '<h2 class="mt-1 text-xl font-bold text-slate-900">要確認</h2>' + note)
        page = page.replace('担当クラスの出欠と、本人宛ての未回答アンケートを一覧にしています。', f'{range_label}の出欠と、本人宛ての未回答アンケートを一覧にしています。')
        page = page.replace('取得不可件', '取得不可')
    page = re.sub(r'\s+hx-[\w-]+="[^"]*"', '', page)
    # Every link stays within this fixture. No business form can be submitted.
    def rewrite(match):
        url = match[1]
        if url.startswith('#'):
            return match[0]
        target = urlsplit(url)
        target_params = parse_qs(target.query)
        next_p = dict(p)
        if target.path in ('/', '/staff/portal'):
            next_p['page'] = 'home'
            next_p['detail'] = 'default'
            if 'scope' in target_params:
                next_p['scope'] = target_params['scope'][0]
        elif target.path == '/staff/attention':
            next_p['page'] = 'attention'
            next_p['detail'] = target_params.get('scope', ['assigned'])[0] if p['page'] == 'attention' else 'default'
        else:
            return 'href="#preview-outside" data-preview-outside="true"'
        return 'href="/?' + urlencode(next_p).replace('&', '&amp;') + '"'
    # CSS must keep its own URL.
    page = re.sub(r'<a\b[^>]*>', lambda m: re.sub(r'href="([^"]*)"', rewrite, m[0]), page)
    page = re.sub(r'<form\b(?![^>]*id="review-controls")[^>]*>.*?</form>', '', page, flags=re.S)
    return page


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = urlsplit(self.path)
        if path.path in ('/review.css', '/preview.js'):
            data = (HERE / path.path[1:]).read_bytes()
            content_type = 'text/css' if path.path.endswith('css') else 'text/javascript'
        elif path.path == '/':
            data, content_type = render(path.query).encode('utf-8'), 'text/html'
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header('Content-Type', content_type + '; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == '__main__':
    (HERE / 'baseline.json').write_text(json.dumps(dict(commit=COMMIT, normalized_sha256=hashes), indent=2) + '\n', encoding='utf-8')
    ThreadingHTTPServer.allow_reuse_address = False
    server = ThreadingHTTPServer(('127.0.0.1', 8924), Handler)
    print('Fictional preview: http://127.0.0.1:8924/ (GET only; no database)', flush=True)
    server.serve_forever()
