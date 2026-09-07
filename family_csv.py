"""Sparse family ledger updates. CSV never binds accounts or grants child access."""
from copy import deepcopy
import re
import unicodedata

from fastapi import HTTPException
from sqlmodel import select

from family_support import normalize_guardians_data
from models import Child, Family, ParentAccount


GUARDIAN_COLUMNS = (
    ("姓", "last_name"), ("名", "first_name"),
    ("姓カナ", "last_name_kana"), ("名カナ", "first_name_kana"),
    ("続柄", "relationship"), ("メールアドレス", "email"),
    ("電話番号", "phone"), ("勤務先", "workplace"),
    ("勤務先住所", "workplace_address"), ("勤務先電話番号", "workplace_phone"),
)
GUARDIAN_HEADERS = tuple(f"保護者{number}{label}" for number in "①②" for label, _ in GUARDIAN_COLUMNS)


def identity(value):
    return "".join(unicodedata.normalize("NFKC", str(value or "")).split())


def valid_email(value):
    return len(value) <= 255 and re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value) is not None


def family_csv_values(family):
    profiles = {item["order"]: item for item in normalize_guardians_data(family.guardian_profiles())}
    return [str(profiles.get(order, {}).get(key) or "") for order in (1, 2) for _, key in GUARDIAN_COLUMNS]


def plan_family(session, family, row):
    """Return complete proposed data without changing any mapped objects."""
    from data_transfer_service import TransferMessage

    errors = []

    def fail(column, message):
        errors.append(TransferMessage(0, column, "", message))

    if family is None and not row.get("ID") and any(row.get(h) for h in GUARDIAN_HEADERS):
        if session.exec(select(Family).where(Family.family_name == row["家庭名"])).first():
            fail("ID", "同名の家庭があります。エクスポートした家庭IDを指定してください。")
    try:
        raw_profiles = deepcopy(family.guardian_profiles()) if family else []
        for profile in raw_profiles:
            if not profile.get("last_name") or not profile.get("first_name"):
                raise ValueError("incomplete stored guardian")
            if int(profile.get("order", 0)) < 1:
                raise ValueError("invalid order")
            account_id = profile.get("parent_account_id")
            if account_id is not None and (isinstance(account_id, bool) or not str(account_id).isdigit() or int(account_id) < 1):
                raise ValueError("invalid account binding")
        profiles = normalize_guardians_data(raw_profiles)
    except (HTTPException, ValueError, TypeError):
        fail("保護者", "保護者番号の重複、氏名、アカウント紐付けを家庭の編集画面で確認してください。")
        profiles = []
    by_order = {item["order"]: item for item in profiles}
    for order, number in enumerate("①②", 1):
        values = {key: row.get(f"保護者{number}{label}", "") for label, key in GUARDIAN_COLUMNS}
        if not any(values.values()):
            continue
        if not values["last_name"] or not values["first_name"]:
            fail(f"保護者{number}姓", "保護者の情報を取り込む行では、姓と名の両方を入力してください。")
            continue
        previous = by_order.get(order)
        if previous and any(identity(values[key]) != identity(previous.get(key)) for key in ("last_name", "first_name")):
            fail(f"保護者{number}姓", "登録済みの保護者と氏名が異なります。改姓・入れ替えは家庭の編集画面で行ってください。")
            continue
        if values["email"] and not valid_email(values["email"]):
            fail(f"保護者{number}メールアドレス", "メールアドレスの形式を確認してください。")
        merged = deepcopy(previous or {"order": order, "relationship": "保護者"})
        merged.update({key: value for key, value in values.items() if value})
        by_order[order] = merged

    profiles = normalize_guardians_data(list(by_order.values()))
    seen_accounts = set()
    for profile in profiles:
        account_id = profile.get("parent_account_id")
        if not account_id:
            continue
        account = session.get(ParentAccount, account_id)
        if not account or not family or account.family_id != family.id or account_id in seen_accounts:
            fail("保護者アカウント", "紐付けが不整合です。家庭の編集画面で確認してください。")
            continue
        seen_accounts.add(account_id)
        # Compare the contact address, never PasswordCredential.login_id.
        if profile.get("email") and profile["email"] != account.email:
            fail("メールアドレス", "アカウントの連絡先メールはCSVで変更できません。保護者アカウント画面で確認してください。")
        profile["email"] = account.email
        # A missing ledger value must not erase a contact held only by the account.
        for key in ("phone", "workplace", "workplace_address", "workplace_phone"):
            if not profile.get(key):
                profile[key] = getattr(account, key) or ""

    payload = {
        "family_name": row["家庭名"] or (family.family_name if family else ""),
        "home_address": row["住所"] or (family.home_address if family else "") or "",
        "home_phone": row["電話番号"] or (family.home_phone if family else "") or "",
        "guardians_data": profiles,
    }
    if family and profiles:
        proposed = {p["order"]: p for p in profiles}
        for child in session.exec(select(Child).where(Child.family_id == family.id)).all():
            for guardian in child.guardians:
                profile = proposed.get(guardian.order)
                if not profile or any(identity(getattr(guardian, key)) != identity(profile.get(key)) for key in ("last_name", "first_name")):
                    fail("園児の保護者", f"園児ID {child.id} に家庭と異なる保護者情報があります。家庭の編集画面で情報を揃えてから取り込んでください。")
                    break
    return payload, errors


def add_diff(result, row_number, entity, entity_id, before, after):
    """Display values only in the protected preview; audit logs store field names."""
    for key in sorted(set(before) | set(after)):
        old, new = before.get(key), after.get(key)
        if key == "guardians_data":
            old_profiles = {p["order"]: p for p in old or []}
            new_profiles = {p["order"]: p for p in new or []}
            for order in sorted(set(old_profiles) | set(new_profiles)):
                add_diff(result, row_number, entity, entity_id,
                         {f"保護者{order} {label}": old_profiles.get(order, {}).get(field) for label, field in (*GUARDIAN_COLUMNS, ("アカウントID", "parent_account_id"))},
                         {f"保護者{order} {label}": new_profiles.get(order, {}).get(field) for label, field in (*GUARDIAN_COLUMNS, ("アカウントID", "parent_account_id"))})
            continue
        if old != new and not (old in (None, "") and new in (None, "")):
            label = {"family_name": "家庭名", "home_address": "住所", "home_phone": "自宅電話番号",
                     "display_name": "表示名", "email": "メールアドレス", "phone": "電話番号",
                     "workplace": "勤務先", "workplace_address": "勤務先住所", "workplace_phone": "勤務先電話番号",
                     "staff_sort_order": "表示順", "family_id": "家庭ID", "classroom_id": "クラスID",
                     "last_name": "姓", "first_name": "名", "last_name_kana": "姓カナ", "first_name_kana": "名カナ",
                     "birth_date": "生年月日", "enrollment_date": "入園日", "withdrawal_date": "退園日", "status": "在園状態"}.get(key, key)
            result.changes.append({"row": row_number, "entity": entity, "id": entity_id,
                                   "field": key, "label": label, "before": old, "after": new})


def preview_family_changes(session, result, row_number, family, payload):
    from family_support import guardian_account_values, guardian_profiles_from_child

    before = {key: getattr(family, key) if family else "" for key in ("family_name", "home_address", "home_phone")}
    before["guardians_data"] = family.guardian_profiles() if family else []
    add_diff(result, row_number, "家庭", family.id if family else "新規", before, payload)
    if not family:
        return
    for child in session.exec(select(Child).where(Child.family_id == family.id)).all():
        add_diff(result, row_number, "園児", child.id,
                 {"home_address": child.home_address, "home_phone": child.home_phone,
                  "guardians_data": guardian_profiles_from_child(child)},
                 {"home_address": payload["home_address"] or child.home_address,
                  "home_phone": payload["home_phone"] or child.home_phone,
                  "guardians_data": payload["guardians_data"] or guardian_profiles_from_child(child)})
    proposed = Family(home_address=payload["home_address"])
    for profile in payload["guardians_data"]:
        if not profile.get("parent_account_id"):
            continue
        account = session.get(ParentAccount, profile["parent_account_id"])
        values = guardian_account_values(proposed, profile)
        values.pop("registration_verification_name")
        values.pop("registration_verification_name_type")
        if account.home_address and account.home_address.strip() != (family.home_address or "").strip():
            values["home_address"] = account.home_address
        add_diff(result, row_number, "保護者アカウント", account.id,
                 {key: getattr(account, key) for key in values}, values)
