"""Render the deployed daily form with two fictional examples for a static, offline trial."""
from pathlib import Path
import re

from jinja2 import DictLoader, Environment, select_autoescape

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[3]
OUT = HERE / "plan-forms/daily-copy"


def example(key, title, age, month, aim, content, rows):
    blocks = [
        dict(time_and_activity=time, child_state=child, support=support, considerations=note)
        for time, child, support, note in rows
    ]
    return dict(id=key, title=title, main_activity=title, age_class=age, month=month,
                aims=[aim], content=content, activity_blocks=blocks)


examples = [
    example("leaves", "落ち葉を集める", "4歳児", 11, "拾った葉っぱを友だちと見せ合う。",
            "集めた葉っぱを並べて、色や形を見比べる。", [
                ("10:00", "落ち葉の色や形を見比べる。", "気づいた違いを一緒に言葉にする。", "歩く場所を確かめる。"),
                ("10:30", "気に入った葉っぱを紹介する。", "友だちの話を聞く時間を作る。", "座る場所を整える。"),
            ]),
    example("clay", "粘土で遊ぶ", "3歳児", 8, "やわらかい粘土の感触を楽しむ。",
            "丸めたり伸ばしたりして好きな形を作る。", [
                ("10:15", "粘土を手のひらで丸める。", "子どもの動きに合わせて声をかける。", "用具を使う場所を確かめる。"),
            ]),
]

base = (PROJECT / "templates/base.html").read_text(encoding="utf-8")
css = re.search(r"<style>\s*(\.plan-docs-content\s*\{.*?)</style>", base, re.S)[1]
css += "\n" + (PROJECT / "static/css/daily-example-list.css").read_text(encoding="utf-8")
source = (PROJECT / "templates/plan_docs/daily_plans/form.html").read_text(encoding="utf-8")
source = re.sub(r'<link rel="stylesheet" href="[^"]*daily-example-list\.css[^"]*">', "", source)
source = re.sub(r'<dialog id="daily-copy-choice".*?</dialog>', "", source, flags=re.S)
source = source.replace('method="get" action="/plans/daily-plans/new"', 'id="example-search"')
source = source.replace('method="post" action="/plans/daily-plans"', "novalidate")
source = re.sub(r'<a class="button button--secondary daily-example-copy".*?</a>',
                '<button type="button" class="button button--secondary daily-example-copy" data-copy="{{ example.id }}">この候補を下書きへコピー</button>', source)
source = source.replace('href="/plans/"', 'href="../daily-findings.html"')
source = re.sub(r'<script src="[^"]*daily-example-search\.js[^"]*"></script>', "", source)
env = Environment(loader=DictLoader({"base.html": (HERE / "daily-copy-shell.html.j2").read_text(encoding="utf-8"),
                                     "form.html": source}), autoescape=select_autoescape(default=True))
doc = env.get_template("form.html").render(
    user={"name": "見本 はなこ", "classroom_refs": ["そら組", "さくら組"], "can_edit": True},
    examples=examples, errors=[], corpus_info={}, corpus_error="", default_classroom_ref="そら組",
    form_values={"target_date":"2026-11-11", "classroom_ref":"そら組", "age_class":"3歳児",
                 "timeline_rows":[]}, selected_age_class="", selected_month=None,
    age_class_options=[f"{n}歳児" for n in range(6)], search_query="",
)
assert 'action="/plans' not in doc and 'href="/plans' not in doc and 'src="/static' not in doc
OUT.mkdir(exist_ok=True)
(OUT / "index.html").write_text(doc, encoding="utf-8")
(OUT / "form.css").write_text(css, encoding="utf-8")
