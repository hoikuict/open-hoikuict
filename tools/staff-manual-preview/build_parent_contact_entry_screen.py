"""Render the daily-contact entry with its own numbered targets (SD-021)."""
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
setup = (HERE / 'build_parent_app_screens.py').read_text(encoding='utf-8').split("render('app-home','home'")[0]
context = {'__file__': str(HERE / 'build_parent_app_screens.py')}
exec(compile(setup, str(HERE / 'build_parent_app_screens.py'), 'exec'), context)
render = context['render']
names = context['names']
BASE = context['BASE']
render('app-contact-entry', 'home', [
    'input[name=date]',
    '#child-information h3',
    '#child-information a[href*="/contact?"]',
])
(HERE / 'parent-contact-entry-baseline.json').write_text(json.dumps({
    'source_commit': '285b67e7c0bec04afb40ac526626781182280779',
    'synthetic_data_only': True,
    'network_disabled': True,
    'business_records_written': 0,
    'screens': names,
    'source_files': {f: hashlib.sha256((BASE / f).read_bytes()).hexdigest()
                     for f in ['templates/base.html', 'templates/parent_portal/home.html']},
}, ensure_ascii=False, indent=2), encoding='utf-8')
print('Rendered daily-contact entry: date, child name, daily-contact button.')
