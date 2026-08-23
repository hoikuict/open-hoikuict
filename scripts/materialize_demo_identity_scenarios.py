from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parents[1]
FULL_DIR = BASE_DIR / "demo_data" / "full"
IMPORT_DIR = BASE_DIR / "demo_data" / "import_compatible"

FOREIGN_SCENARIO_FAMILY_IDS = frozenset({4, 8, 12, 17, 28, 39, 50, 63, 79})

FAMILY_PERSONAS: dict[int, str] = {
    4: "Garcia家",
    8: "Moreau・木村家",
    12: "Chen家",
    17: "Nguyen家",
    28: "Patel家",
    39: "O'Connor・小林家",
    50: "Müller家",
    63: "Santos家",
    79: "Hassan家",
}

ORIGINAL_FAMILY_NAMES: dict[int, str] = {
    4: "遠藤家",
    8: "木村家",
    12: "佐藤家",
    17: "中村家",
    28: "長谷川家",
    39: "小林家",
    50: "藤井家",
    63: "井上家",
    79: "林家",
}

CHILD_PERSONAS: dict[int, dict[str, str]] = {
    60: {"last_name": "Garcia", "first_name": "Sofia", "last_name_kana": "ガルシア", "first_name_kana": "ソフィア", "verification": "Sofia Garcia"},
    7: {"last_name": "Garcia", "first_name": "Mateo", "last_name_kana": "ガルシア", "first_name_kana": "マテオ", "verification": "Mateo Garcia"},
    61: {"last_name": "Moreau", "first_name": "Sota", "last_name_kana": "モロー", "first_name_kana": "ソウタ", "verification": "Sota Moreau"},
    3: {"last_name": "Moreau", "first_name": "Tsumugi", "last_name_kana": "モロー", "first_name_kana": "ツムギ", "verification": "Tsumugi Moreau"},
    63: {"last_name": "Chen", "first_name": "Emma", "last_name_kana": "チェン", "first_name_kana": "エマ", "verification": "Emma Chen"},
    9: {"last_name": "Chen", "first_name": "Leo", "last_name_kana": "チェン", "first_name_kana": "レオ", "verification": "Leo Chen"},
    11: {"last_name": "Nguyen", "first_name": "Linh", "last_name_kana": "グエン", "first_name_kana": "リン", "verification": "Linh Nguyen"},
    28: {"last_name": "Patel", "first_name": "Anaya", "last_name_kana": "パテル", "first_name_kana": "アナヤ", "verification": "Anaya Patel"},
    45: {"last_name": "O'Connor", "first_name": "Haruto", "last_name_kana": "オコナー", "first_name_kana": "ハルト", "verification": "Haruto O'Connor"},
    56: {"last_name": "Müller", "first_name": "Mia", "last_name_kana": "ミュラー", "first_name_kana": "ミア", "verification": "Mia Müller"},
    75: {"last_name": "Santos", "first_name": "Gabriela", "last_name_kana": "サントス", "first_name_kana": "ガブリエラ", "verification": "Gabriela Santos"},
    95: {"last_name": "Hassan", "first_name": "Layla", "last_name_kana": "ハッサン", "first_name_kana": "ライラ", "verification": "Layla Hassan"},
}

PARENT_PERSONAS: dict[int, dict[str, str]] = {
    7: {"display_name": "Elena Garcia", "verification": "Elena Garcia", "type": "latin"},
    8: {"display_name": "Carlos Garcia", "verification": "Carlos Garcia", "type": "latin"},
    14: {"display_name": "木村 美穂", "verification": "キムラ ミホ", "type": "kana"},
    15: {"display_name": "Alexandre Moreau", "verification": "Alexandre Moreau", "type": "latin"},
    22: {"display_name": "Mei Chen", "verification": "Mei Chen", "type": "latin"},
    23: {"display_name": "Jun Chen", "verification": "Jun Chen", "type": "latin"},
    31: {"display_name": "Lan Nguyen", "verification": "Lan Nguyen", "type": "latin"},
    32: {"display_name": "Minh Nguyen", "verification": "Minh Nguyen", "type": "latin"},
    52: {"display_name": "Priya Patel", "verification": "Priya Patel", "type": "latin"},
    72: {"display_name": "小林 奈々", "verification": "コバヤシ ナナ", "type": "kana"},
    73: {"display_name": "Daniel O'Connor", "verification": "Daniel O'Connor", "type": "latin"},
    92: {"display_name": "Anna Müller", "verification": "Anna Müller", "type": "latin"},
    93: {"display_name": "Lukas Müller", "verification": "Lukas Müller", "type": "latin"},
    117: {"display_name": "Ana-Maria Santos", "verification": "Ana-Maria Santos", "type": "latin"},
    146: {"display_name": "Amina Hassan", "verification": "Amina Hassan", "type": "latin"},
    147: {"display_name": "Omar Hassan", "verification": "Omar Hassan", "type": "latin"},
}

GUARDIAN_PERSONAS_BY_PHONE: dict[str, dict[str, str]] = {
    "090-0001-0004": {"last_name": "Garcia", "first_name": "Elena", "last_name_kana": "ガルシア", "first_name_kana": "エレナ"},
    "090-0002-0004": {"last_name": "Garcia", "first_name": "Carlos", "last_name_kana": "ガルシア", "first_name_kana": "カルロス"},
    "090-0002-0008": {"last_name": "Moreau", "first_name": "Alexandre", "last_name_kana": "モロー", "first_name_kana": "アレクサンドル"},
    "090-0001-0012": {"last_name": "Chen", "first_name": "Mei", "last_name_kana": "チェン", "first_name_kana": "メイ"},
    "090-0002-0012": {"last_name": "Chen", "first_name": "Jun", "last_name_kana": "チェン", "first_name_kana": "ジュン"},
    "090-0001-0017": {"last_name": "Nguyen", "first_name": "Lan", "last_name_kana": "グエン", "first_name_kana": "ラン"},
    "090-0002-0017": {"last_name": "Nguyen", "first_name": "Minh", "last_name_kana": "グエン", "first_name_kana": "ミン"},
    "090-0001-0028": {"last_name": "Patel", "first_name": "Priya", "last_name_kana": "パテル", "first_name_kana": "プリヤ"},
    "090-0002-0028": {"last_name": "Patel", "first_name": "Ravi", "last_name_kana": "パテル", "first_name_kana": "ラヴィ"},
    "090-0002-0039": {"last_name": "O'Connor", "first_name": "Daniel", "last_name_kana": "オコナー", "first_name_kana": "ダニエル"},
    "090-0001-0050": {"last_name": "Müller", "first_name": "Anna", "last_name_kana": "ミュラー", "first_name_kana": "アンナ"},
    "090-0002-0050": {"last_name": "Müller", "first_name": "Lukas", "last_name_kana": "ミュラー", "first_name_kana": "ルーカス"},
    "090-0001-0063": {"last_name": "Santos", "first_name": "Ana-Maria", "last_name_kana": "サントス", "first_name_kana": "アナマリア"},
    "090-0002-0063": {"last_name": "Santos", "first_name": "Paulo", "last_name_kana": "サントス", "first_name_kana": "パウロ"},
    "090-0003-0063": {"last_name": "Santos", "first_name": "Rosa", "last_name_kana": "サントス", "first_name_kana": "ローザ"},
    "090-0001-0079": {"last_name": "Hassan", "first_name": "Amina", "last_name_kana": "ハッサン", "first_name_kana": "アミナ"},
    "090-0002-0079": {"last_name": "Hassan", "first_name": "Omar", "last_name_kana": "ハッサン", "first_name_kana": "オマル"},
}


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        return list(reader.fieldnames or ()), list(reader)


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _insert_after(fieldnames: list[str], after: str, additions: tuple[str, ...]) -> list[str]:
    result = [name for name in fieldnames if name not in additions]
    position = result.index(after) + 1
    result[position:position] = list(additions)
    return result


def _materialize_full_data() -> tuple[dict[tuple[str, str, str], dict[str, str]], dict[str, dict[str, str]]]:
    guardian_path = FULL_DIR / "guardians.csv"
    guardian_fields, guardians = _read_csv(guardian_path)
    for row in guardians:
        persona = GUARDIAN_PERSONAS_BY_PHONE.get(row["phone"])
        if persona:
            row.update(persona)
    _write_csv(guardian_path, guardian_fields, guardians)

    family_path = FULL_DIR / "families.csv"
    family_fields, families = _read_csv(family_path)
    for row in families:
        family_id = int(row["id"])
        if family_id in FAMILY_PERSONAS:
            row["family_name"] = FAMILY_PERSONAS[family_id]

    child_path = FULL_DIR / "children.csv"
    child_fields, children = _read_csv(child_path)
    child_fields = _insert_after(
        child_fields,
        "first_name_kana",
        ("registration_verification_name", "registration_verification_name_type"),
    )
    child_lookup: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in children:
        old_key = (row["last_name_kana"], row["first_name_kana"], row["birth_date"])
        persona = CHILD_PERSONAS.get(int(row["id"]))
        if persona:
            row.update({key: value for key, value in persona.items() if key != "verification"})
            row["registration_verification_name"] = persona["verification"]
            row["registration_verification_name_type"] = "latin"
        else:
            row["registration_verification_name"] = f"{row['last_name_kana']} {row['first_name_kana']}"
            row["registration_verification_name_type"] = "kana"
        child_lookup[old_key] = row
        child_lookup[(row["last_name_kana"], row["first_name_kana"], row["birth_date"])] = row
    _write_csv(child_path, child_fields, children)

    family_id_by_child_id = {
        row["id"]: row["family_id"]
        for row in children
    }
    guardian_fields_for_profile = (
        "order",
        "last_name",
        "first_name",
        "last_name_kana",
        "first_name_kana",
        "relationship",
        "phone",
        "workplace",
        "workplace_address",
        "workplace_phone",
    )
    profiles_by_family: dict[str, list[dict[str, str]]] = {}
    seen_phones_by_family: dict[str, set[str]] = {}
    for guardian in guardians:
        family_id = family_id_by_child_id[guardian["child_id"]]
        phone = guardian["phone"]
        seen_phones = seen_phones_by_family.setdefault(family_id, set())
        if phone in seen_phones:
            continue
        seen_phones.add(phone)
        profiles_by_family.setdefault(family_id, []).append(
            {field: guardian.get(field, "") for field in guardian_fields_for_profile}
        )
    for profiles in profiles_by_family.values():
        profiles.sort(key=lambda profile: int(profile.get("order") or 99))
    for row in families:
        if "shared_profile" in row:
            row["shared_profile"] = json.dumps(
                {"guardians": profiles_by_family.get(row["id"], [])},
                ensure_ascii=False,
                separators=(",", ":"),
            )
    _write_csv(family_path, family_fields, families)

    parent_path = FULL_DIR / "parent_accounts.csv"
    parent_fields, parents = _read_csv(parent_path)
    parent_fields = _insert_after(
        parent_fields,
        "display_name",
        ("registration_verification_name", "registration_verification_name_type"),
    )
    guardian_by_phone = {row["phone"]: row for row in guardians}
    parent_by_email: dict[str, dict[str, str]] = {}
    for row in parents:
        persona = PARENT_PERSONAS.get(int(row["id"]))
        if persona:
            row["display_name"] = persona["display_name"]
            row["registration_verification_name"] = persona["verification"]
            row["registration_verification_name_type"] = persona["type"]
        else:
            guardian = guardian_by_phone.get(row["phone"])
            if not guardian:
                raise ValueError(f"保護者のカナ氏名を解決できません: {row['email']}")
            row["registration_verification_name"] = (
                f"{guardian['last_name_kana']} {guardian['first_name_kana']}"
            )
            row["registration_verification_name_type"] = "kana"
        parent_by_email[row["email"]] = row
    _write_csv(parent_path, parent_fields, parents)
    return child_lookup, parent_by_email


def _materialize_import_data(
    child_lookup: dict[tuple[str, str, str], dict[str, str]],
    parent_by_email: dict[str, dict[str, str]],
) -> None:
    children_by_family_and_birth = {
        (row["family_id"], row["birth_date"]): row
        for row in {id(row): row for row in child_lookup.values()}.values()
    }
    child_path = IMPORT_DIR / "children.csv"
    child_fields, children = _read_csv(child_path)
    child_fields = _insert_after(child_fields, "名カナ", ("照合用氏名", "照合用氏名種別"))
    for row in children:
        source = child_lookup[(row["姓カナ"], row["名カナ"], row["生年月日"])]
        row.update(
            {
                "姓": source["last_name"],
                "名": source["first_name"],
                "姓カナ": source["last_name_kana"],
                "名カナ": source["first_name_kana"],
                "照合用氏名": source["registration_verification_name"],
                "照合用氏名種別": source["registration_verification_name_type"],
                "家庭名": FAMILY_PERSONAS.get(int(source["family_id"]), row["家庭名"]),
            }
        )
    _write_csv(child_path, child_fields, children)

    parent_path = IMPORT_DIR / "parent_accounts.csv"
    parent_fields, parents = _read_csv(parent_path)
    parent_fields = _insert_after(parent_fields, "表示名", ("照合用氏名", "照合用氏名種別"))
    for row in parents:
        source = parent_by_email[row["メールアドレス"]]
        row["表示名"] = source["display_name"]
        row["照合用氏名"] = source["registration_verification_name"]
        row["照合用氏名種別"] = source["registration_verification_name_type"]
        row["家庭名"] = FAMILY_PERSONAS.get(int(source["family_id"]), row["家庭名"])
    _write_csv(parent_path, parent_fields, parents)

    family_path = IMPORT_DIR / "families.csv"
    family_fields, families = _read_csv(family_path)
    replacements = {
        ORIGINAL_FAMILY_NAMES[family_id]: family_name
        for family_id, family_name in FAMILY_PERSONAS.items()
    }
    replacements.update({name: name for name in FAMILY_PERSONAS.values()})
    for row in families:
        row["家庭名"] = replacements.get(row["家庭名"], row["家庭名"])
    _write_csv(family_path, family_fields, families)

    link_path = IMPORT_DIR / "parent_child_links.csv"
    link_fields, links = _read_csv(link_path)
    for row in links:
        parent = parent_by_email[row["保護者メールアドレス"]]
        source = children_by_family_and_birth[
            (parent["family_id"], row["園児生年月日"])
        ]
        row["園児姓カナ"] = source["last_name_kana"]
        row["園児名カナ"] = source["first_name_kana"]
    _write_csv(link_path, link_fields, links)


def _materialize_sqlite_template(db_path: Path) -> None:
    if not db_path.is_file():
        raise FileNotFoundError(db_path)
    _, families = _read_csv(FULL_DIR / "families.csv")
    _, children = _read_csv(FULL_DIR / "children.csv")
    _, guardians = _read_csv(FULL_DIR / "guardians.csv")
    _, parents = _read_csv(FULL_DIR / "parent_accounts.csv")

    connection = sqlite3.connect(db_path)
    try:
        for table_name in ("children", "parent_accounts"):
            columns = {
                row[1]
                for row in connection.execute(f"PRAGMA table_info({table_name})")
            }
            for column_name, column_type in (
                ("registration_verification_name", "VARCHAR(200)"),
                ("registration_verification_name_type", "VARCHAR(16)"),
            ):
                if column_name not in columns:
                    connection.execute(
                        f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"
                    )

        for row in families:
            connection.execute(
                "UPDATE families SET family_name = ?, shared_profile = ? WHERE id = ?",
                (row["family_name"], row["shared_profile"], int(row["id"])),
            )
        for row in children:
            connection.execute(
                "UPDATE children SET last_name = ?, first_name = ?, "
                "last_name_kana = ?, first_name_kana = ?, "
                "registration_verification_name = ?, "
                "registration_verification_name_type = ? WHERE id = ?",
                (
                    row["last_name"],
                    row["first_name"],
                    row["last_name_kana"],
                    row["first_name_kana"],
                    row["registration_verification_name"],
                    row["registration_verification_name_type"],
                    int(row["id"]),
                ),
            )
        for row in guardians:
            connection.execute(
                "UPDATE guardians SET last_name = ?, first_name = ?, "
                "last_name_kana = ?, first_name_kana = ? WHERE id = ?",
                (
                    row["last_name"],
                    row["first_name"],
                    row["last_name_kana"],
                    row["first_name_kana"],
                    int(row["id"]),
                ),
            )
        for row in parents:
            connection.execute(
                "UPDATE parent_accounts SET display_name = ?, "
                "registration_verification_name = ?, "
                "registration_verification_name_type = ? WHERE id = ?",
                (
                    row["display_name"],
                    row["registration_verification_name"],
                    row["registration_verification_name_type"],
                    int(row["id"]),
                ),
            )

        latin_family_count = connection.execute(
            "SELECT COUNT(DISTINCT family_id) FROM ("
            "SELECT family_id FROM children WHERE registration_verification_name_type = 'latin' "
            "UNION ALL "
            "SELECT family_id FROM parent_accounts WHERE registration_verification_name_type = 'latin'"
            ")"
        ).fetchone()[0]
        if latin_family_count != len(FOREIGN_SCENARIO_FAMILY_IDS):
            raise ValueError(
                f"SQLiteデモの外国籍想定家庭数が不正です: {latin_family_count}"
            )
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise ValueError(f"SQLiteデモに外部キー違反があります: {violations[:5]}")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--sqlite-template",
        type=Path,
        help="CSVと同じ氏名シナリオを反映する既存SQLiteデモテンプレート",
    )
    args = parser.parse_args()
    child_lookup, parent_by_email = _materialize_full_data()
    _materialize_import_data(child_lookup, parent_by_email)
    if args.sqlite_template:
        _materialize_sqlite_template(args.sqlite_template.resolve())
    print(
        "Materialized foreign-household demo identities: "
        f"{len(FOREIGN_SCENARIO_FAMILY_IDS)} families"
    )


if __name__ == "__main__":
    main()
