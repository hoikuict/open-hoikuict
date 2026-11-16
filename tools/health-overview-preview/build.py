"""Build an offline mock from the recorded deployment, without app/DB imports."""
from datetime import date
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from jinja2 import DictLoader, Environment, select_autoescape
from lxml import html

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / '.local-dev/document-search-rollout-20261108/source'
REV = '67f4d728c51d67a6c6c1da38ea8f10b6f4186b8f'
PATH = 'templates/health/overview.html'
original = subprocess.check_output(['git', '-C', str(SOURCE), 'show', f'{REV}:{PATH}']).decode('utf-8')
env = Environment(loader=DictLoader({'overview': original, 'base.html': '{% block content %}{% endblock %}'}), autoescape=select_autoescape(default=True))
names = ['青空 はる', '若葉 そう', '花野 めい', '小川 りく', '星見 ひなた', '森野 あおい', '朝日 ゆう', '野原 なお', '水野 さき', '風見 そら', '月野 あかり', '山吹 けい', '白石 れん', '春野 こと', '夏目 いと', '秋山 まお', '冬木 あん', '虹野 つむぎ']
classrooms = [dict(id=1, name='ひよこ'), dict(id=2, name='りす'), dict(id=3, name='うさぎ')]

def rows_for(scenario):
    rows = []
    for i, name in enumerate(names):
        allergies = ['卵'] if i == 5 else (['牛乳', '小麦', '魚卵（たらこ・いくらなど、加工食品に含まれる場合も確認）', 'えび', 'かに'] if i == 13 else [])
        labels = {1:['肘内障'], 4:['健診要確認'], 5:['アレルギー'], 10:['熱性けいれん', '与薬'], 13:['アレルギー', 'エピペン', 'アレルギー期限切れ']}.get(i, [])
        height, weight = round(73.4+i*1.5,1), round(9.1+i*.4,1)
        stale = i == 4
        if stale or scenario == 'empty':
            height = weight = None
            stale = True
        elif scenario == 'partial' and i % 2 == 0:
            weight = None
        if scenario == 'empty':
            labels, allergies = ['健診要確認'], []
        rows.append(dict(child=dict(id=i+1, full_name=name, family=dict(family_name=name.split()[0]+'家'), classroom=classrooms[min(i//6,2)]), profile={},
            attention_labels=labels, allergies=[dict(allergen_name=a) for a in allergies], active_allergy_count=len(allergies), expired_allergy_count=1 if i==13 and scenario!='empty' else 0,
            latest_height=dict(value=height,date=date(2026,11,15) if height is not None else None), latest_weight=dict(value=weight,date=date(2026,11,15) if weight is not None else None), health_check_stale=stale,
            medical_waiting=i==10, status='graduated' if i==16 else 'withdrawn' if i==17 else 'enrolled', priority=i in (1,10,13)))
    return rows

templates = []
for scenario in ['filled', 'empty', 'partial']:
    rows = rows_for(scenario)
    markup = env.get_template('overview').render(rows=rows, summary=dict(children_count=18,attention_count=6,priority_management_count=3,expired_allergy_children_count=1), classrooms=classrooms, current_status='enrolled',current_attention='all',current_classroom_id=None,current_query='')
    doc = html.fromstring(markup)
    table = doc.xpath('.//table')[0]
    table.set('class',table.get('class')+' health-table')
    colgroup = html.fragment_fromstring('<colgroup>'+''.join('<col>' for _ in range(7))+'</colgroup>')
    table.insert(0,colgroup)
    scroll = table.getparent()
    scroll.set('class',scroll.get('class')+' health-scroll')
    scroll.set('tabindex','0')
    scroll.set('role','region')
    scroll.set('aria-label','園児の健康情報と操作の一覧')
    for th in table.xpath('.//th'):
        th.set('scope','col')
    for tr, row in zip(table.xpath('.//tbody/tr'),rows):
        for cell, label in zip(tr.xpath('./td'), ['園児','クラス','健康フラグ','アレルギー','最新測定','健診状態','操作']):
            cell.set('data-label', label)
        for key,value in dict(status=row['status'],attention=bool(row['attention_labels']),classroom=row['child']['classroom']['id'],priority=row['priority'],expired=bool(row['expired_allergy_count'])).items():
            tr.set('data-'+key,str(value).lower())
    cards = doc.xpath('./section')[0]
    for i, element in enumerate(cards.xpath('./div/p[2]')):
        element.set('data-count',str(i))
    form = doc.xpath('.//form')[0]
    form.set('action','#')
    form.set('id','health-filters')
    form.attrib.pop('method',None)
    for element in form.xpath('.//input|.//select'):
        element.set('id','filter-'+element.get('name'))
    for link in doc.xpath('.//a'):
        route = link.get('href')
        link.set('data-original-route',route)
        link.set('href','#preview-detail')
    table.getparent().getparent().addprevious(html.fragment_fromstring('<p class="scroll-hint">現行の配置は、横にスクロールして操作欄を確認できます。</p>'))
    templates.append(f'<template id="scenario-{scenario}">'+html.tostring(doc,encoding='unicode')+'</template>')

shell = '''<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'none'; form-action 'none'; base-uri 'none'">
<title>健康管理一覧・余白の見直し r2（モック）</title><script src="tailwind.js"></script><link rel="stylesheet" href="preview.css?v=r2"></head>
<body><aside class="preview-controls" aria-label="モックの確認用操作"><div class="preview-heading"><strong>健康管理一覧 · レイアウト確認 r2</strong><span>架空データのモック／本番への保存・送信なし</span></div>
<div class="preview-options"><div class="view-toggle" role="group" aria-label="レイアウト"><button type="button" data-layout="proposed" aria-pressed="true">変更案</button><button type="button" data-layout="current" aria-pressed="false">現行の配置</button></div>
<label>見本の状態 <select id="scenario"><option value="filled">入力済み（長文・複数項目あり）</option><option value="empty">未入力（測定・アレルギー未登録）</option><option value="partial">一部入力（身長のみを含む）</option><option value="error">読み込みエラー</option></select></label><a href="#list-anchor" id="jump-list">一覧へ移動</a></div>
<p id="layout-note">操作欄まで画面幅に収め、狭い画面では園児ごとに全項目と操作をまとめて表示します。</p></aside>
<main id="business-screen" class="proposed"></main>
<div id="load-error" hidden role="alert"><h1>一覧を読み込めませんでした</h1><p>これは確認用のエラー表示です。再読み込みで架空データの一覧へ戻ります。</p><button type="button" id="retry">再読み込み</button></div>
<dialog id="preview-detail" aria-labelledby="detail-title"><div class="detail-header"><h2 id="detail-title"></h2><button type="button" id="close-detail">閉じる</button></div><p class="detail-note">遷移先の確認用です。このモックでは編集・登録は行いません。</p><div id="detail-content"></div><p id="detail-route"></p></dialog>
TEMPLATES<script src="preview.js?v=r2"></script></body></html>'''
(HERE/'index.html').write_text(shell.replace('TEMPLATES','\n'.join(templates)),encoding='utf-8')
shutil.copyfile(ROOT/'tools/staff-manual-preview/dist/assets/tailwind.js',HERE/'tailwind.js')
(HERE/'baseline.json').write_text(json.dumps(dict(revision=REV,source=PATH,source_sha256=hashlib.sha256(original.encode()).hexdigest(),generated_sha256=hashlib.sha256((HERE/'index.html').read_bytes()).hexdigest(),source_kind='latest deployment record and saved Git source; live production not accessed',input_names=['status','attention','classroom_id','q'],columns=7,fictional_rows=18),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Built offline health overview r2 from '+REV)
