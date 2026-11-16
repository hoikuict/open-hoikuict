"""Run the real new screen with fictional in-memory data and no production app startup."""
from pathlib import Path

from fastapi.staticfiles import StaticFiles
import pytest
import uvicorn

from test_attendance_monthly import nursery


if __name__ == "__main__":
    monkeypatch = pytest.MonkeyPatch()
    fixture = nursery.__wrapped__(monkeypatch)
    client, engine, state = next(fixture)
    app = client.app
    app.mount("/static", StaticFiles(directory=Path(__file__).resolve().parents[1] / "static"), name="static")
    try:
        uvicorn.run(app, host="127.0.0.1", port=8895)
    finally:
        try:
            next(fixture)
        except StopIteration:
            pass
        monkeypatch.undo()
