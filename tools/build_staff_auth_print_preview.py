"""Build a disconnected staff handout mock from the recorded production release."""
import hashlib
import json
import re
from pathlib import Path
from types import SimpleNamespace as NS

import qrcode
from jinja2 import DictLoader, Environment, select_autoescape
from qrcode.image.svg import SvgPathFillImage

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / ".local-dev/dependency-rollout-20261023/source"
OUT = ROOT / "tools/staff-auth-print-preview"
BASELINE = "5aabf64b559b10318b015e628e9109bcfb076631"
FILES = ["templates/base.html", "routers/staff_auth.py", "local_auth.py"] + [
    f"templates/staff_auth/{name}.html"
    for name in ("authentication", "action_code", "activate", "activate_confirm", "reset_password")
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sources = {path: (SOURCE / path).read_text(encoding="utf-8") for path in FILES}
    env = Environment(loader=DictLoader({
        "base.html": "{% block content %}{% endblock %}",
        **{p: text for p, text in sources.items() if p != "templates/base.html"},
    }), autoescape=select_autoescape())
    env.filters["jst_datetime"] = lambda value: value
    user = NS(id="fictional-staff", display_name="見本 はな", email="hana@example.invalid", is_active=True)
    credential = NS(login_id="hana@example.invalid", password_changed_at="2026/10/01 09:00")
    context = dict(user=user, credential=None, csrf_token="mock-only", form_error="", target_name=user.display_name,
                   activation_code="H7K3MP", login_id=credential.login_id)
    views = {
        "admin-activate": env.get_template("templates/staff_auth/authentication.html").render(**context, auth_status="not_configured"),
        "admin-reset": env.get_template("templates/staff_auth/authentication.html").render(**{**context, "credential": credential}, auth_status="configured"),
        "recipient-activate": env.get_template("templates/staff_auth/activate.html").render(**context),
        "recipient-reset": env.get_template("templates/staff_auth/reset_password.html").render(**context),
        "confirm": env.get_template("templates/staff_auth/activate_confirm.html").render(**context),
    }
    for name, markup in views.items():
        markup = re.sub(r'<input[^>]*type="hidden"[^>]*>', "", markup)
        markup = markup.replace('method="post"', 'method="dialog"')
        markup = re.sub(r'action="[^"]+"', 'action="#"', markup)
        views[name] = markup
    qr = {}
    for action, path in [("activate", "/staff/activate"), ("reset", "/staff/reset-password")]:
        url = "https://staff.example.invalid" + path
        svg = qrcode.make(url, image_factory=SvgPathFillImage, border=4).to_string().decode()
        svg = re.sub(r'<\?xml[^>]+>', "", svg)
        qr[action] = {"url": url, "svg": svg}
    fixture = {"views": views, "qr": qr, "baseline": BASELINE}
    (OUT / "fixtures.js").write_text("window.StaffPrintFixture=" + json.dumps(fixture, ensure_ascii=False) + ";\n", encoding="utf-8")
    base = re.sub(r'<script\b[^>]*>.*?</script>', "", sources["templates/base.html"], flags=re.S)
    shell = Environment(loader=DictLoader({"base.html": base, "shell.html": '{% extends "base.html" %}{% block title %}確認用：職員のQR付き案内{% endblock %}{% block content %}<div id="mock-view"></div>{% endblock %}'}), autoescape=select_autoescape())
    page = shell.get_template("shell.html").render(
        request=NS(url=NS(path="/staff/users"), state=NS(csrf_token="")),
        current_user=NS(staff_id="fictional-admin", name="見本 管理者", role_label="管理者", can_manage_child_records=True),
    )
    toolbar = '''<div id="preview-toolbar" class="no-print">
      <div class="preview-heading"><strong>確認用モック · 職員のQR付き案内</strong><span>架空データ／本番への登録・保存・送信なし／見本時刻 2026/11/01 10:00</span></div>
      <div class="preview-controls">
        <label>用途<select id="preview-action"><option value="activate">初回設定</option><option value="reset">パスワード再設定</option></select></label>
        <label>画面<select id="preview-view"><option value="issued">発行後・印刷用の案内</option><option value="admin">管理者・コード発行</option><option value="recipient">本人・設定画面</option></select></label>
        <label>状態<select id="preview-state"><option value="filled">入力済み</option><option value="empty">未入力</option><option value="partial">一部入力</option><option value="error">エラー</option><option value="expired">期限切れ</option><option value="urlmissing">施設URL未設定</option></select></label>
        <button type="button" id="try-recipient">QRの先の画面を試す</button>
      </div><p id="preview-status" role="status">まず印刷の見え方を確認し、「管理者・コード発行」から操作も試せます。</p>
    </div>'''
    page = page.replace("</head>", '''<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; font-src 'self'; connect-src 'none'; form-action 'none'; base-uri 'none'; object-src 'none'">
<link rel="stylesheet" href="preview.css"><script src="tailwind.js"></script><script src="fixtures.js"></script><script src="preview.js" defer></script></head>''')
    page = page.replace('<body class="bg-slate-50 text-slate-800">', '<body class="bg-slate-50 text-slate-800">' + toolbar)
    (OUT / "index.html").write_text(page, encoding="utf-8")
    (OUT / "tailwind.js").write_bytes((ROOT / ".local-dev/spec-20260908/tailwind.js").read_bytes())
    manifest = {
        "recorded_production_commit": BASELINE,
        "source": str(SOURCE),
        "live_server_checked": False,
        "source_sha256": {p: hashlib.sha256((SOURCE / p).read_bytes()).hexdigest() for p in FILES},
        "main_matches_source_ignoring_line_endings": {p: (ROOT / p).read_text(encoding="utf-8") == sources[p] for p in FILES},
        "mock_only": True,
    }
    (OUT / "baseline.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False))


if __name__ == "__main__":
    main()
