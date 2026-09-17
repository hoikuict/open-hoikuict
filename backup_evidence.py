"""Small, non-secret operational receipts, separate from immutable backup sets."""
from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from uuid import uuid4

from backup_jobs import backup_control_dir


def evidence_dir() -> Path:
    return backup_control_dir() / "evidence"


def append_receipt(root: Path, receipt: dict) -> Path:
    root.mkdir(parents=True, exist_ok=True, mode=stat.S_IRWXU)
    path = root / f"{uuid4().hex}.json"
    # Readers only see the final document. UUID names never update an older receipt.
    temporary = root / f".{path.name}.partial"
    with temporary.open("x", encoding="utf-8") as output:
        json.dump(receipt, output, ensure_ascii=False, indent=2, sort_keys=True)
        output.write("\n")
    temporary.chmod(stat.S_IRUSR | stat.S_IWUSR)
    temporary.rename(path)
    return path


def operational_stages(backup_id: str, manifest_sha256: str, *, root: Path | None = None,
                       required_destinations: list[str] | None = None) -> dict:
    stages = {"replicated": "unconfirmed", "restored": "unconfirmed"}
    if not backup_id or not manifest_sha256:
        return stages
    required = required_destinations if required_destinations is not None else [
        item.strip() for item in os.getenv("HOIKUICT_BACKUP_REPLICA_TARGETS", "").split(",") if item.strip()
    ]
    latest = {}
    for path in (root or evidence_dir()).glob("*.json"):
        try:
            if path.is_symlink() or path.stat().st_size > 65536:
                continue
            receipt = json.loads(path.read_text(encoding="utf-8"))
            if (receipt.get("backup_id") != backup_id or receipt.get("manifest_sha256") != manifest_sha256
                    or receipt.get("status") not in {"passed", "failed"}):
                continue
            kind = receipt.get("kind")
            if kind not in {"replication", "restore_test"}:
                continue
            key = (kind, receipt.get("destination_ref", ""))
            if key not in latest or receipt["recorded_at_utc"] > latest[key]["recorded_at_utc"]:
                latest[key] = receipt
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            continue
    replication = [latest.get(("replication", name), {}).get("status", "unconfirmed") for name in required]
    if "failed" in replication:
        stages["replicated"] = "failed"
    elif replication and all(status == "passed" for status in replication):
        stages["replicated"] = "passed"
    if ("restore_test", "") in latest:
        stages["restored"] = latest[("restore_test", "")]["status"]
    return stages
