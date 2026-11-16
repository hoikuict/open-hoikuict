"""Keep the existing seven sections and 33 manual topics available in the mock."""
from pathlib import Path
import json
import re

root = Path(__file__).resolve().parents[2]
chapters = []
descriptions = ['登録からログインまで、使い始める準備をする。', '朝の出欠、保護者の連絡、登園・降園を確かめる。', '園児と家庭の情報、健康や育ちの記録を残す。', '年・月・週・日の計画を順番に確認する。', '予定、議事録、確認してほしい文書を共有する。', '認定から延長料金、月末の請求まで確認する。', '日々の点検、バックアップ、困ったときの対応。']
for line in root.joinpath('docs/manual-index.md').read_text(encoding='utf-8').splitlines():
    if line.startswith('## '):
        if len(chapters) == 7:
            break
        chapters.append({'name': line[3:], 'description': descriptions[len(chapters)], 'topics': []})
    match = re.match(r'\| \[([^]]+)\]\(([^)]+)\) \| (.+?) \| (.+?) \|', line)
    if match and chapters:
        title, link, role, kind = match.groups()
        if link.startswith('manual-guide-preview/'):
            continue  # Illustrated guides have their own cards in the manual.
        path, _, anchor = link.partition('#')
        public = 'https://open.hoikuict.net/' + path.removesuffix('.md') + '/' + ('#' + anchor if anchor else '')
        chapters[-1]['topics'].append(dict(title=title,url=public,role=role,kind=kind,source=link))
assert len(chapters) == 7
assert sum(len(c['topics']) for c in chapters) == 33
root.joinpath('tools/staff-manual-preview/dist/catalog.js').write_text('const manualChapters = '+json.dumps(chapters, ensure_ascii=False,indent=2)+';\n',encoding='utf-8')
print('Catalog: 7 chapters / 33 existing topics')
