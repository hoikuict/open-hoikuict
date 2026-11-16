"""Actual production editing routes, with a private fictional SQLite database."""
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import uvicorn
from fastapi.staticfiles import StaticFiles
from sqlmodel import create_engine

from test_monthly_library import MonthlyLibraryTests
from tools.monthly_library_preview_data import seed_preview_phrases


def main():
    fixture = MonthlyLibraryTests()
    fixture.setUp()
    path = Path(fixture.temp.name) / 'fictional.sqlite'
    with fixture.engine.connect() as connection, sqlite3.connect(path) as target:
        connection.connection.driver_connection.backup(target)
    fixture.engine.dispose()
    fixture.engine = create_engine('sqlite:///' + path.as_posix(), connect_args={'check_same_thread':False})
    fixture.app.state.monthly_library_fixture = True
    os.environ['HOIKUICT_COOKIE_SECURE'] = '0'
    os.environ['HOIKU_MONTHLY_OLLAMA_SOURCES'] = '{}'
    seed_preview_phrases(fixture.corpus)
    fixture.corpus_bytes = fixture.corpus.read_bytes()
    context = fixture.context().json()
    fixture.save(fixture.payload(context, {'common:goal':{'body':'一人ひとりのペースで過ごす。'}})).raise_for_status()
    fixture.app.mount('/static', StaticFiles(directory='static'), name='static')
    try:
        with patch('plan_docs.services.monthly_presence.cache_path', return_value=Path(fixture.temp.name)/'presence.sqlite'):
            uvicorn.run(fixture.app, host='127.0.0.1', port=8905, log_level='warning')
    finally:
        fixture.tearDown()


if __name__ == '__main__':
    main()
