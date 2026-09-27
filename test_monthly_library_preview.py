"""Keep the interactive fixture usable outside the narrow unit-test examples."""
import sqlite3
from contextlib import closing

import pytest

from plan_docs.services.monthly_library import field_definitions, search_phrases
import test_monthly_library as fixtures
from tools.monthly_library_preview_data import seed_preview_phrases


def test_preview_candidates_cover_all_ages_months_and_searchable_fields():
    fixture = fixtures.MonthlyLibraryTests()
    fixture.setUp()
    try:
        assert seed_preview_phrases(fixture.corpus) == 2520
        fixture.corpus_bytes = fixture.corpus.read_bytes()
        for age in range(6):
            for month in range(1, 13):
                sheet = {"age": age, "children": [{"ref": "child:1"}, {"ref": "child:2"}]}
                for key, definition in field_definitions(sheet, f"2026-{month:02}").items():
                    result = search_phrases("test-nursery", definition, age, month)
                    if definition["section"]:
                        assert len(result["items"]) >= 2, (age, month, key)
                        assert all(row["age"] == age and row["month"] == month for row in result["items"])
                    else:
                        assert result["items"] == []

        candidates = fixture.candidates("group:care:environment", age=3, keyword="休息").json()["items"]
        assert len(candidates) == 1
        origin = candidates[0]
        assert origin["relative_path"] == "fictional/monthly-preview.xls"
        context = fixture.context(age=3).json()
        result = fixture.save(fixture.payload(context, {"group:care:environment": {
            "body": "手入力\n○" + origin["text"],
            "origins": [{"source_key": origin["source_key"], "phrase_id": origin["phrase_id"]}],
        }}))
        assert result.status_code == 200, result.text
        assert fixture.candidates("group:care:environment", age=3, keyword="一致しない検索語").json()["items"] == []
        with closing(sqlite3.connect(fixture.corpus)) as con:
            before = con.execute("SELECT * FROM phrase ORDER BY id").fetchall()
        seed_preview_phrases(fixture.corpus)
        with closing(sqlite3.connect(fixture.corpus)) as con:
            assert con.execute("SELECT * FROM phrase ORDER BY id").fetchall() == before
            assert con.execute("SELECT text FROM phrase WHERE id=2").fetchone()[0] == "手洗いを楽しむ。ＡＢＣ"
    finally:
        fixture.tearDown()


def test_preview_seed_refuses_other_corpora(tmp_path):
    corpus = tmp_path / "other.sqlite"
    with closing(sqlite3.connect(corpus)) as con:
        con.execute("CREATE TABLE source(id INTEGER PRIMARY KEY, rel_path TEXT)")
        con.execute("INSERT INTO source VALUES(1, 'other.xls')")
        con.commit()
    before = corpus.read_bytes()
    with pytest.raises(ValueError, match="fictional"):
        seed_preview_phrases(corpus)
    assert corpus.read_bytes() == before
