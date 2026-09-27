"""Render the deployed parent UI with fictional data; never import the app or DB."""
from datetime import datetime, timezone, timedelta
import hashlib
import json
from pathlib import Path
import re
import subprocess

from jinja2 import Environment, FileSystemLoader, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/truenas-desktop-20260925/source'
COMMIT = 'c907275b94cabcb613b4cf2a8edf778c05ade8dd'
JST = timezone(timedelta(hours=9))
FILES = ['templates/base.html', 'templates/parent_portal/home.html',
         'templates/parent_portal/_update_card.html', 'templates/parent_portal/notices.html',
         'templates/parent_portal/notice_detail.html', 'templates/parent_portal/notification_detail.html',
         'routers/parent_portal.py']


def git(*args):
    return subprocess.check_output(['git', '-C', str(SOURCE), *args])


assert git('rev-parse', 'HEAD').decode().strip() == COMMIT
hashes = {}
for name in FILES:
    content = (SOURCE / name).read_bytes().replace(b'\r\n', b'\n')
    assert content == git('show', f'HEAD:{name}').replace(b'\r\n', b'\n'), name
    hashes[name] = hashlib.sha256(content).hexdigest()

env = Environment(loader=FileSystemLoader(SOURCE / 'templates'), autoescape=select_autoescape())
env.filters['jst_datetime'] = lambda value, fmt='%Y-%m-%d %H:%M': value.astimezone(JST).strftime(fmt) if value else ''


def date(value):
    return datetime.fromisoformat(value + '+09:00')


children = [{'id': 1, 'full_name': '青葉 はる（架空）', 'classroom': {'name': 'くるみ'}},
            {'id': 2, 'full_name': '青葉 そら（架空）', 'classroom': {'name': 'さくら'}}]
context = dict(parent_portal_mode=True, current_parent_user={'display_name': '青葉 保護者（架空）', 'child_links': [1, 2]},
               target_date_value='2026-09-27', children=children, entry_by_child_id={}, reply_by_child_id={},
               reply_display_by_child_id={}, pending_request_by_child_id={}, latest_updates=[],
               recent_replies=[], unread_notice_count=0, flash_notice='')


def render(name, **values):
    return env.get_template('parent_portal/' + name + '.html').render(**(context | values))


def main_content(page):
    return re.search(r'<main\b[^>]*>(.*?)</main>', page, re.S).group(1)


# Include newer ordinary notices and older attendance messages on both sides of read status.
items = [
    dict(id='n1', kind='notice', title='明日の持ち物について', at='2026-09-27T12:00', read=False, important=False,
         body='明日は水筒と帽子をお持ちください。これは並び順を確認する架空のお知らせです。'),
    dict(id='n2', kind='notice', title='10月の園だよりを公開しました', at='2026-09-27T11:00', read=True, important=False,
         body='10月の行事予定をご確認ください。内容・日時はすべて架空です。'),
    dict(id='a1', kind='parent_notification', title='本日の出欠をご連絡ください', at='2026-09-27T09:00', read=False, important=True,
         body='本日の連絡をいただいておりません。出席か欠席かお知らせください。（架空）'),
    dict(id='n3', kind='notice', title='運動会の集合時刻について', at='2026-09-26T16:00', read=False, important=True,
         body='集合時刻は9時です。並び順を確認するための架空データです。'),
    dict(id='a2', kind='parent_notification', title='9月25日の出欠確認', at='2026-09-25T09:00', read=True, important=True,
         body='9月25日の出欠をご確認ください。（架空）'),
    dict(id='n4', kind='notice', title='園庭あそびの様子', at='2026-09-24T15:00', read=True, important=False,
         body='今日は園庭で元気に遊びました。こちらも架空のお知らせです。'),
]
pages = {}
for scenario in ('empty', 'partial', 'filled'):
    entry = dict(is_present_contact=True, contact_type={'label': '出席', 'value': 'present'},
                 temperature='36.5', mood='よい', breakfast_status='完食')
    entries = {} if scenario == 'empty' else {1: entry} if scenario == 'partial' else {1: entry, 2: entry}
    replies = {} if scenario == 'empty' else {1: dict(staff_name='担任（架空）', published_at=date('2026-09-27T13:00'),
                                                       message='今日はお友だちと積み木で遊びました。（架空）')}
    recent = [] if not replies else [dict(child_id=1, target_date=date('2026-09-27T00:00').date(),
                                        child=children[0], published_at=date('2026-09-27T13:00'))]
    home = main_content(render('home', entry_by_child_id=entries, reply_by_child_id=replies, recent_replies=recent))
    home = home.replace('<section>\n    <div class="mb-3', '<section id="notice-section">\n    <div class="mb-3', 1)
    pages[scenario] = home

pages['notices'] = main_content(render('notices', notices=[], parent_notifications=[], read_notice_ids=set()))
for item in items:
    when = date(item['at'])
    item['url'] = '/parent-portal/' + ('notices/' if item['kind'] == 'notice' else 'notifications/') + item['id']
    item['cards'] = {}
    for read in (False, True):
        notice = dict(id=item['id'], title=item['title'], created_at=when, publish_start_at=None,
                      priority={'value': 'high' if item['important'] else 'normal'}, attachments=[], body=item['body'])
        notification = dict(id=item['id'], title=item['title'], created_at=when, is_read=read, body=item['body'], action_url='')
        output = main_content(render('notices', notices=[notice] if item['kind'] == 'notice' else [],
                                    parent_notifications=[notification] if item['kind'] != 'notice' else [],
                                    read_notice_ids={item['id']} if read else set()))
        card = re.search(r'<div class="space-y-4">\s*(.*?)\s*</div>\s*$', output, re.S).group(1)
        update = dict(kind=item['kind'], title=item['title'], url=item['url'], is_unread=not read,
                      is_important=item['important'], published_at_label=when.strftime('%Y-%m-%d %H:%M'),
                      closes_at_label=None, summary=item['body'] if item['kind'] != 'notice' else None)
        home_card = env.get_template('parent_portal/_update_card.html').render(update=update)
        item['cards'][str(read).lower()] = dict(list=card, home=home_card)
    item['detail'] = main_content(render('notice_detail', notice=notice, notice_body_html=item['body']) if item['kind'] == 'notice'
                                   else render('notification_detail', notification=notification, child=children[0]))

shell = render('home')
shell = re.sub(r'<script\b[^>]*>.*?</script>', '', shell, flags=re.S)
shell = re.sub(r'<main\b[^>]*>.*?</main>', '<main class="mx-auto max-w-7xl px-4 py-6 sm:px-6" id="screen"></main>', shell, flags=re.S)
shell = shell.replace('<title>保護者ホーム | open-hoikuict</title>', '<title>お知らせの並び順・確認用モック</title>')
shell = shell.replace('</head>', '''
<meta http-equiv="Content-Security-Policy" content="default-src 'self'; script-src 'self' https://cdn.tailwindcss.com 'unsafe-eval'; style-src 'self' 'unsafe-inline'; connect-src 'none'; form-action 'none'; object-src 'none'; base-uri 'none'">
<script src="https://cdn.tailwindcss.com"></script>
<link rel="stylesheet" href="review.css">
<script src="data.js" defer></script><script src="preview.js" defer></script>
</head>''')
controls = '''
<aside class="review" aria-label="確認用モックの設定">
  <div class="review-title"><strong>お知らせの並び順・確認用モック</strong><span>架空データ ／ 本番未反映</span></div>
  <div class="review-controls">
    <label>画面<select id="page"><option value="notices">お知らせ一覧</option><option value="home">保護者ホーム</option></select></label>
    <label>並び順<select id="order"><option value="proposal">変更案</option><option value="current">現行配備版</option></select></label>
    <label>先に表示する状態<select id="priority" disabled><option value="unread">未読を上にする（確認済み）</option></select></label>
    <label>お知らせの状態<select id="state"><option value="partial">一部既読</option><option value="empty">すべて未読</option><option value="filled">すべて既読</option><option value="none">お知らせなし</option></select></label>
    <label>日次連絡の状態<select id="contact"><option value="partial">一部入力</option><option value="empty">未入力</option><option value="filled">入力済み</option></select></label>
    <label class="review-check"><input type="checkbox" id="error">次に開くとエラー</label>
    <button id="reset">初期状態に戻す</button>
  </div>
  <p id="order-note" aria-live="polite"></p>
  <details><summary>今回の確認範囲</summary><p>未読を先に表示し、未読・既読それぞれの中で、出欠確認と通常のお知らせを新しい日時順にまとめます。重要マークは残します。未読優先はユーザー確認済みです。ホーム・一覧の両画面で変更案を試せます。</p><p>詳細を開くとこのモック内だけで既読になり、戻った際に並べ直します。日付の変更も試せます。ほかの業務画面・アンケートの回答は今回のモックの対象外です。再読み込みで初期化します。</p><p>基準：2026年9月27日の配備記録 c907275b94ca。ホームの入力・連絡状況・返信・メニューは配備テンプレートから再現しています。</p></details>
</aside>
'''
shell = re.sub(r'(<body\b[^>]*>)', lambda match: match[1] + controls, shell, count=1)
shell = shell.replace('</body>', '<div id="feedback" role="status" hidden></div></body>')
(HERE / 'index.html').write_text(shell, encoding='utf-8')
(HERE / 'data.js').write_text('window.PREVIEW_DATA = ' + json.dumps(dict(items=items, pages=pages), ensure_ascii=False) + ';\n', encoding='utf-8')
(HERE / 'baseline.json').write_text(json.dumps(dict(commit=COMMIT, normalized_sha256=hashes), indent=2), encoding='utf-8')
print('Rendered deployed templates with 6 fictional notices and 3 contact scenarios.')
