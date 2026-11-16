"""Render the real parent form with fictional values in a sandboxed preview."""
from datetime import date
from pathlib import Path
import re

from jinja2 import ChoiceLoader, DictLoader

from home_care_details import APPETITES
from parent_contact_fields import all_fields

ROOT = Path(__file__).resolve().parent


def render_preview(templates, policy, group, state):
    css = (ROOT / "static/css/parent-contact-preview.css").read_text(encoding="utf-8")
    base = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'none'; form-action 'none'; base-uri 'none'">
    <title>保護者画面の見本</title><style>""" + css + """
    [hidden]{display:none!important}body{padding:12px;background:#f8fafc;color:#334155;font-family:system-ui,sans-serif}
    </style></head><body>{% block content %}{% endblock %}{% block body_end %}{% endblock %}
    <script>document.querySelectorAll('a').forEach(a=>a.removeAttribute('href'));
    document.querySelectorAll('button[type=submit]').forEach(b=>{b.disabled=true;b.textContent='見本のため送信できません'});
    document.querySelector('form').addEventListener('submit',e=>e.preventDefault());</script></body></html>"""
    env = templates.env.overlay(loader=ChoiceLoader([DictLoader({"base.html": base}), templates.env.loader]))
    values = {}
    if state in {"filled", "partial", "error"}:
        values.update(temperature="36.7", mood="良好", contact_note="見本の連絡です。")
    if state == "filled":
        values.update(bedtime="20:30", wakeup_time="07:00", sleep_notes="よく眠りました",
            dinner_appetite="普通", dinner_contents="ごはん、焼き魚", breakfast_appetite="普通",
            breakfast_contents="パン、バナナ", stool_consistency="normal", stool_count="1",
            cough="なし", runny_nose="なし", medication="なし", condition_note="元気です。")
    if state == "error":
        values.update(attendance_mode="absent", contact_type="absent_sick", absence_reason="absent_sick")
    day = date(2026, 11, 16)
    markup = env.get_template("parent_portal/contact_form.html").render(
        child={"id": -1, "full_name": "見本 ひなた"}, entry=None, form_data=values,
        field_visibility=policy[policy["mode"]].get(group, all_fields()), contact_fields_revision="preview",
        target_date_value=day.isoformat(), target_day=day, pickup_editable=True,
        pickup_values={}, closing_time="19:00", emergency={"usual": {"contacts": [
            {"label": "見本保護者の電話", "phone": "000-0000-0000"}]},
            "answer": None, "base_revision": 1, "day_revision": 0}, appetites=APPETITES,
        present_temperature_limit="37.5", present_temperature_error="37.5℃以上の場合は、出席として送信できません。",
        temperature_format_error="体温は「36.7」のような数値で入力してください。",
        form_error="病欠の場合は現在の体温を入力してください。" if state == "error" else "")
    # All assets and values stay in the iframe; no parent account or DB submission.
    markup = re.sub(r'<script\b[^>]*src="[^"]*family-emergency\.js[^"]*"[^>]*></script>', "", markup)
    script = (ROOT / "static/js/family-emergency.js").read_text(encoding="utf-8")
    markup = markup.replace("</body>", "<script>" + script + "</script></body>")
    return markup.replace('action="/parent-portal/children/-1/contact"', 'action="#"')
