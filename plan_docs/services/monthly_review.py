"""Planning fields required only when requesting review of a monthly sheet."""
from copy import deepcopy

from models import Classroom
from .monthly_library import COLUMNS, DOMAINS, PERSONAL, field_definitions, new_sheet


class MonthlyReviewIncompleteError(ValueError):
    def __init__(self, missing):
        super().__init__("未記入の計画欄があります。入力してからレビュー依頼してください。")
        self.missing = missing


def review_fields(sheet, target_month):
    definitions = field_definitions(sheet, target_month)
    result = [{"key": key, "label": definitions[key]["label"]}
              for key in ("common:goal", "common:home")]
    if sheet["age"] < 3:
        for child in sheet["children"]:
            result.extend({"key": f"{child['ref']}:{key}", "label": f"{child['name']} / {label}"}
                          for key, label in PERSONAL if key != "review")
    else:
        keys = [f"group:{domain}:{column}" for domain, _ in DOMAINS for column, _ in COLUMNS]
        keys.append("group:food")
        result.extend({"key": key, "label": definitions[key]["label"]} for key in keys)
    return result


def missing_fields(sheet, target_month, owner_name):
    missing = [] if (owner_name or "").strip() else [{"key": "@owner", "label": "担任名"}]
    missing.extend(item for item in review_fields(sheet, target_month)
                   if not (sheet["fields"].get(item["key"], {}).get("body") or "").strip())
    return missing


def validate_review(session, document):
    """Run under the document's write lock, before revisions or notifications.

    Include new enrolments just as the editor does, retaining historical members.
    Validation never rewrites the saved draft or its roster.
    """
    sheet = deepcopy(document.monthly_sheet)
    if sheet["age"] < 3:
        classroom = session.get(Classroom, sheet["classroom_id"])
        if classroom is not None:
            known = {child["ref"] for child in sheet["children"]}
            roster = new_sheet(session, classroom, document.target_month, sheet["age"])["children"]
            sheet["children"].extend(child for child in roster if child["ref"] not in known)
    missing = missing_fields(sheet, document.target_month, document.owner_name)
    if missing:
        raise MonthlyReviewIncompleteError(missing)
