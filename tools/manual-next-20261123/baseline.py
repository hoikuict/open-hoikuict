"""Record the exact deployed-source comparison and existing screenshot inventory."""
from pathlib import Path
import hashlib
import json
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '.local-dev/document-search-rollout-20261108/source'
OUT = ROOT / '.local-dev/manual-next-20261123'
COMMIT = 'c255d24e17ce41136f7600a47368a026feaf4099'
paths = ['auth.py', 'models.py', 'family_emergency.py', 'attendance_checks_service.py',
         'attendance_correction_service.py', 'attendance_monthly_service.py', 'test_parent_portal.py',
         'routers/attendance.py', 'routers/attendance_monthly.py', 'routers/attendance_checks.py',
         'routers/children.py', 'routers/parent_portal.py', 'templates/base.html',
         'templates/attendance_monthly.html', 'templates/attendance_correction.html',
         'templates/attendance_list.html', 'templates/children/detail.html', 'templates/children/emergency_oral.html',
         'templates/parent_portal/emergency.html', 'templates/parent_portal/_emergency_editor.html',
         'templates/parent_portal/_daily_emergency.html', 'templates/shared/_emergency_order.html',
         'static/js/attendance-monthly.js', 'static/js/attendance-checks.js', 'static/js/family-emergency.js',
         'static/css/attendance-monthly.css', 'static/css/attendance-compact.css']
paths += [p.relative_to(SOURCE).as_posix() for p in (SOURCE / 'templates/attendance_checks').glob('*.html')]
records = []
for path in paths:
    deployed = subprocess.check_output(['git', '-C', str(SOURCE), 'show', COMMIT + ':' + path]).replace(b'\r\n', b'\n')
    local = (SOURCE / path).read_bytes().replace(b'\r\n', b'\n')
    records.append(dict(path=path, matches=deployed == local, sha256=hashlib.sha256(local).hexdigest()))
assert all(row['matches'] for row in records), [x for x in records if not x['matches']]
data = dict(source=str(SOURCE), recorded_production_commit=COMMIT,
            checkout_head=subprocess.check_output(['git', '-C', str(SOURCE), 'rev-parse', 'HEAD'], text=True).strip(),
            comparisons=records, production_live_rechecked=False)
(OUT / 'baseline.json').write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
js = (ROOT / 'docs/manual-guide-preview/app.js').read_text(encoding='utf-8')
start = js.index('const manualArticles = ') + len('const manualArticles = ')
end = js.index('\n};', start) + 2
node = 'C:/Program Files/WindowsApps/OpenAI.CodexPrimaryRuntime.v26-1119-907-0_26.1119.907.0_x64__3k8sg7r9htsxt/dependencies/node/bin/node.exe'
articles = json.loads(subprocess.check_output([node, '-e', "const vm=require('vm'),fs=require('fs');process.stdout.write(JSON.stringify(vm.runInNewContext('('+fs.readFileSync(0,'utf8')+')')));"], input=js[start:end].encode()))
inventory = [{'id': key, 'title': row['title'], 'steps': len(row.get('steps', []))} for key, row in articles.items()]
(OUT / 'existing-articles.json').write_text(json.dumps(inventory, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps({'matched_source_files': len(records), 'existing_articles': len(inventory)}))
