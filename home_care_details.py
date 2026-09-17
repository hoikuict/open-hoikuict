"""Optional structured home-care fields alongside the original free-text notes."""
import re

CARE_KEYS = ("bedtime", "wakeup_time", "breakfast_contents", "stool_consistency", "stool_count")
STOOL_LABELS = {"none": "なし", "normal": "普通", "hard": "硬い", "soft": "軟らかい", "watery": "水様", "mixed": "複数の性状", "unknown": "不明"}


def validate_home_care(values: dict) -> dict:
    result = {key: str(values.get(key) or "").strip() for key in CARE_KEYS}
    for key in ("bedtime", "wakeup_time"):
        if result[key] and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", result[key]):
            raise ValueError("就寝・起床は時・分で入力してください")
    if len(result["breakfast_contents"]) > 1000:
        raise ValueError("朝食の内容は1000文字以内で入力してください")
    if result["stool_consistency"] not in {"", *STOOL_LABELS}:
        raise ValueError("排便の性状を選択してください")
    count = result["stool_count"]
    if count and (not count.isascii() or not count.isdigit() or not 0 <= int(count) <= 99):
        raise ValueError("排便回数は0から99の整数で入力してください")
    if result["stool_consistency"] == "none":
        if count and int(count) != 0:
            raise ValueError("排便なしの場合、回数は0にしてください")
        result["stool_count"] = "0"
    elif count == "0" and result["stool_consistency"] not in {"", "unknown"}:
        raise ValueError("排便回数が0の場合、性状は「なし」または未入力にしてください")
    return result


def care_display_items(extra: dict | None) -> list[tuple[str, str]]:
    values = extra or {}
    items = []
    bedtime, wakeup = values.get("bedtime"), values.get("wakeup_time")
    if bedtime or wakeup:
        sleep = f"{bedtime or '未入力'} → {wakeup or '未入力'}"
        if bedtime and wakeup:
            try:
                minutes = lambda value: int(value[:2]) * 60 + int(value[3:])
                duration = (minutes(wakeup) - minutes(bedtime)) % (24 * 60)
                sleep += f"（{duration // 60}時間{duration % 60}分）"
            except (ValueError, TypeError):
                pass
        items.append(("就寝・起床", sleep))
    if values.get("breakfast_contents"):
        items.append(("朝食の内容", values["breakfast_contents"]))
    if values.get("stool_consistency"):
        items.append(("排便の性状（前日夕方から）", STOOL_LABELS.get(values["stool_consistency"], "不明")))
    if values.get("stool_count") not in (None, ""):
        items.append(("排便回数（前日夕方から）", str(values["stool_count"]) + "回"))
    return items
