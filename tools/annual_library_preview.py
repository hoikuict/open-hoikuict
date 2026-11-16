"""Exercise annual production routes in a separate database, on loopback only."""
import argparse
import json
import os
import sqlite3
from pathlib import Path

import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlmodel import create_engine

from test_annual_library import AnnualLibraryTests


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument("--port", type=int, default=8911)
    args = parser.parse_args()
    fixture = AnnualLibraryTests()
    fixture.setUp()
    path = Path(fixture.temp.name) / "preview.sqlite"
    with fixture.engine.connect() as connection, sqlite3.connect(path) as target:
        connection.connection.driver_connection.backup(target)
    fixture.engine.dispose()
    fixture.engine = create_engine("sqlite:///" + path.as_posix(), connect_args={"check_same_thread": False})
    if args.source:
        os.environ["HOIKU_ANNUAL_LIBRARY_SOURCES"] = json.dumps({
            fixture.user.nursery_ref: [{"id": "fixture", "path": str(args.source.resolve())}]})
    os.environ["HOIKUICT_COOKIE_SECURE"] = "0"
    fixture.app.state.annual_library_fixture = True
    fixture.app.mount("/static", StaticFiles(directory="static"), name="static")
    try:
        uvicorn.run(fixture.app, host="127.0.0.1", port=args.port, log_level="warning")
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
