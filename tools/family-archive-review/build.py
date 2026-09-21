"""Render production form fragments with fictional values; never import the app/DB."""
from pathlib import Path
from types import SimpleNamespace as NS
import hashlib
import io
import json
import re
import shutil
import subprocess
import tarfile

from jinja2 import DictLoader, Environment, select_autoescape

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT
OUT = ROOT / ".local-dev/family-archive-review"
BASELINE = "8ec32083aed01256263dbad4237157ea729abcbc"

# Pin the reviewed deployment even while implementation proceeds in this worktree.
archive = subprocess.run(
    ["git", "archive", BASELINE, "templates"], cwd=SOURCE, check=True, capture_output=True,
).stdout
with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
    source_templates = {
        member.name.removeprefix("templates/"): bundle.extractfile(member).read().decode("utf-8")
        for member in bundle.getmembers() if member.isfile()
    }
env = Environment(loader=DictLoader({
    **source_templates, "base.html": "{% block content %}{% endblock %}",
    "children/_photo_preview_script.html": "",
}), autoescape=select_autoescape(["html"]))
env.filters["jst_datetime"] = lambda value, fmt: value
user = NS(is_admin=True, can_manage_child_records=True)
children = [NS(id=201, full_name="見本 ひなた", family=NS(family_name="見本家")),
            NS(id=202, full_name="確認 あお", family=NS(family_name="確認家"))]
accounts = [NS(id=301, display_name="見本 はる", family=NS(family_name="見本家"),
               email="guardian@example.invalid", status=NS(label="有効"))]
fields = re.findall(r'<(?:input|select|textarea)\b[^>]*\bname="([^"]+)"', source_templates["families/form.html"])
form = env.get_template("families/form.html").render(
    current_user=user, form_data={key: "" for key in fields}, submit_label="家族を更新",
    action_url="#", children=children, parent_accounts=accounts, parent_accounts_by_id={},
    selected_child_ids=[], selected_parent_account_ids=[], guardian_account_fields={})
datasets = [NS(id=key, label=label) for key, label in [
    ("classrooms", "クラス"), ("families", "家庭"), ("children", "園児"),
    ("parents", "保護者アカウント"), ("parent_child_links", "保護者・園児紐づけ"), ("staff", "職員")]]
transfers = env.get_template("data_transfers/index.html").render(
    current_user=user, datasets=datasets, selected_dataset="families", classrooms=[NS(id=1, name="見本組")],
    child_status_options=[NS(value="enrolled", label="在園"), NS(value="graduated", label="卒園"), NS(value="withdrawn", label="退園")],
    parent_status_options=[NS(value="active", label="有効"), NS(value="inactive", label="停止中")],
    ninka_default_fiscal_year=2026, logs=[])

def inert(fragment):
    fragment = re.sub(r"<script\b[^>]*>[\s\S]*?</script>", "", fragment)
    fragment = re.sub(r' action="[^"]*"', ' action="#"', fragment)
    return fragment

templates = {"form": inert(form), "transfers": inert(transfers), "baseline": BASELINE}
rendered_fields = set(re.findall(r'name="([^"]+)"', templates["form"]))
assert set(fields) <= rendered_fields, "A deployed family form field was omitted"
assert {"g1_photo", "g2_photo"} <= rendered_fields
assert "<script" not in templates["form"] and "<script" not in templates["transfers"]
OUT.mkdir(parents=True, exist_ok=True)
payload = json.dumps(templates, ensure_ascii=False).replace("<", "\\u003c")
html = (HERE / "shell.html").read_text(encoding="utf-8").replace("/* REVIEW_TEMPLATES */", "window.REVIEW_TEMPLATES = " + payload + ";")
(OUT / "index.html").write_text(html, encoding="utf-8")
for name in ("app.js", "style.css"):
    shutil.copyfile(HERE / name, OUT / name)
manifest = {"baseline": BASELINE, "sources": {name: hashlib.sha256(source_templates[name].encode("utf-8")).hexdigest()
            for name in ["families/list.html", "families/form.html", "families/delete.html", "data_transfers/index.html"]},
            "form_field_names": sorted(set(fields)), "output": str(OUT / "index.html")}
(OUT / "build.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"output": str(OUT / "index.html"), "baseline": BASELINE, "existing_form_fields": len(set(fields))}))
