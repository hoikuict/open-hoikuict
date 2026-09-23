"""Create an initial ledger in one transaction, without accounts or permissions."""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from io import BytesIO
import hashlib
import json
import math
from pathlib import Path
import posixpath
import re
from xml.etree import ElementTree as ET
from zipfile import BadZipFile, ZipFile

from sqlalchemy import text
from sqlmodel import Session, select

from data_transfer_service import TransferMessage
from family_support import set_family_guardian_profiles
from import_state import audit_changes, ledger_state, state_revision
from models import Child, ChildSex, ChildStatus, Classroom, DataTransferLog, Family, Guardian

FIELDS = json.loads((Path(__file__).parent / "static/initial-ledger-fields.json").read_text(encoding="utf-8"))
HEADERS = [item["key"] for item in FIELDS]
MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_ROWS = 1000
DATASET = "initial_ledger"
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
GUARDIAN_KEYS = dict(zip(
    ["姓", "名", "姓カナ", "名カナ", "続柄", "メールアドレス", "電話番号", "勤務先", "勤務先住所", "勤務先電話番号"],
    ["last_name", "first_name", "last_name_kana", "first_name_kana", "relationship", "email", "phone", "workplace", "workplace_address", "workplace_phone"],
))


def parse_date(value, *, epoch1904=False):
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value) or not 1 <= value <= 100000 or (not epoch1904 and int(value) == 60):
            raise ValueError("存在する日付を入力してください。")
        base = date(1904, 1, 1) if epoch1904 else date(1899, 12, 31 if value < 60 else 30)
        return (base + timedelta(days=int(value))).isoformat()
    match = re.fullmatch(r"(\d{4})[/.-](\d{1,2})[/.-](\d{1,2})", str(value).strip())
    if not match:
        raise ValueError("日付は西暦で入力してください。")
    return date(*map(int, match.groups())).isoformat()


def _xml(archive, name):
    raw = archive.read(name)
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper() or b"\x00" in raw:
        raise ValueError("このExcelのXML形式には対応していません。")
    return ET.fromstring(raw)


def read_workbook(content: bytes) -> list[dict]:
    """Read only 入力用; never accidentally import the example sheet or formulas."""
    if not content or len(content) > MAX_FILE_BYTES:
        raise ValueError("空ではない20MB以下のExcel（.xlsx）を選択してください。")
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or len({e.filename for e in entries}) != len(entries):
                raise ValueError("Excelの内部構成が不正です。")
            if sum(e.file_size for e in entries) > 80 * 1024 * 1024 or any(e.flag_bits & 1 for e in entries):
                raise ValueError("展開サイズが大きすぎるか、パスワード保護されています。")
            book = _xml(archive, "xl/workbook.xml")
            sheets = [s for s in book.findall("s:sheets/s:sheet", NS) if s.get("name") == "入力用"]
            if len(sheets) != 1:
                raise ValueError("テンプレートの「入力用」シートを使用してください。記入例は取り込みません。")
            rel_id = sheets[0].get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
            rels = _xml(archive, "xl/_rels/workbook.xml.rels")
            rel = next((r for r in rels if r.get("Id") == rel_id), None)
            if rel is None or rel.get("TargetMode") == "External":
                raise ValueError("入力用シートを読み込めません。")
            target = rel.get("Target", "")
            target = posixpath.normpath(target.lstrip("/") if target.startswith("/") else "xl/" + target)
            if not target.startswith("xl/worksheets/"):
                raise ValueError("入力用シートの位置が不正です。")
            strings = []
            if "xl/sharedStrings.xml" in archive.namelist():
                strings = ["".join(n.text or "" for n in si.findall(".//s:t", NS)) for si in _xml(archive, "xl/sharedStrings.xml").findall("s:si", NS)]
            props = book.find("s:workbookPr", NS)
            epoch1904 = props is not None and props.get("date1904") in {"1", "true"}
            sheet = _xml(archive, target)
            headers = None
            output = []
            seen_lines = set()
            for element in sheet.findall("s:sheetData/s:row", NS):
                line = int(element.get("r", "0"))
                if line < 1 or line in seen_lines:
                    raise ValueError("行番号が不正または重複しています。")
                seen_lines.add(line)
                cells = {}
                for cell in element.findall("s:c", NS):
                    address = cell.get("r", "")
                    match = re.fullmatch(r"([A-Z]+)([1-9]\d*)", address)
                    if not match or int(match[2]) != line:
                        raise ValueError("セル位置が不正です。")
                    column = 0
                    for char in match[1]:
                        column = column * 26 + ord(char) - 64
                    if column in cells:
                        raise ValueError("同じセルが複数あります。")
                    if line < 4:
                        continue
                    if cell.find("s:f", NS) is not None:
                        raise ValueError(f"{address}に数式があります。値のみ貼り付けてください。")
                    kind = cell.get("t")
                    v = cell.find("s:v", NS)
                    raw = v.text if v is not None and v.text is not None else ""
                    if kind == "e":
                        raise ValueError(f"{address}にExcelのエラーがあります。")
                    if kind == "s":
                        index = int(raw)
                        if not 0 <= index < len(strings):
                            raise ValueError("Excelの文字列参照が不正です。")
                        value = strings[index]
                    elif kind == "inlineStr":
                        value = "".join(n.text or "" for n in cell.findall(".//s:t", NS))
                    elif kind in {"str", "d"}:
                        value = raw
                    elif kind == "b":
                        raise ValueError(f"{address}には文字または日付を入力してください。")
                    else:
                        value = float(raw) if raw else ""
                        if isinstance(value, float) and (not math.isfinite(value)):
                            raise ValueError("Excelの数値が不正です。")
                        if isinstance(value, float) and value.is_integer():
                            value = int(value)
                    cells[column] = value
                if line == 4:
                    headers = [cells.get(i + 1, "") for i in range(len(HEADERS))]
                    if headers != HEADERS or any(v != "" for i, v in cells.items() if i > len(HEADERS)):
                        raise ValueError("4行目の見出しが異なります。最新の初期台帳テンプレートを使用してください。")
                elif line > 4 and any(v != "" for v in cells.values()):
                    if headers is None:
                        raise ValueError("4行目に見出しがありません。")
                    if any(v != "" for i, v in cells.items() if i > len(HEADERS)):
                        raise ValueError(f"{line}行目にテンプレート外の列があります。")
                    row = {key: cells.get(i + 1, "") for i, key in enumerate(HEADERS)}
                    for definition in FIELDS:
                        key = definition["key"]
                        if definition["type"] == "date" and isinstance(row[key], (int, float)):
                            row[key] = parse_date(row[key], epoch1904=epoch1904)
                    output.append({**row, "_line": line})
                    if len(output) > MAX_ROWS:
                        raise ValueError("一度に取り込める園児は1000人までです。")
            if headers is None:
                raise ValueError("入力用シートの4行目に見出しがありません。")
            return output
    except ValueError:
        raise
    except (BadZipFile, ET.ParseError, KeyError, IndexError, TypeError, RuntimeError, OverflowError) as exc:
        raise ValueError("Excelを読み込めません。通常の.xlsx形式で保存してください。") from exc


def clean_rows(source):
    if not isinstance(source, list) or len(source) > MAX_ROWS:
        raise ValueError("園児は1000行以内で指定してください。")
    rows, lines = [], set()
    for index, raw in enumerate(source):
        if not isinstance(raw, dict) or set(raw) - set(HEADERS) - {"_line"}:
            raise ValueError("入力項目が不正です。Excelを読み込み直してください。")
        line = raw.get("_line", index + 5)
        if type(line) is not int or not 5 <= line <= 1048576 or line in lines:
            raise ValueError("行番号が不正または重複しています。")
        lines.add(line)
        row = {"_line": line}
        for key in HEADERS:
            value = raw.get(key, "")
            if not isinstance(value, (str, int, float)) or isinstance(value, bool) or (isinstance(value, float) and not math.isfinite(value)):
                raise ValueError(f"{line}行目の値が不正です。")
            if len(str(value)) > 1000:
                raise ValueError(f"{line}行目の{key}は1000文字以内で入力してください。")
            row[key] = value.strip() if isinstance(value, str) else value
        if any(row[k] != "" for k in HEADERS):
            rows.append(row)
    return rows


@dataclass
class LedgerPlan:
    rows: list = field(default_factory=list)
    children: list = field(default_factory=list)
    families: list = field(default_factory=list)
    classes: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    revision: str = ""
    fingerprint: str = ""
    preview_token: str = ""
    filename: str = ""
    already_imported: bool = False
    committed: bool = False
    receipt_id: int | None = None

    @property
    def can_commit(self):
        return bool(self.children) and not self.errors and not self.already_imported


def preview_ledger(session: Session, source, *, filename="") -> LedgerPlan:
    plan = LedgerPlan(filename=filename, revision=state_revision(ledger_state(session)))
    try:
        plan.rows = clean_rows(source)
    except ValueError as exc:
        plan.errors.append(TransferMessage(0, "ファイル", "", str(exc)))
        return plan
    normalized = []
    families, classes, exact, identities = {}, {}, {}, {}
    old_children = session.exec(select(Child)).all()
    old_families = session.exec(select(Family)).all()
    old_classes = {c.name: c for c in session.exec(select(Classroom)).all()}
    next_child = max((c.id for c in old_children), default=0)
    next_family = max((f.id for f in old_families), default=0)
    next_order = max((c.display_order for c in old_classes.values()), default=0)
    old_identities = {(c.last_name_kana, c.first_name_kana, c.birth_date.isoformat()) for c in old_children}
    shared_keys = ["家庭住所", "家庭電話番号"] + [f["key"] for f in FIELDS if f["group"].startswith("保護者")]
    def issue(row, key, message, *, warning=False):
        (plan.warnings if warning else plan.errors).append(TransferMessage(row, key, "", message))
    for index, raw in enumerate(plan.rows):
        row = {key: str(raw[key]).strip() for key in HEADERS}
        line = raw["_line"]
        for definition in FIELDS:
            key, value = definition["key"], row[definition["key"]]
            kind = definition["type"]
            if definition["required"] and not value:
                issue(line, key, "必須項目が空欄です。")
            if not value:
                continue
            if kind == "date":
                try:
                    row[key] = parse_date(raw[key])
                except ValueError:
                    issue(line, key, "存在する日付を西暦で入力してください。")
            if kind == "select" and value not in definition["options"]:
                issue(line, key, "・".join(definition["options"]) + "から選択してください。")
            if kind == "integer" and (not re.fullmatch(r"[1-9]\d{0,8}", value)):
                issue(line, key, "1以上、9桁以内の整数を入力してください。")
            if kind == "email" and (len(value) > 255 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value)):
                issue(line, key, "メールアドレスを確認してください。")
            if kind == "phone" and not isinstance(raw[key], str):
                issue(line, key, "数値の電話番号です。先頭の0を原本で確認し、文字列で入力し直してください。")
        for number in ("①", "②"):
            if any(row[f"保護者{number}{key}"] for key in GUARDIAN_KEYS) and not all(row[f"保護者{number}{key}"] for key in ("姓", "名")):
                issue(line, f"保護者{number}姓", "保護者情報がある場合は姓・名の両方が必要です。")
        name, name_type = row["照合用氏名"], row["照合用氏名種別"]
        if bool(name) != bool(name_type):
            issue(line, "照合用氏名", "氏名と種別をセットで入力してください。")
        if len(name) > 200:
            issue(line, "照合用氏名", "200文字以内で入力してください。")
        if name and name_type == "kana" and not re.search(r"[ァ-ヶー]", name):
            issue(line, "照合用氏名", "カタカナを入力してください。")
        if name and name_type == "latin" and not re.search(r"[A-Za-zÀ-ÖØ-öø-ÿ]", name):
            issue(line, "照合用氏名", "英字を入力してください。")
        for start, end in (("生年月日", "入園日"), ("入園日", "退園日")):
            try:
                if row[start] and row[end] and parse_date(row[end]) < parse_date(row[start]):
                    issue(line, end, f"{start}より前になっています。")
            except ValueError:
                pass
        if row["在園状態"] in {"卒園", "退園"} and not row["退園日"]:
            issue(line, "退園日", "卒園・退園ですが日付が空欄です。", warning=True)
        signature = json.dumps(row, ensure_ascii=False, sort_keys=True)
        if signature in exact:
            issue(line, "姓", f"{exact[signature]}行目と入力内容がすべて同じです。重複行を確認してください。")
        exact[signature] = line
        identity = (row["姓カナ"], row["名カナ"], row["生年月日"])
        if all(identity) and identity in identities:
            issue(line, "姓カナ", "同じ氏名カナ・生年月日があります。別園児として登録してよいか確認してください。", warning=True)
        identities[identity] = line
        group = ("group", row["きょうだいグループ"]) if row["きょうだいグループ"] else ("row", line)
        if group not in families:
            families[group] = {"id": next_family + len(families) + 1, "group": row["きょうだいグループ"], "data": {}, "children": [], "guardians": []}
        family = families[group]
        for key in shared_keys:
            if row[key]:
                if family["data"].get(key) and family["data"][key] != row[key]:
                    issue(line, key, "同じきょうだいグループの別の行と内容が異なります。")
                else:
                    family["data"][key] = row[key]
        if row["クラス名"]:
            key = row["クラス名"]
            if key not in classes:
                existing = old_classes.get(key)
                classes[key] = {"name": key, "existing_id": existing.id if existing else None, "explicit": "", "order": existing.display_order if existing else next_order + 1}
                if not existing:
                    next_order += 1
            classroom = classes[key]
            if row["クラス表示順"] and re.fullmatch(r"[1-9]\d{0,8}", row["クラス表示順"]):
                order = int(row["クラス表示順"])
                if classroom["explicit"] and classroom["explicit"] != order:
                    issue(line, "クラス表示順", "同じクラスで表示順が異なります。")
                elif classroom["existing_id"] and order != classroom["order"]:
                    issue(line, "クラス表示順", "登録済みクラスの表示順と異なります。空欄にすると既存の表示順を使用します。")
                else:
                    classroom["explicit"] = order
                    classroom["order"] = order
        elif row["クラス表示順"]:
            issue(line, "クラス名", "表示順を指定する場合はクラス名も入力してください。")
        normalized.append(row.copy())
        child = {**row, "_line": line, "id": next_child + index + 1, "family_id": family["id"]}
        family["children"].append(child)
        plan.children.append(child)
    fingerprint_data = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False) for r in normalized)
    plan.fingerprint = hashlib.sha256(json.dumps(fingerprint_data, ensure_ascii=False).encode()).hexdigest()
    logs = session.exec(select(DataTransferLog).where(DataTransferLog.dataset == DATASET, DataTransferLog.result == "success")).all()
    for log in logs:
        if any(m.get("kind") == "initial_ledger_batch" and m.get("fingerprint") == plan.fingerprint for m in (log.change_metadata or []) if isinstance(m, dict)):
            plan.already_imported = True
            plan.receipt_id = log.id
            break
    if not plan.already_imported:
        for child in plan.children:
            if (child["姓カナ"], child["名カナ"], child["生年月日"]) in old_identities:
                issue(child["_line"], "姓カナ", "同じ氏名カナ・生年月日の園児が既存台帳にあります。初期取り込みでは上書きしません。園児台帳で確認してください。")
    surname_counts = Counter(f["children"][0]["姓"] for f in families.values())
    existing_surnames = {c.last_name for c in old_children if c.family_id}
    used_names = {f.family_name for f in old_families}
    for family in families.values():
        first = family["children"][0]
        surname = first["姓"]
        duplicate = surname_counts[surname] > 1 or surname in used_names or surname in existing_surnames
        base = " ".join((surname, first["名"])).strip() if duplicate else surname
        name = base or "氏名入力後に自動設定"
        if name in used_names:
            name = f"{name}（F-{family['id']:05d}）"
        while name in used_names:
            name += "（別家庭）"
        used_names.add(name)
        family["name"] = name
        for child in family["children"]:
            child["family_name"] = name
            if child["姓"] and surname and child["姓"] != surname:
                issue(child["_line"], "きょうだいグループ", "異なる姓の園児を同じ家庭にまとめています。家庭名は先頭行の園児を基準にします。", warning=True)
        for order, number in enumerate(("①", "②"), start=1):
            profile = {destination: family["data"].get(f"保護者{number}{source}", "") for source, destination in GUARDIAN_KEYS.items()}
            if profile["last_name"] and profile["first_name"]:
                profile.update(order=order, parent_account_id=None)
                profile["relationship"] = profile["relationship"] or "保護者"
                family["guardians"].append(profile)
    plan.families = list(families.values())
    plan.classes = list(classes.values())
    if not plan.rows:
        issue(0, "入力用", "入力用シートの5行目から園児情報を入力してください。")
    return plan


def commit_ledger(session, rows, *, filename, expected_revision, actor_name, actor_id=None):
    from child_profile_history import record_child_profile_history
    session.rollback()
    plan = LedgerPlan(filename=filename)
    if session.get_bind().dialect.name != "sqlite":
        plan.errors.append(TransferMessage(0, "構成", "", "初期台帳の確定は現在SQLite構成に対応しています。"))
        return plan
    try:
        session.execute(text("BEGIN IMMEDIATE"))
        before = ledger_state(session)
        plan = preview_ledger(session, rows, filename=filename)
        if plan.already_imported:
            session.rollback()
            return plan
        if not expected_revision or expected_revision != state_revision(before):
            plan.errors.append(TransferMessage(0, "台帳", "", "確認後に台帳が更新されました。もう一度内容を確認してください。"))
        if not plan.can_commit:
            session.rollback()
            return plan
        classrooms = {}
        for item in plan.classes:
            if item["existing_id"]:
                classrooms[item["name"]] = item["existing_id"]
            else:
                classroom = Classroom(name=item["name"], display_order=item["order"])
                session.add(classroom)
                session.flush()
                classrooms[item["name"]] = classroom.id
        for item in plan.families:
            family = Family(id=item["id"], family_name=item["name"], home_address=item["data"].get("家庭住所") or None, home_phone=item["data"].get("家庭電話番号") or None)
            set_family_guardian_profiles(family, item["guardians"])
            session.add(family)
        session.flush()
        family_map = {f["id"]: f for f in plan.families}
        created = []
        for row in plan.children:
            family = family_map[row["family_id"]]
            child = Child(
                id=row["id"], family_id=row["family_id"], classroom_id=classrooms.get(row["クラス名"]),
                last_name=row["姓"], first_name=row["名"], last_name_kana=row["姓カナ"], first_name_kana=row["名カナ"],
                birth_date=date.fromisoformat(row["生年月日"]), enrollment_date=date.fromisoformat(row["入園日"]),
                withdrawal_date=date.fromisoformat(row["退園日"]) if row["退園日"] else None,
                status={"在園": ChildStatus.enrolled, "卒園": ChildStatus.graduated, "退園": ChildStatus.withdrawn}[row["在園状態"]],
                sex={"男": ChildSex.male, "女": ChildSex.female}.get(row["性別"], ChildSex.not_set),
                home_address=row["園児住所"] or family["data"].get("家庭住所") or None,
                home_phone=row["園児電話番号"] or family["data"].get("家庭電話番号") or None,
                registration_verification_name=row["照合用氏名"] or f"{row['姓カナ']} {row['名カナ']}",
                registration_verification_name_type=row["照合用氏名種別"] or "kana",
                extra_data={"allergy": [], "medical_notes": ""},
            )
            session.add(child)
            session.flush()
            for profile in family["guardians"]:
                session.add(Guardian(child_id=child.id, **profile))
            created.append(child)
        session.flush()
        for child in created:
            record_child_profile_history(session, child, actor_name=actor_name, action="created", previous_snapshot=None, source="initial_ledger_import")
        metadata = audit_changes(before, ledger_state(session))
        metadata.append({"kind": "initial_ledger_batch", "fingerprint": plan.fingerprint, "children": [r["id"] for r in plan.children], "families": [f["id"] for f in plan.families]})
        log = DataTransferLog(transfer_type="import", dataset=DATASET, filename=filename, actor_name=actor_name, actor_id=actor_id,
                              result="success", created_count=len(plan.children), change_metadata=metadata)
        session.add(log)
        session.flush()
        plan.receipt_id = log.id
        session.commit()
        plan.committed = True
        return plan
    except Exception:
        session.rollback()
        plan.errors.append(TransferMessage(0, "保存", "", "保存できませんでした。今回の登録はすべて取り消しました。もう一度確認してください。"))
        return plan
