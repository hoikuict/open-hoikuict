# -*- coding: utf-8 -*-
"""
facility_import.py — 自園の過去計画を文例として取り込む。

目的: AIには出せない「生きた文章」を、著作権問題なく増やす（出所=自園）。
ただし子どもの個人情報が混入しやすいため、防御は多層で行う:

  1) PIIマスキング（ヒューリスティック。完全ではない）
  2) 園内限定スコープ（nursery_ref。他園には絶対に出さない）
  3) 必須監修（needs_review=1 固定。masked フラグと別に人の確認を要する）

重要: 自動マスキングは取りこぼす。これは「人の確認を省く道具」ではなく
「人の確認の前処理」である。masked=1 でも needs_review は外れない。

入力: CSV（列: plan_type, age_class, month, item, ryoiki, text）。
出力: facility.sqlite の bunrei_facility テーブル（共有コーパスとは別DB・別スコープ）。
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

# 共有コーパスの語彙と突き合わせる（緩く検証）
try:
    import framework as fw
    KNOWN_PLAN_TYPES = set(fw.PLAN_TYPES)
    KNOWN_AGE = {c for c, _, _ in fw.AGE_BANDS}
except Exception:  # framework が無い場所でも単体で動く
    KNOWN_PLAN_TYPES = {"年案", "月案", "週案", "個人案"}
    KNOWN_AGE = {"0歳児", "1歳児", "2歳児", "3歳児", "4歳児", "5歳児"}

# ---- PII マスキング（保守的・不完全） ----
# 子ども想定の敬称付き氏名。名前部分を伏せる。さん/先生は職員の可能性があるため対象外。
_NAME_HONORIFIC = re.compile(
    r"(?P<name>[一-龥ぁ-んァ-ヶ\u30FCA-Za-zＡ-Ｚａ-ｚ]{1,6})(?P<honorific>ちゃん|くん|君)"
)
# 7桁以上の連続数字（電話・ID 想定）
_LONG_DIGITS = re.compile(
    r"0[0-9０-９]{1,3}[\-‐ー－—\s]?[0-9０-９]{2,4}[\-‐ー－—\s]?[0-9０-９]{3,4}"
    r"|[0-9０-９]{7,}"
)


def mask_pii(text: str) -> tuple[str, bool]:
    """個人情報らしき箇所を伏せる。戻り値: (マスク後, 何か伏せたか)。"""
    masked = False

    def _name_sub(m: re.Match) -> str:
        nonlocal masked
        masked = True
        name = m.group("name")
        prefix = ""
        if len(name) > 4:
            prefix = name[:-3]
        elif len(name) > 3 and name[0] in "とやがはをにへで":
            prefix = name[0]
        return prefix + "◯◯" + m.group("honorific")

    out = _NAME_HONORIFIC.sub(_name_sub, text)
    if _LONG_DIGITS.search(out):
        out = _LONG_DIGITS.sub("◯◯◯", out)
        masked = True
    return out, masked


def _row_id(nursery_ref: str, plan_type: str, item: str, text: str) -> str:
    key = f"{nursery_ref}|{plan_type}|{item}|{text}"
    return "fac_" + hashlib.sha1(key.encode()).hexdigest()[:10]


def ensure_table(con: sqlite3.Connection) -> None:
    con.execute("""
        CREATE TABLE IF NOT EXISTS bunrei_facility (
            id TEXT PRIMARY KEY,
            nursery_ref TEXT NOT NULL,            -- 園スコープ。他園に出さない
            visibility  TEXT NOT NULL DEFAULT 'facility_private',
            plan_type TEXT, age_class TEXT, month INTEGER, item TEXT, ryoiki TEXT,
            text TEXT NOT NULL,
            text_provenance TEXT NOT NULL DEFAULT 'facility',
            masked INTEGER NOT NULL DEFAULT 0,    -- 自動マスクが何か伏せたか
            needs_review INTEGER NOT NULL DEFAULT 1,  -- 常に1。人の確認必須
            source_note TEXT,
            imported_at TEXT NOT NULL
        )""")
    con.execute("CREATE INDEX IF NOT EXISTS idx_fac ON bunrei_facility(nursery_ref, plan_type, age_class, month, item)")


def import_csv(csv_path: Path, db_path: Path, nursery_ref: str, source_note: str = "") -> dict:
    rows, warnings = [], []
    now = datetime.now(UTC).isoformat()
    with csv_path.open(encoding="utf-8") as f:
        for i, raw in enumerate(csv.DictReader(f), start=2):  # 2=ヘッダ次の行
            text = (raw.get("text") or "").strip()
            if not text:
                continue
            plan_type = (raw.get("plan_type") or "").strip()
            age_class = (raw.get("age_class") or "").strip()
            item = (raw.get("item") or "").strip()
            if plan_type and plan_type not in KNOWN_PLAN_TYPES:
                warnings.append(f"L{i}: 未知の plan_type '{plan_type}'")
            if age_class and age_class not in KNOWN_AGE:
                warnings.append(f"L{i}: 未知の age_class '{age_class}'")
            masked_text, masked = mask_pii(text)
            month_raw = (raw.get("month") or "").strip()
            rows.append(dict(
                id=_row_id(nursery_ref, plan_type, item, masked_text),
                nursery_ref=nursery_ref, visibility="facility_private",
                plan_type=plan_type or None, age_class=age_class or None,
                month=int(month_raw) if month_raw.isdigit() else None,
                item=item or None, ryoiki=(raw.get("ryoiki") or "").strip() or None,
                text=masked_text, text_provenance="facility",
                masked=1 if masked else 0, needs_review=1,
                source_note=source_note, imported_at=now))

    con = sqlite3.connect(db_path)
    ensure_table(con)
    con.executemany("""
        INSERT OR REPLACE INTO bunrei_facility
        (id, nursery_ref, visibility, plan_type, age_class, month, item, ryoiki,
         text, text_provenance, masked, needs_review, source_note, imported_at)
        VALUES (:id,:nursery_ref,:visibility,:plan_type,:age_class,:month,:item,:ryoiki,
                :text,:text_provenance,:masked,:needs_review,:source_note,:imported_at)
    """, rows)
    con.commit()
    masked_n = sum(r["masked"] for r in rows)
    con.close()
    return {"imported": len(rows), "masked_rows": masked_n, "warnings": warnings}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="自園計画を文例として取り込む")
    ap.add_argument("csv", type=Path)
    ap.add_argument("--db", type=Path, default=Path(__file__).resolve().parent / "facility.sqlite")
    ap.add_argument("--nursery", required=True, help="園の安定参照（例: ひかり保育園）")
    ap.add_argument("--note", default="", help="出所メモ（例: 2024年度クラスより）")
    a = ap.parse_args()
    result = import_csv(a.csv, a.db, a.nursery, a.note)
    print(f"取り込み: {result['imported']}件 / 自動マスク該当: {result['masked_rows']}件")
    if result["warnings"]:
        print("警告:")
        for w in result["warnings"]:
            print("  -", w)
    print("注意: 全行 needs_review=1。masked=1 でも人の確認は必須。")
