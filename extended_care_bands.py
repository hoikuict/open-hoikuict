"""Explicit, same-day fee bands. Existing rules opt in only on an explicit save."""
from __future__ import annotations

from datetime import date
import hashlib
import json
import re

SIDES = {"morning": "前延長", "evening": "あと延長"}


def minutes(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise ValueError("時刻は HH:MM 形式で入力してください。")
    return int(value[:2]) * 60 + int(value[3:])


def integer(value, label, minimum=0, maximum=10000000):
    if isinstance(value, bool) or not re.fullmatch(r"\d+", str(value)):
        raise ValueError(f"{label}は整数で入力してください。")
    result = int(value)
    if not minimum <= result <= maximum:
        raise ValueError(f"{label}は{minimum}〜{maximum}で入力してください。")
    return result


def day(value, label):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{label}を正しく入力してください。") from None


def normalize_plan(raw):
    if not isinstance(raw, dict):
        raise ValueError("設定の形式が正しくありません。")
    p = {key: raw.get(key, "") for key in ("name", "from", "to", "normalStart", "normalEnd", "cap")}
    if any(not isinstance(v, str) for v in p.values()):
        raise ValueError("設定の形式が正しくありません。")
    p["name"] = p["name"].strip()
    if not 1 <= len(p["name"]) <= 100:
        raise ValueError("ルール名は1〜100文字で入力してください。")
    start_day = day(p["from"], "適用開始日")
    if p["to"] and day(p["to"], "適用終了日") < start_day:
        raise ValueError("適用終了日は適用開始日以降にしてください。")
    start, end = minutes(p["normalStart"]), minutes(p["normalEnd"])
    if start >= end:
        raise ValueError("通常保育の終了は開始より後にしてください。")
    if p["cap"]:
        p["cap"] = str(integer(p["cap"], "日別上限額"))
    if type(raw.get("active")) is not bool:
        raise ValueError("有効・無効を指定してください。")
    p["active"] = raw["active"]
    for side, label in SIDES.items():
        enabled = raw.get(side + "Enabled")
        if type(enabled) is not bool:
            raise ValueError(label + "を使用するか選択してください。")
        p[side + "Enabled"] = enabled
        try:
            grace = integer(raw.get(side + "Grace", "0"), label + "の猶予", 0, 120)
        except ValueError:
            if enabled:
                raise
            grace = 0
        p[side + "Grace"] = str(grace)
        rows = raw.get(side + "Bands", [])
        if not isinstance(rows, list) or len(rows) > 24 or (enabled and not rows):
            raise ValueError(label + "の時間帯を1〜24件で設定してください。")
        clean = []
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                raise ValueError(label + "の時間帯が不正です。")
            item = {k: str(row.get(k, "")) for k in ("start", "end", "mode", "unit", "price")}
            item["id"] = f"{side}{i + 1}"
            if any(len(v) > 32 for v in item.values()):
                raise ValueError(label + "の入力が長すぎます。")
            if enabled:
                a, b = minutes(item["start"]), minutes(item["end"])
                if a >= b or (side == "morning" and b > start) or (side == "evening" and a < end):
                    raise ValueError(label + "の開始・終了を通常保育時間の外に設定してください。")
                if item["mode"] not in ("unit", "flat"):
                    raise ValueError(label + "の料金方式を選択してください。")
                item["unit"] = str(integer(item["unit"], label + "の課金単位", 1, 120)) if item["mode"] == "unit" else "1"
                item["price"] = str(integer(item["price"], label + "の料金"))
            clean.append(item)
        if enabled:
            clean.sort(key=lambda x: x["start"])
            for left, right in zip(clean, clean[1:]):
                if left["end"] != right["start"]:
                    raise ValueError(label + "の時間帯に重複または空白があります。無料の時間は0円で設定してください。")
            if (side == "morning" and clean[-1]["end"] != p["normalStart"]) or (side == "evening" and clean[0]["start"] != p["normalEnd"]):
                raise ValueError(label + "を通常保育時間の境界につなげてください。")
        p[side + "Bands"] = clean
    return p


def evaluate_plan(plan, target_date, arrival, departure):
    p = normalize_plan(plan)
    if not p["active"] or target_date < p["from"] or (p["to"] and target_date > p["to"]):
        raise ValueError("利用日に有効な料金ルールではありません。")
    day(target_date, "利用日")
    a, b = minutes(arrival), minutes(departure)
    if a >= b:
        raise ValueError("同じ日の登園より後の降園時刻で確認してください。日付をまたぐ利用は要確認です。")
    start, end = minutes(p["normalStart"]), minutes(p["normalEnd"])
    lines, warnings = [], []
    clock = lambda n: f"{n // 60:02d}:{n % 60:02d}"
    for side, label in SIDES.items():
        enabled = p[side + "Enabled"]
        grace = int(p[side + "Grace"]) if enabled else 0
        lo, hi = (a, min(b, start - grace)) if side == "morning" else (max(a, end + grace), b)
        duration = max(0, hi - lo)
        if not duration:
            continue
        if not enabled:
            warnings.append(f"{label}を使用しない設定ですが、通常保育の外に{duration}分の利用があります。")
            continue
        covered = 0
        for i, band in enumerate(p[side + "Bands"]):
            left, right = max(lo, minutes(band["start"])), min(hi, minutes(band["end"]))
            used = max(0, right - left)
            if not used:
                continue
            unit, price = int(band["unit"]), int(band["price"])
            units = 1 if band["mode"] == "flat" else (used + unit - 1) // unit
            covered += used
            lines.append(dict(side=side, label=f"{label}{i+1}", range=f"{band['start']}〜{band['end']}",
                              usedRange=f"{clock(left)}〜{clock(right)}", used=used, units=units,
                              billableMinutes=used if band["mode"] == "flat" else units * unit,
                              method="時間帯ごと定額" if band["mode"] == "flat" else f"{unit}分ごと（切り上げ）",
                              price=price, amount=units * price))
        if covered < duration:
            warnings.append(f"{label}の設定時間帯の外に{duration-covered}分の利用があります。扱いを確認してください。")
    subtotal = sum(row["amount"] for row in lines)
    cap = int(p["cap"]) if p["cap"] else None
    total = None if warnings else min(subtotal, cap) if cap is not None else subtotal
    return dict(errors=[], warnings=warnings, lines=lines, subtotal=subtotal, cap=cap,
                total=total, capped=total is not None and total < subtotal)


def revision(rule):
    return hashlib.sha256(rule.model_dump_json().encode()).hexdigest()


def rule_plan(rule):
    if rule.fee_bands_json is not None:
        p = json.loads(rule.fee_bands_json)
    else:
        # Missing outer bounds are deliberately left for the user to specify.
        p = dict(morningBands=[], eveningBands=[])
        for side in SIDES:
            if getattr(rule, side + "_enabled"):
                unit = getattr(rule, side + "_rounding_minutes")
                price = getattr(rule, side + "_unit_price")
                p[side + "Bands"] = [dict(id=side + "1", mode="unit", unit=str(unit if unit is not None else rule.rounding_minutes),
                    price=str(price if price is not None else rule.unit_price),
                    start="" if side == "morning" else rule.normal_end_time or "",
                    end=rule.normal_start_time or "" if side == "morning" else "")]
    p.update(id=rule.id, revision=revision(rule), existingCalculation=rule.fee_bands_json is None,
             name=rule.name, **{"from": rule.effective_from.isoformat(), "to": rule.effective_to.isoformat() if rule.effective_to else ""},
             active=rule.is_active, normalStart=rule.normal_start_time or "", normalEnd=rule.normal_end_time or "",
             morningEnabled=rule.morning_enabled, eveningEnabled=rule.evening_enabled,
             morningGrace=str(rule.morning_grace_minutes),
             eveningGrace=str(rule.evening_grace_minutes if rule.evening_grace_minutes is not None else rule.grace_minutes),
             cap=str(rule.daily_cap_amount) if rule.daily_cap_amount is not None else "")
    return p


def rule_values(p, category):
    values = dict(name=p["name"], effective_from=day(p["from"], "適用開始日"), effective_to=day(p["to"], "適用終了日") if p["to"] else None,
                  start_time=p["normalEnd"], normal_start_time=p["normalStart"], normal_end_time=p["normalEnd"],
                  care_time_category=category, is_active=p["active"],
                  daily_cap_amount=int(p["cap"]) if p["cap"] else None, fee_bands_json=json.dumps(p, ensure_ascii=False))
    for side in SIDES:
        rows = p[side + "Bands"] if p[side + "Enabled"] else []
        values.update({side + "_enabled": p[side + "Enabled"], side + "_grace_minutes": int(p[side + "Grace"]),
                       side + "_rounding_minutes": int(rows[0]["unit"]) if rows else 1,
                       side + "_unit_price": int(rows[0]["price"]) if rows else 0})
    values.update(grace_minutes=values["evening_grace_minutes"], rounding_minutes=values["evening_rounding_minutes"], unit_price=values["evening_unit_price"])
    return values
