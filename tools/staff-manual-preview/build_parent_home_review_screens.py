"""Focused, individually annotated views for SD-020. No app or DB imports."""
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
# Reuse only the environment/context setup, before the original fixture renders.
setup=(HERE/'build_parent_app_screens.py').read_text(encoding='utf-8').split("render('app-home','home'")[0]
context = {'__file__': str(HERE / 'build_parent_app_screens.py')}
exec(compile(setup, str(HERE / 'build_parent_app_screens.py'), 'exec'), context)
render = context['render']
updates = context['updates']
names = context['names']
BASE = context['BASE']
render('app-home-date','home',['main h1','input[name=date]','main form button[type=submit]'])
render('app-home-child','home',['#child-information h3','#child-information a[href*="/contact?"]','#child-information a[href*="/pickup?"]'],script='document.body.style.paddingBottom="900px";document.querySelector("#child-information").scrollIntoView();window.scrollBy(0,-30);')
render('app-home-unread','home',['a[href="/parent-portal/attention"]'],script='document.body.style.paddingBottom="900px";document.querySelector("a[href=\\"/parent-portal/attention\\"]").scrollIntoView();window.scrollBy(0,-40);')
render('app-home-updates','attention',['section a[href="/parent-portal/notices/9301"]','section a[href="/parent-portal/surveys/9401"]'],updates=updates)
render('app-home-menu','home',['nav summary','nav details > div'],script='document.querySelector("nav details").open=true;')
evidence=dict(source_commit='285b67e7c0bec04afb40ac526626781182280779',synthetic_data_only=True,network_disabled=True,business_records_written=0,screens=names,source_files={f:hashlib.sha256((BASE/f).read_bytes()).hexdigest() for f in ['templates/base.html','templates/parent_portal/home.html','templates/parent_portal/attention.html','templates/parent_portal/_update_card.html']})
(HERE/'parent-home-review-baseline.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding='utf-8')
print('Rendered 5 focused views of the existing parent home.')
