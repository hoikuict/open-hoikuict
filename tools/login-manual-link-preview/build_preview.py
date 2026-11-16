"""Build a review-only login screen from the recorded production template."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
from jinja2 import Template

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).parent
BASE = ROOT / '.local-dev/backup-v2-rollout-20261101/source/templates/portal/login_prompt.html'
CURRENT = ROOT / 'templates/portal/login_prompt.html'
source = subprocess.check_output(['git','show','d75b28d2f14a5660922e51d9a177b2ce259de652:templates/portal/login_prompt.html'],cwd=BASE.parents[2],encoding='utf-8')
anchor = '      >ログインする</a>\n'
assert source.count(anchor) == 1
link = '''      <div class="mt-6">
        <a
          href="https://open.hoikuict.net/manual-guide-preview/"
          target="_blank"
          rel="noopener noreferrer"
          aria-describedby="manual-link-note"
          class="inline-flex min-h-12 items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-medium text-indigo-200 underline decoration-indigo-300/50 underline-offset-4 transition hover:text-white focus:outline-none focus:ring-4 focus:ring-indigo-300/50"
        >使い方マニュアル <span aria-hidden="true">↗</span></a>
        <p id="manual-link-note" class="mt-1 text-xs text-slate-400">別のタブで開きます</p>
      </div>
'''
candidate = source.replace(anchor, anchor + link)
assert CURRENT.read_text(encoding='utf-8') in (source,candidate), 'Unexpected application template changes.'
(HERE / 'candidate-login_prompt.html').write_text(candidate,encoding='utf-8')
dist = HERE / 'dist'
dist.mkdir(parents=True,exist_ok=True)
shutil.copyfile(ROOT / 'tools/staff-auth-print-preview/tailwind.js',dist/'tailwind.js')
html = Template(candidate).render(current_time='04:52',timezone_name='Asia/Tokyo')
html = html.replace('https://cdn.tailwindcss.com','tailwind.js')
html = html.replace('<title>職員ログイン | open-hoikuict</title>','<title>マニュアルへの入口・画面案 | open-hoikuict</title>')
html = html.replace('<body class="min-h-screen bg-slate-950 text-slate-100">', '''<body class="min-h-screen bg-slate-950 text-slate-100">
  <aside class="fixed left-4 top-4 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-xs text-slate-300">確認用モック · マニュアルへの入口</aside>''')
html = html.replace('href="/staff/login?redirect=/"','href="#login-sample" id="login-sample"')
html = html.replace('</main>', '''</main>
  <p id="mock-status" role="status" class="fixed bottom-4 left-5 right-5 text-center text-xs text-slate-400">確認用の画面です。ログイン操作は行いません。</p>
  <script>document.getElementById('login-sample').addEventListener('click',e=>{e.preventDefault();document.getElementById('mock-status').textContent='本番では職員ログイン画面へ進みます。このモックではログインしません。';});</script>''')
html = html.replace('<meta charset="UTF-8">', '<meta charset="UTF-8"><meta http-equiv="Content-Security-Policy" content="default-src \'self\'; script-src \'self\' \'unsafe-inline\' \'unsafe-eval\'; style-src \'self\' \'unsafe-inline\'; img-src \'self\' data:; connect-src \'none\'; form-action \'none\'; base-uri \'none\'">')
(dist/'index.html').write_text(html,encoding='utf-8')
evidence = {'id':'LOGIN-MANUAL-LINK-MOCK-001','date':'2026-11-03 JST',
            'baseline_record':'docs/deployment-billing-reopen-2026-11-01.md',
            'recorded_production_commit':'d75b28d2f14a5660922e51d9a177b2ce259de652',
            'source_template':str(BASE),'matches_workspace':source==CURRENT.read_text(encoding='utf-8'),
            'source_sha256':hashlib.sha256(source.encode()).hexdigest(),
            'candidate_sha256':hashlib.sha256(candidate.encode()).hexdigest(),
            'mock_sha256':hashlib.sha256(html.encode()).hexdigest(),
            'manual_url':'https://open.hoikuict.net/manual-guide-preview/',
            'application_template_modified_by_this_script':False,
            'approved_deployment_record':'docs/deployment-login-manual-link-2026-11-03.md'}
# Keep the original approval evidence unchanged when regenerating the archived mock.
(HERE/'regenerated-preview.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print('Rebuilt the approved review mock; the application template was not changed by this script.')
