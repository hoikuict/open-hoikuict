"""Build a disconnected daily-plan mock from the recorded deployed source."""
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
from types import SimpleNamespace

from jinja2 import DictLoader, Environment, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT / ".local-dev/document-search-rollout-20261108/source"
COMMIT = "b6bc359740e2e070e359151a7ff0ac4dc1c1a3a6"
FORM = "templates/plan_docs/daily_plans/form.html"
AUDIT_FILES = [FORM, "templates/base.html", "plan_docs/routers/plans.py", "static/js/daily-example-search.js",
               "templates/plan_docs/weekly_library/sheet.html", "templates/plan_docs/annual_library/_sheet.html",
               "templates/plan_docs/monthly_library/_sheet.html", "templates/plan_docs/documents/detail.html",
               "templates/plan_docs/documents/edit.html", "templates/plan_docs/reflections/review.html",
               "templates/plan_docs/bunrei/facility_new.html", "templates/plan_docs/weekly_plans/form.html",
               "plan_docs/routers/annual_library.py", "plan_docs/routers/monthly_library.py",
               "plan_docs/routers/weekly_library.py", "plan_docs/routers/documents.py",
               "plan_docs/routers/reflections.py", "plan_docs/routers/bunrei.py",
               "plan_docs/services/reflection_reviews.py", "static/js/annual-library.js",
               "static/js/monthly-library.js", "static/js/weekly-library.js", "static/js/daily-reflection-review.js"]


def main():
    def read(path):
        return subprocess.check_output(["git", "-C", str(SOURCE), "show", f"{COMMIT}:{path}"]).decode("utf-8")

    source = read(FORM)
    base = read("templates/base.html")
    css = re.search(r"<style>\s*(\.plan-docs-content\s*\{.*?)</style>", base, re.S).group(1)
    (HERE / "deployed-form.css").write_text(css, encoding="utf-8")
    (HERE / "daily-example-list.css").write_text(read("static/css/daily-example-list.css"), encoding="utf-8")
    original = source
    source = source.replace('method="post" action="/plans/daily-plans" id="daily-draft"', 'action="#" id="daily-draft" novalidate')
    source = source.replace('method="get" action="/plans/daily-plans/new"', 'action="#" id="mock-search"')
    source = re.sub(r'href="/plans/daily-plans/new\?[^\"]+" target="_blank" rel="noopener"', 'href="#daily-draft" data-copy="{{ example.id }}"', source)
    source = source.replace('href="/plans/"', 'href="#" id="mock-back"')
    source = source.replace('  <script src="{{ static_asset_url(\'js/daily-example-search.js\') }}"></script>', '')
    source = source.replace('    <div class="form-actions">', '''    <div class="save-area"><div id="save-feedback" class="save-feedback" tabindex="-1" hidden></div>
    <div class="form-actions">''', 1)
    source = source.replace('    </div>\n  </form>\n\n  <template', '    </div></div>\n  </form>\n\n  <template', 1)
    env = Environment(loader=DictLoader({"base.html": (HERE / "shell.html.j2").read_text(encoding="utf-8"), "form.html": source}), autoescape=select_autoescape(["html", "j2"]))
    examples = [dict(id="leaves", main_activity="落ち葉で遊ぶ（見本）", title="架空の日案例", age_class="2歳児", month=11,
                     aims=["秋の自然に親しむ。"], content="落ち葉を集め、色や形の違いを楽しむ。", review_pending=False,
                     activity_blocks=[dict(time_and_activity="10:00〜10:40", child_state="落ち葉を拾って見せ合う。", support="発見したことに耳を傾ける。", considerations="足元と周囲の安全を確認する。")])]
    user = SimpleNamespace(name="見本 はなこ", can_edit=True, classroom_refs=("さくら組（見本）", "そら組（見本）"))
    values = dict(target_date="2026-11-16", classroom_ref=user.classroom_refs[0], age_class="", owner_name=user.name, timeline_rows=[dict(row_key="row_1")])
    html = env.get_template("form.html").render(user=user, errors=[], form_values=values, examples=examples,
             default_classroom_ref=user.classroom_refs[0], age_class_options=[f"{n}歳児" for n in range(6)],
             selected_age_class="", selected_month=None, search_query="", corpus_info={}, corpus_error="",
             static_asset_url=lambda path: Path(path).name)
    assert 'action="/plans/' not in html and 'href="/plans/' not in html
    (HERE / "index.html").write_text(html, encoding="utf-8")
    evidence = {"date_jst": "2026-11-15", "recorded_deployed_commit": COMMIT,
                "live_server_rechecked": False, "synthetic_data_only": True, "production_connections": False,
                "source_sha256": {p: sha256(read(p).encode()).hexdigest() for p in AUDIT_FILES},
                "original_form_sha256": sha256(original.encode()).hexdigest()}
    (HERE / "baseline.json").write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(HERE / "index.html")


if __name__ == "__main__":
    main()
