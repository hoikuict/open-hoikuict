# -*- coding: utf-8 -*-
"""
被覆拡張版ジェネレータ。

generate.py の基底 rows() を再利用しつつ、以下を追加する:
  - 年間目標（年案。通年・領域横断の本来の年間目標。従来は期のねらいで代用していた穴を埋める）
  - 期の振り返り観点（年案。従来は項目自体が無かった穴を埋める）
  - 10の姿のねらい（3歳以上。5領域に加えた付加軸。月非依存=通年で保持）

10の姿の行は month=None（通年）で保持する。これは「同じ姿を12か月ぶん複製する」
冗長な量増しを避けるため。アプリ側は _fetch_examples の月フィルタを
`(month = ? OR month IS NULL)` に拡張すれば月案画面に表示できる（INTEGRATION参照）。

出所タグ: 文面は ai_generated・要監修。分類軸（10の姿名・目標/観点の方向性）は
shishin_framework。新たに juu_no_sugata 列を追加（後方互換: 既存列は不変）。
"""
import sqlite3
import json
import hashlib
import itertools
from pathlib import Path

import framework as fw
from templates import TEMPLATES_EXTRA
from generate import rows as base_rows

BASE_DIR = Path(__file__).resolve().parent

# 代表月（季節フィルタ用）
PERIOD_REP_MONTH = {"Ⅰ期": 4, "Ⅱ期": 7, "Ⅲ期": 10, "Ⅳ期": 1}
OVER3_CLASSES = [c for c, dev, _ in fw.AGE_BANDS if dev == "over3"]


def extra_rows():
    out = []

    # --- 年間目標（年案・通年・age_classごと） ---
    for klass, devkey, _ in fw.AGE_BANDS:
        for goal_dir, tpl in itertools.product(fw.ANNUAL_GOAL_DIRECTION, TEMPLATES_EXTRA["年間目標"]):
            out.append(dict(
                plan_type="年案", age_class=klass, age_detail=klass, dev_band=devkey,
                time_unit="通年", month=4, item="年間目標", ryoiki=None,
                direction=goal_dir, juu_no_sugata=None,
                text=tpl.format(goal_dir=goal_dir)))

    # --- 期の振り返り観点（年案・期ごと） ---
    for klass, devkey, _ in fw.AGE_BANDS:
        for (term_name, term_range, _months) in [(p[0], p[1], p[2]) for p in fw.PERIODS]:
            period_label = f"{term_name}（{term_range}）"
            for vp, tpl in itertools.product(fw.ANNUAL_REFLECTION_VIEWPOINT, TEMPLATES_EXTRA["期の振り返り観点"]):
                out.append(dict(
                    plan_type="年案", age_class=klass, age_detail=klass, dev_band=devkey,
                    time_unit=term_name, month=PERIOD_REP_MONTH[term_name],
                    item="期の振り返り観点", ryoiki=None, direction=vp, juu_no_sugata=None,
                    text=tpl.format(period=period_label, vp=vp)))

    # --- 10の姿のねらい（3歳以上・月案/年案・通年 month=None） ---
    for klass in OVER3_CLASSES:
        for plan in ("月案", "年案"):
            for sugata in fw.JUU_NO_SUGATA:
                d = fw.JUU_NO_SUGATA_DIRECTION[sugata]
                for tpl in TEMPLATES_EXTRA["10の姿のねらい"]:
                    out.append(dict(
                        plan_type=plan, age_class=klass, age_detail=klass, dev_band="over3",
                        time_unit=None, month=None, item="10の姿のねらい",
                        ryoiki=None, direction=d, juu_no_sugata=sugata,
                        text=tpl.format(sugata=sugata, dir=d)))
    return out


def build(db_path=None):
    db_path = Path(db_path) if db_path else BASE_DIR / "bunrei.sqlite"
    data = base_rows()
    for r in data:               # 基底行に juu_no_sugata 列を付与（None）
        r["juu_no_sugata"] = None
    data += extra_rows()

    seen, uniq = set(), []
    for r in data:
        key = (r["plan_type"], r["age_class"], r["age_detail"], r["item"],
               r["ryoiki"], r["juu_no_sugata"], r["month"], r["text"])
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
            id TEXT PRIMARY KEY, plan_type TEXT NOT NULL, age_class TEXT NOT NULL,
            age_detail TEXT, dev_band TEXT, time_unit TEXT, month INTEGER,
            item TEXT NOT NULL, ryoiki TEXT, direction TEXT,
            juu_no_sugata TEXT,                              -- 10の姿（付加軸・新規）
            text TEXT NOT NULL,
            text_provenance  TEXT NOT NULL DEFAULT 'ai_generated',
            framework_source TEXT NOT NULL DEFAULT 'shishin_framework',
            needs_review     INTEGER NOT NULL DEFAULT 1
        )""")
    cur.executemany("""
        INSERT INTO bunrei
        (id, plan_type, age_class, age_detail, dev_band, time_unit, month, item,
         ryoiki, direction, juu_no_sugata, text, text_provenance, framework_source, needs_review)
        VALUES (:id,:plan_type,:age_class,:age_detail,:dev_band,:time_unit,:month,:item,
                :ryoiki,:direction,:juu_no_sugata,:text,'ai_generated','shishin_framework',1)
    """, uniq)
    cur.execute("CREATE INDEX idx_filter ON bunrei(plan_type, age_class, month, item, ryoiki)")
    cur.execute("CREATE INDEX idx_sugata ON bunrei(plan_type, age_class, juu_no_sugata)")
    con.commit()

    cur.execute("SELECT COUNT(*) FROM bunrei"); total = cur.fetchone()[0]
    cur.execute("SELECT item, COUNT(*) FROM bunrei WHERE item IN ('年間目標','期の振り返り観点','10の姿のねらい') GROUP BY item")
    new_items = cur.fetchall()
    con.close()

    with (BASE_DIR / "sample.jsonl").open("w", encoding="utf-8") as f:
        for r in uniq[:40]:
            f.write(json.dumps({k: r[k] for k in
                    ["id","plan_type","age_class","month","item","ryoiki","juu_no_sugata","direction","text"]},
                    ensure_ascii=False) + "\n")
    return total, new_items


if __name__ == "__main__":
    total, new_items = build()
    print("総件数:", total)
    print("追加項目:", dict(new_items))
