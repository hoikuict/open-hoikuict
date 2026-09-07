"""Preview the actual child changes, including its destination family's profile."""
from family_csv import add_diff
from family_support import guardian_profiles_from_child
from models import ChildStatus, Family


def child_import_changes(session, result, number, child, family, classroom, row, *, birth_date, enrollment_date, withdrawal_date, status, verification_name, verification_name_type):
    columns = {"姓": "last_name", "名": "first_name", "姓カナ": "last_name_kana", "名カナ": "first_name_kana", "住所": "home_address", "電話番号": "home_phone"}
    fields = (*columns.values(), "birth_date", "enrollment_date", "withdrawal_date", "status", "family_id", "classroom_id", "registration_verification_name", "registration_verification_name_type")
    before = {key: getattr(child, key) if child else None for key in fields}
    after = dict(before)
    for column, key in columns.items():
        if row[column]:
            after[key] = row[column]
    for key, value in (("birth_date", birth_date), ("enrollment_date", enrollment_date), ("withdrawal_date", withdrawal_date), ("status", status)):
        if value is not None:
            after[key] = value
    if not child and status is None:
        after["status"] = ChildStatus.enrolled
    if row["家庭ID"] or row["家庭名"]:
        after["family_id"] = family.id if family else None
    if row["クラス名"]:
        after["classroom_id"] = classroom.id if classroom else None
    if verification_name and verification_name_type:
        after.update(registration_verification_name=verification_name, registration_verification_name_type=verification_name_type)
    elif not child:
        after.update(registration_verification_name=verification_name or f"{row['姓カナ']} {row['名カナ']}".strip(), registration_verification_name_type=verification_name_type or "kana")
    before["guardians_data"] = guardian_profiles_from_child(child) if child else []
    after["guardians_data"] = before["guardians_data"]
    target = session.get(Family, after["family_id"]) if after["family_id"] else None
    sync = bool(target and (target.guardian_profiles() or not before["guardians_data"]))
    if sync:
        after.update(home_address=target.home_address or after["home_address"], home_phone=target.home_phone or after["home_phone"], guardians_data=target.guardian_profiles())
    add_diff(result, number, "園児", child.id if child else "新規", before, after)
    return sync
