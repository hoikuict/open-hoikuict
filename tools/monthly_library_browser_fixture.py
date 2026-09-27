"""Run the actual monthly UI with ephemeral, fictional data on loopback only.

    python -m tools.monthly_library_browser_fixture

No application startup, production DB or real phrase corpus is used.
Local Ollama can be explicitly configured for test-nursery; otherwise AI is off.
"""
import os

import uvicorn
from fastapi.staticfiles import StaticFiles

from test_monthly_library import MonthlyLibraryTests
from tools.monthly_library_preview_data import seed_preview_phrases


def main():
    fixture = MonthlyLibraryTests()
    fixture.setUp()
    fixture.app.state.monthly_library_fixture = True
    # Local HTTP fixture only. CSRF validation itself stays enabled.
    os.environ["HOIKUICT_COOKIE_SECURE"] = "0"
    try:
        seed_preview_phrases(fixture.corpus)
        fixture.corpus_bytes = fixture.corpus.read_bytes()
        for age in (1,):
            for month in ("2026-07", "2026-08", "2026-09"):
                context = fixture.context(month, age).json()
                fields = {"child:1:life": {"body": month + "の架空の生活・健康計画"},
                          "child:1:play": {"body": "身近な素材で遊ぶ"},
                          "child:1:help": {"body": "落ち着ける場所を用意する"},
                          "child:1:review": {"body": "自分から遊びを選ぶ姿が見られた"}}
                if month != "2026-08":
                    fields["child:2:life"] = {"body": "別の園児の架空の計画"}
                result = fixture.save(fixture.payload(context, fields))
                result.raise_for_status()
        fixture.app.mount("/static", StaticFiles(directory="static"), name="static")
        uvicorn.run(fixture.app, host="127.0.0.1", port=int(os.getenv("MONTHLY_FIXTURE_PORT", "8895")), log_level="warning")
    finally:
        fixture.tearDown()


if __name__ == "__main__":
    main()
