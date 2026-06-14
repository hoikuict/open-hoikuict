from __future__ import annotations

import os
import shutil
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_FACILITY_DB_PATH = REPO_ROOT / "data" / "facility.sqlite"
FACILITY_SEED_PATH = REPO_ROOT / "gen_bunnrei" / "facility.sqlite"


def facility_bunrei_db_path() -> Path:
    return Path(os.getenv("HOIKU_FACILITY_BUNREI_DB_PATH", str(DEFAULT_FACILITY_DB_PATH)))


def ensure_runtime_files() -> None:
    facility_path = facility_bunrei_db_path()
    facility_path.parent.mkdir(parents=True, exist_ok=True)
    if facility_path.exists() or not FACILITY_SEED_PATH.exists():
        return
    shutil.copyfile(FACILITY_SEED_PATH, facility_path)

