import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'.local-dev/document-search-rollout-20261108/source'
EVIDENCE=ROOT/'.local-dev/manual-batch2-20261123'
files=['templates/base.html','templates/portal/index.html','templates/portal/attention.html','templates/plan_docs/_review_notifications.html','static/js/child-progress.js','auth.py','models.py','plan_docs/routers/documents.py','test_child_progress_periods.py','routers/staff_portal.py','staff_portal_service.py','test_staff_portal.py','test_staff_attention_scope.py']
files += [p.relative_to(SOURCE).as_posix() for folder in ['child_records','templates/child_records'] for p in (SOURCE/folder).rglob('*') if p.suffix in ['.py','.html'] and '__pycache__' not in p.parts]
checks=[]
for relative in sorted(set(files)):
    current=(SOURCE/relative).read_bytes().replace(b'\r\n',b'\n')
    recorded=subprocess.check_output(['git','show','c255d24e17ce41136f7600a47368a026feaf4099:'+relative],cwd=SOURCE).replace(b'\r\n',b'\n')
    assert current==recorded,relative
    checks.append({'path':relative,'sha256':hashlib.sha256(current).hexdigest()})
(EVIDENCE/'baseline.json').write_text(json.dumps({'recorded_production':'c255d24e17ce41136f7600a47368a026feaf4099','files':checks,'live_production_read':False},ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps({'passed':True,'files':len(checks)}))
