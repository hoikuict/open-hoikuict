"""Build an offline review page from the deployed templates and fictional data."""
from datetime import date
from pathlib import Path
import ast
import json
import re
import subprocess
import sys

from jinja2 import DictLoader, Environment, select_autoescape


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / ".local-dev/document-search-rollout-20261108/source"
REV = "a3641fa9903bd9cbca6519d83a057c913923ccb8"
# Read immutable files without importing the application or opening any database.
def source(path):
    return subprocess.check_output(["git", "-C", str(SOURCE), "show", f"{REV}:{path}"]).decode()


names = ["parent_portal/contact_form.html", "parent_portal/_contact_quick_inputs.html",
         "shared/_pickup_fields.html", "shared/_pickup_script.html", "children/detail.html",
         "children/_care_record.html", "parent_portal/home.html"]
files = {name: source("templates/" + name) for name in names}
for name in ("children/list.html", "children/_table.html", "parent_portal/pickup.html"):
    files[name] = source("templates/" + name)
files["base.html"] = "{% block content %}{% endblock %}{% block body_end %}{% endblock %}"
# The editable mock supplies this section for the selected child, including on absence days.
files["parent_portal/_daily_emergency.html"] = '<section id="emergency"></section>'
files["parent_portal/_meal_fields.html"] = source("templates/parent_portal/_meal_fields.html")
env = Environment(loader=DictLoader(files), autoescape=select_autoescape(default=True))
env.filters["jst_datetime"] = lambda value, fmt: ""
env.globals["parent_enrollment_enabled"] = lambda: False
env.globals["meal_dates"] = lambda day: [("dinner", ""), ("breakfast", "")]


def once(markup, needle, replacement):
    if markup.count(needle) != 1:
        raise ValueError(f"Expected one insertion point: {needle}")
    return markup.replace(needle, replacement)


def local_links(markup):
    routes = {"/children/": "#children", "/parent-portal/history": "#history",
              "/parent-portal/?date=MOCKDATE": "#home"}
    for i in (1, 2):
        routes[f"/children/{i}"] = f"#profile/{i}"
        routes[f"/parent-portal/children/{i}/contact?date=MOCKDATE"] = f"#daily/{i}"
        routes[f"/parent-portal/children/{i}/pickup?date=MOCKDATE"] = f"#pickup/{i}"
    def rewrite(match):
        destination = routes.get(match.group(1))
        return f'href="{destination}"' if destination else 'aria-disabled="true" title="今回の試用範囲外"'
    return re.sub(r'href="(/[^"]*)"', rewrite, re.sub(r' (?:action|method)="[^"]*"', '', markup))


children = [dict(id=i, full_name="見本 " + name, classroom=dict(name=group),
                 full_name_kana="ミホン " + kana, birth_date=dob, age=age, status=dict(label="在園"),
                 sex=dict(label=sex), family=dict(family_name="見本"), get_field=lambda key: "",
                 shared_home_address="見本町 1番地", shared_home_phone="000-0000-0100")
            for i, name, kana, group, dob, age, sex in [
                (1, "あおい", "アオイ", "さくら組", date(2021, 6, 12), 5, "女"),
                (2, "ひなた", "ヒナタ", "ひよこ組", date(2024, 4, 5), 2, "男")]]
guardians = [dict(last_name="見本", first_name=name, relationship=role, phone=phone,
                  parent_account_id=i+1, workplace=work, workplace_phone=office, email=f"demo{i}@example.invalid")
             for i, (name, role, phone, work, office) in enumerate([
                 ("はなこ", "母", "000-0000-0103", "見本商店", "000-0000-0101"),
                 ("たろう", "父", "000-0000-0104", "見本工房", "000-0000-0102")])]
accounts = {g["parent_account_id"]: dict(id=g["parent_account_id"], display_name="見本 " + g["first_name"],
            email=g["email"], phone=g["phone"], status=dict(label="有効")) for g in guardians}
# Only fictional numbers explicitly identified as mobile in these examples use the mobile label.
examples = {
    "standard": guardians,
    "unknown": [dict(g, relationship="") for g in guardians],
    "single": [guardians[1]],
    "single-extra": [guardians[0]],
    "partial": [dict(guardians[0], workplace_phone=""), guardians[1]],
}
contact_examples = {}
for example, members in examples.items():
    contact_examples[example] = {
        "guardians": [
            dict(id=g["parent_account_id"], name=g["last_name"] + " " + g["first_name"],
                 role=g["relationship"], office=g["workplace_phone"], phone=g["phone"], mobile=True)
            for g in members
        ],
        "extras": {"1": [dict(id="extra-grandma", label="祖母の携帯", phone="000-0000-0105")]}
        if example == "single-extra" else {},
    }
parent = dict(display_name="見本 はなこ", child_links=[1, 2])
home = env.get_template(names[-1]).render(children=children, current_parent_user=parent,
    target_date_value="MOCKDATE", latest_updates=[], entry_by_child_id={}, reply_by_child_id={},
    pending_request_by_child_id={}, medical_status={}, unread_notice_count=0)
home = local_links(home)

fields = ast.literal_eval(re.search(r"^CHILD_FIELDS = (\[.*?^\])", source("models.py"), re.M | re.S)[1])
for c in children:
    surname, given = c["full_name"].split()
    c.update(last_name=surname, first_name=given, status=dict(value="enrolled", label="在園"))
    field_values = dict(c, classroom=c["classroom"]["name"], home_address=c["shared_home_address"],
                        home_phone=c["shared_home_phone"], first_name_kana=c["full_name_kana"].split()[1],
                        last_name_kana="ミホン", guardians="MOCKGUARDIANS",
                        siblings=children[1 if c["id"] == 1 else 0]["full_name"])
    c["get_field"] = field_values.get
roster = env.get_template("children/list.html").render(children=children, total=2, current_user={"role":"staff"},
    all_fields=fields, selected_fields=[f["key"] for f in fields], current_status="enrolled",
    current_sort_by="name", current_sort_order="asc", sort_options={"name":"名前","birth_date":"生年月日"},
    sort_order_options={"asc":"昇順","desc":"降順"})
for field in fields:
    if not field["default"]:
        roster = roster.replace(f'value="{field["key"]}" checked', f'value="{field["key"]}"')
roster = local_links(re.sub(r' hx-[\w-]+="[^"]*"', "", roster))

detail_template = source("templates/daily_contacts/detail.html")
reply_form = re.search(r'(<form id="daily-reply-form".*?</form>)', detail_template, re.S)[1]
reply_fields = []
tree = ast.parse(source("daily_contact_reply_fields.py"))
for node in next(n.value for n in tree.body if isinstance(n, ast.AnnAssign)
                 and n.target.id == "DEFAULT_DAILY_CONTACT_REPLY_FIELDS").elts:
    reply_fields.append(dict(key=node.args[0].value, label=node.args[1].value,
                             **{kw.arg: ast.literal_eval(kw.value) for kw in node.keywords}))
reply_form = local_links(env.from_string(reply_form).render(child=children[0],reply_fields=reply_fields,reply_form_values={}))

profiles = []
for example, members in examples.items():
    example_accounts = {g["parent_account_id"]: accounts[g["parent_account_id"]] for g in members}
    for child in children:
        markup = env.get_template("children/detail.html").render(child=child, family_children=children,
            guardian_profiles=members, current_user={}, family_parent_accounts=example_accounts.values(),
            family_parent_accounts_by_id=example_accounts, care_certifications=[])
        marker = '<div class="grid grid-cols-1 gap-4 md:grid-cols-3">'
        markup = once(markup, marker, '<div id="family-emergency"></div>' + marker)
        profiles.append(f'<template id="profile-{example}-{child["id"]}">{local_links(markup)}</template>')

daily = env.get_template("parent_portal/contact_form.html").render(child=dict(full_name="MOCKCHILD",id=1),
    form_data={}, target_date_value="MOCKDATE", pickup_editable=True, pickup_values={}, emergency=True,
    appetites=("旺盛", "普通", "あまりない", "ない"),
    present_temperature_limit=37.5, present_temperature_error="37.5℃以上の場合は、出席として送信できません。",
    temperature_format_error="体温を数字で入力してください。")
scripts = re.findall(r"<script>(.*?)</script>", daily, re.S)
assert len(scripts) == 3
pickup_script = once(scripts[2], "const closing =", "let closing =")
pickup_script = once(pickup_script, "    sync();\n  });", """    root.addEventListener('closingchange', () => {
      closing = root.dataset.closingTime;
      sync();
    });
    sync();
  });""")
pickup = env.get_template("parent_portal/pickup.html").render(child=dict(full_name="MOCKCHILD"),
                                                             day="MOCKDATE", pickup_values={})
pickup = local_links(re.sub(r"<script>.*?</script>", "", pickup, flags=re.S))
daily = local_links(re.sub(r"<script>.*?</script>", "", daily, flags=re.S))
shell = (HERE / "shell.html").read_text(encoding="utf-8")
assets = {"HOME": home, "PROFILES": "".join(profiles), "DAILY": daily, "ROSTER":roster, "REPLY":reply_form,
          "PICKUP": pickup,
          "BIND": "function bindDeployedFields(){\n" + scripts[0] + "\n" + scripts[1] + "\n}\nfunction bindPickupFields(){\n" + pickup_script + "\n}",
          "EXAMPLES": json.dumps(contact_examples, ensure_ascii=False),
          "APP": (HERE / "app.js").read_text(encoding="utf-8"),
          "CSS": (HERE / "mock.css").read_text(encoding="utf-8"),
          "UTILITIES": (HERE / "utilities.css").read_text(encoding="utf-8") if (HERE / "utilities.css").exists() else ""}
for key, content in assets.items():
    shell = once(shell, f"<!--{key}-->", content)
out = HERE / "preview" / "index.html"
out.parent.mkdir(exist_ok=True)
out.write_text(shell, encoding="utf-8", newline="\n")
print(out)
