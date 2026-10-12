"""Annual sheets retain immutable source text separately from editable values."""
from copy import deepcopy
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

TEMPLATE_ID = "annual-infant-1-v1"
GRID_TEMPLATE_ID = "annual-grid-v1"
TEMPLATE_IDS = {TEMPLATE_ID, GRID_TEMPLATE_ID}
GRID_SCHEMA = "annual-r8-grid-v1"
SOURCE_SCHEMA = "donguri-r8-import-v1"
PERIODS = [
    {"label": "1期（4〜5月）", "start_month": 4, "end_month": 5},
    {"label": "2期（6〜8月）", "start_month": 6, "end_month": 8},
    {"label": "3期（9〜12月）", "start_month": 9, "end_month": 12},
    {"label": "4期（1〜3月）", "start_month": 1, "end_month": 3},
]


class CellInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    body: str = Field(max_length=20000)
    start: int | Literal["annual"] | None = None
    confirmed: bool = False


class OriginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["source", "previous"]
    key: str | None = Field(default=None, max_length=100)
    document_id: int | None = Field(default=None, gt=0)
    revision_id: int | None = Field(default=None, gt=0)


class SaveInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: int | None = Field(default=None, gt=0)
    lock_version: int = Field(ge=0)
    classroom_id: int = Field(gt=0)
    school_year: int = Field(ge=1900, le=2199)
    # The save route supplies the same actionable message for empty and whitespace-only names.
    owner_name: str = Field(max_length=200)
    origin: OriginInput | None = None
    source_digest: str = Field(min_length=64, max_length=64)
    fields: dict[str, CellInput] = Field(max_length=200)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def definitions(sheet):
    source = sheet["source"]
    result = {item["id"]: dict(item) for item in source["fields"]}
    for section in source["sections"]:
        for item in section["items"]:
            result[item["id"]] = {**item, "ticks": section["ticks"]}
    return result


def read_source(path):
    """Accept only inspected, bounded formats; layout and field identities are server-owned."""
    try:
        path = Path(path).expanduser()
        if path.stat().st_size > 2_000_000:
            raise ValueError
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema"] in (SOURCE_SCHEMA, GRID_SCHEMA)
        assert type(data["source"]["age"]) is int and 0 <= data["source"]["age"] <= 5
        assert 1900 <= data["source"]["year"] <= 2199
        assert data["source"]["url"].startswith("https://docs.google.com/spreadsheets/d/")
        if data["schema"] == SOURCE_SCHEMA:
            assert data["source"]["age"] == 1
            expected = {"annual"} | {f"{kind}:{i}" for kind in ("goal", "content", "care") for i in range(4)}
            assert len(data["fields"]) == 13 and {x["id"] for x in data["fields"]} == expected
            assert [s["kind"] for s in data["sections"]] == ["development", "support"]
        else:
            assert data["source"]["age"] in (0, 2, 3, 4, 5)
            assert 1 <= len(data["fields"]) <= 150
            assert all(f["text"] == data["rawCells"][f["sourceCell"]] for f in data["fields"])
            assert 1 <= len(data["annualFields"]) <= 4
            assert set(data["annualFields"]) <= {f["id"] for f in data["fields"]}
            assert len(data["periods"]) == 4
            assert [s["kind"] for s in data["sections"]] == (["development", "support"] if data["source"]["age"] == 0 else [])
            validate_grid(data["grid"], {f["id"] for f in data["fields"]})
        items = list(data["fields"])
        for section in data["sections"]:
            ticks = section["ticks"]
            allowed = (list(range(5, 24)) if data["source"]["age"] == 0 else
                       list(range(12, 36)) if section["kind"] == "development" else list(range(12)))
            assert [t["value"] for t in ticks] == allowed
            assert all(math.isfinite(t["x"]) for t in ticks)
            assert all(a["x"] < b["x"] for a, b in zip(ticks, ticks[1:]))
            assert 1 <= len(section["items"]) <= 100
            for item in section["items"]:
                assert item["kind"] == section["kind"]
                assert item["estimateValue"] in allowed or (
                    section["kind"] == "support" and item["estimateValue"] == "annual"
                )
                assert math.isfinite(item["positionRatio"])
                assert item["positionStatus"] in ("needs_confirmation", "explicit_annual")
                assert isinstance(item["category"], str) and len(item["category"]) <= 100
            items.extend(section["items"])
        assert len({x["id"] for x in items}) == len(items)
        assert len(items) <= 200
        assert all(isinstance(x["text"], str) and len(x["text"]) <= 20000 for x in items)
        assert all(isinstance(x["id"], str) and len(x["id"]) <= 80 for x in items)
        return data
    except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
        raise HTTPException(503, "年案の取り込み元を読み込めません。管理者が設定を確認してください") from exc


def validate_grid(grid, field_ids=()):
    assert 1 <= len(grid["widths"]) <= 70 and 1 <= len(grid["rows"]) <= 70
    assert all(isinstance(w, (int, float)) and math.isfinite(w) and 0 < w <= 200 for w in grid["widths"])
    assert sum(len(row) for row in grid["rows"]) <= 4900
    for row in grid["rows"]:
        for cell in row:
            assert isinstance(cell["text"], str) and len(cell["text"]) <= 20000
            assert all(type(cell[k]) is int and 1 <= cell[k] <= 70 for k in ("rowspan", "colspan"))
            assert cell.get("field") is None or cell["field"] in field_ids


def class_key(name):
    return "".join(name.split()).removesuffix("組")


def reference_choices(nursery_ref, classroom_name, school_year):
    """Separate, immutable Drive reflections; never copy old reflections into a new year's text."""
    result = []
    for row in registry_rows(nursery_ref):
        if not row.get("references_path"):
            continue
        source = read_source(row["path"])["source"]
        if source["year"] != school_year or class_key(source["className"]) != class_key(classroom_name):
            continue
        try:
            path = Path(row["references_path"])
            assert path.stat().st_size <= 2_000_000
            refs = json.loads(path.read_text(encoding="utf-8"))
            assert isinstance(refs, list) and len(refs) <= 20
            for ref in refs:
                assert ref["source"]["year"] == school_year and ref["source"]["age"] == source["age"]
                assert ref["source"]["url"].startswith("https://docs.google.com/spreadsheets/d/")
                assert isinstance(ref["status"], str) and type(ref["primary"]) is bool
                validate_grid(ref["grid"])
            result.extend(refs)
        except (OSError, ValueError, KeyError, TypeError, AssertionError) as exc:
            raise HTTPException(503, "反省の取り込み元を読み込めません。管理者が設定を確認してください") from exc
    return result


def registry_rows(nursery_ref):
    try:
        configured = os.getenv("HOIKU_ANNUAL_LIBRARY_SOURCES")
        if configured is None:
            path = Path(__file__).resolve().parents[2] / "data" / "annual-library-sources.json"
            configured = path.read_text(encoding="utf-8") if path.is_file() else "{}"
        rows = json.loads(configured).get(nursery_ref, [])
        assert isinstance(rows, list) and len(rows) <= 30
        assert all(isinstance(row["id"], str) and 1 <= len(row["id"]) <= 100
                   and isinstance(row["path"], str) for row in rows)
        assert len({r["id"] for r in rows}) == len(rows)
        return rows
    except (OSError, ValueError, TypeError, KeyError, AssertionError, AttributeError) as exc:
        raise HTTPException(503, "年案の取り込み元設定を確認してください") from exc


def source_registry(nursery_ref):
    return {r["id"]: r["path"] for r in registry_rows(nursery_ref)}


def source_choices(nursery_ref):
    result = []
    for key, path in source_registry(nursery_ref).items():
        data = read_source(path)
        result.append({"key": key, "title": data["source"]["title"],
                       "year": data["source"]["year"], "class_name": data["source"]["className"],
                       "age": data["source"]["age"]})
    return result


def import_sheet(nursery_ref, classroom_id, key):
    path = source_registry(nursery_ref).get(key)
    if path is None:
        raise HTTPException(404, "取り込み元が見つかりません")
    source = read_source(path)
    sheet = {
        "schema_version": 1, "template_id": TEMPLATE_ID if source["schema"] == SOURCE_SCHEMA else GRID_TEMPLATE_ID,
        "age": source["source"]["age"],
        "classroom_id": classroom_id, "periods": deepcopy(source.get("periods", PERIODS)),
        "source": source, "fields": {}, "origin": {"kind": "source", "key": key},
        "source_digest": digest(source),
    }
    for key, item in definitions(sheet).items():
        start = item.get("estimateValue")
        sheet["fields"][key] = {
            "body": item["text"], "start": start,
            "position_ratio": item.get("positionRatio"),
            "confirmed": item.get("positionStatus") == "explicit_annual",
        }
    sheet["baseline"] = deepcopy(sheet["fields"])
    sheet["baseline_label"] = "取り込み時の原文"
    return sheet


def validate_fields(payload, sheet):
    defs = definitions(sheet)
    if set(payload.fields) != set(defs):
        raise HTTPException(422, "年案の入力欄が不足しているか、未対応の欄が含まれています")
    if not payload.owner_name.strip():
        raise HTTPException(422, "担任名を入力してください")
    if sum(len(c.body) for c in payload.fields.values()) > 500000:
        raise HTTPException(422, "本文が保存可能な容量を超えています")
    result = {}
    for key, cell in payload.fields.items():
        item, old = defs[key], sheet["fields"][key]
        if "kind" not in item:
            if cell.start is not None or cell.confirmed:
                raise HTTPException(422, "この欄には開始目安を設定できません")
            ratio = None
        else:
            allowed = [t["value"] for t in item["ticks"]]
            if cell.start not in allowed and not (item["kind"] == "support" and cell.start == "annual"):
                raise HTTPException(422, "開始目安が月齢・月の範囲外です")
            # Preserve the original fractional position when no timing edit occurred.
            if cell.start == old["start"]:
                ratio = old["position_ratio"]
            elif cell.start == sheet["baseline"][key]["start"]:
                ratio = sheet["baseline"][key]["position_ratio"]
            elif cell.start == "annual":
                ratio = 0
            else:
                ticks = item["ticks"]
                point = next(t["x"] for t in ticks if t["value"] == cell.start)
                ratio = (point - ticks[0]["x"]) / (ticks[-1]["x"] - ticks[0]["x"])
        result[key] = {"body": cell.body, "start": cell.start, "confirmed": cell.confirmed,
                       "position_ratio": ratio}
    return result


def pending_count(sheet):
    return sum("kind" in item and not sheet["fields"][key]["confirmed"]
               for key, item in definitions(sheet).items())


def confirmation_items(sheet):
    count = pending_count(sheet)
    return [f"開始目安が未確認の文章：{count}件"] if count else []
