# -*- coding: utf-8 -*-
"""
基底文例テンプレートを framework の軸で組合せ展開し、SQLite に格納する。

出所タグ (provenance):
  - shishin_framework : 分類軸・領域・ねらいの方向性（指針由来。再配布可）
  - ai_generated      : 文例の文面（本ツール生成。要保育士監修）
各行は両方の性質を持つ（枠組みは指針由来、文面はAI生成）ため、
text_provenance と framework_source の2列で記録する。
"""
import sqlite3
import json
import itertools
import hashlib
from pathlib import Path
from framework import (
    PLAN_TYPES, AGE_BANDS, RYOIKI, YOUGO, RYOIKI_DIRECTION, YOUGO_DIRECTION,
    MONTHS, SEASON, PERIODS, PLAN_ITEMS,
)
from templates import TEMPLATES

# 項目がどの軸で展開するかの分類
RYOIKI_ITEMS = {  # 領域/視点ごとに展開する項目
    "教育のねらい", "週のねらい", "期のねらい", "ねらい",
    "前月末の子どもの姿", "予想される子どもの姿", "活動内容・子どもの姿",
    "活動内容", "環境構成・保育者の援助", "環境構成・援助", "評価・反省",
}
YOUGO_ITEMS = {"養護のねらい"}
# それ以外は季節のみで展開（領域に依存しない一般項目）


def fill(tpl, **kw):
    try:
        return tpl.format(**kw)
    except KeyError:
        return None


def rows():
    out = []
    for plan in PLAN_TYPES:
        items = PLAN_ITEMS[plan]
        for klass, devkey, getsurei in AGE_BANDS:
            ryoiki_list = RYOIKI[devkey]
            # 時間単位: 年案=期, それ以外=月
            if plan == "年案":
                time_units = [(p[0], p[1], p[2][0]) for p in PERIODS]  # (期名, 期範囲, 代表月)
            else:
                time_units = [(str(m), "", m) for m in MONTHS]
            # 個人案は0〜2歳のみ（月齢刻みがある区分）
            if plan == "個人案" and not getsurei:
                continue
            age_slots = getsurei if (plan == "個人案" and getsurei) else [klass]

            for tname, trange, month in time_units:
                s = SEASON[month]
                period_label = f"{tname}（{trange}）" if trange else ""
                for item in items:
                    if item not in TEMPLATES:
                        continue
                    tpls = TEMPLATES[item]
                    for age in age_slots:
                        if item in RYOIKI_ITEMS:
                            for ryoiki in ryoiki_list:
                                dirs = RYOIKI_DIRECTION.get(ryoiki, [""])
                                for d, tpl in itertools.product(dirs, tpls):
                                    text = fill(tpl, dir=d, ryoiki=ryoiki, event=s["event"],
                                                nature=s["nature"], play=s["play"], age=age,
                                                period=period_label)
                                    if text:
                                        out.append(dict(
                                            plan_type=plan, age_class=klass, age_detail=age,
                                            dev_band=devkey, time_unit=tname, item=item,
                                            ryoiki=ryoiki, direction=d, month=month,
                                            text=text))
                        elif item in YOUGO_ITEMS:
                            for y in YOUGO:
                                dirs = YOUGO_DIRECTION[y]
                                for d, tpl in itertools.product(dirs, tpls):
                                    text = fill(tpl, youngo=d, event=s["event"], nature=s["nature"],
                                                play=s["play"], period=period_label)
                                    if text:
                                        out.append(dict(
                                            plan_type=plan, age_class=klass, age_detail=age,
                                            dev_band=devkey, time_unit=tname, item=item,
                                            ryoiki=f"養護:{y}", direction=d, month=month,
                                            text=text))
                        else:  # 一般項目（季節＋必要に応じて月齢）
                            for tpl in tpls:
                                text = fill(tpl, event=s["event"], nature=s["nature"],
                                            play=s["play"], period=period_label, age=age)
                                if text:
                                    out.append(dict(
                                        plan_type=plan, age_class=klass, age_detail=age,
                                        dev_band=devkey, time_unit=tname, item=item,
                                        ryoiki=None, direction=None, month=month,
                                        text=text))
    return out


BASE_DIR = Path(__file__).resolve().parent


def build(db_path=None):
    db_path = Path(db_path) if db_path else BASE_DIR / "bunrei.sqlite"
    data = rows()
    # 重複除去（同一文面・同一軸）
    seen, uniq = set(), []
    for r in data:
        key = (r["plan_type"], r["age_class"], r["age_detail"], r["item"],
               r["ryoiki"], r["month"], r["text"])
        if key in seen:
            continue
        seen.add(key)
        r["id"] = hashlib.sha1(repr(key).encode()).hexdigest()[:12]
        uniq.append(r)

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS bunrei")
    cur.execute("""
        CREATE TABLE bunrei (
            id            TEXT PRIMARY KEY,
            plan_type     TEXT NOT NULL,   -- 計画種別
            age_class     TEXT NOT NULL,   -- クラス（0歳児..5歳児）
            age_detail    TEXT,            -- 月齢刻み（個人案）またはクラス
            dev_band      TEXT,            -- 指針の発達区分キー
            time_unit     TEXT,            -- 月 or 期
            month         INTEGER,         -- 代表月（季節フィルタ用）
            item          TEXT NOT NULL,   -- 記入項目
            ryoiki        TEXT,            -- 5領域/3視点/養護
            direction     TEXT,            -- ねらいの方向性（指針由来）
            text          TEXT NOT NULL,   -- 文例本文
            text_provenance   TEXT NOT NULL DEFAULT 'ai_generated',
            framework_source  TEXT NOT NULL DEFAULT 'shishin_framework',
            needs_review      INTEGER NOT NULL DEFAULT 1
        )""")
    cur.executemany("""
        INSERT INTO bunrei
        (id, plan_type, age_class, age_detail, dev_band, time_unit, month, item,
         ryoiki, direction, text, text_provenance, framework_source, needs_review)
        VALUES (:id,:plan_type,:age_class,:age_detail,:dev_band,:time_unit,:month,:item,
                :ryoiki,:direction,:text,'ai_generated','shishin_framework',1)
    """, uniq)
    # フィルタ用インデックス（実運用の「年齢×季節×項目」検索を想定）
    cur.execute("CREATE INDEX idx_filter ON bunrei(plan_type, age_class, month, item, ryoiki)")
    con.commit()

    # 統計
    stats = {}
    for label, q in [
        ("total", "SELECT COUNT(*) FROM bunrei"),
        ("by_plan", "SELECT plan_type, COUNT(*) FROM bunrei GROUP BY plan_type"),
        ("by_item", "SELECT item, COUNT(*) FROM bunrei GROUP BY item ORDER BY 2 DESC"),
        ("by_class", "SELECT age_class, COUNT(*) FROM bunrei GROUP BY age_class"),
    ]:
        cur.execute(q)
        stats[label] = cur.fetchall()
    con.close()

    # JSONL サンプル書き出し
    sample_path = db_path.with_name("sample.jsonl")
    with sample_path.open("w", encoding="utf-8") as f:
        for r in uniq[:40]:
            f.write(json.dumps({k: r[k] for k in
                    ["id","plan_type","age_class","age_detail","month","item","ryoiki","direction","text"]},
                    ensure_ascii=False) + "\n")
    return stats


if __name__ == "__main__":
    st = build()
    print("総件数:", st["total"][0][0])
    print("\n計画種別ごと:")
    for k, v in st["by_plan"]:
        print(f"  {k}: {v}")
    print("\nクラスごと:")
    for k, v in st["by_class"]:
        print(f"  {k}: {v}")
    print("\n項目ごと（上位）:")
    for k, v in st["by_item"][:12]:
        print(f"  {k}: {v}")
