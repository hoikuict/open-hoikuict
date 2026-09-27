"""Shared fictional phrases in process memory; no production persistence."""
from copy import deepcopy
from datetime import datetime
from threading import RLock
import unicodedata

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field


class PhraseInput(BaseModel):
    age: int = Field(ge=0, le=5)
    month: int = Field(ge=0, le=12)
    field_code: str = Field(min_length=1, max_length=100)
    text: str = Field(min_length=1, max_length=2000)
    source_note: str = Field(default='', max_length=200)
    version: int = Field(default=0, ge=0)


class PreviewPhraseStore:
    def __init__(self, definitions):
        self.catalog = {
            age: {key: value for key, value in definitions(
                {'age': age, 'children': [{'ref': 'personal'}]}, '2026-10').items()
                  if value['section']}
            for age in range(6)
        }
        self.active = {}
        self.versions = {}
        self.lock = RLock()

    def save(self, payload, facility_id=None):
        d = self.catalog[payload.age].get(payload.field_code)
        if not d:
            raise HTTPException(422, '登録先の項目を選んでください。')
        if not payload.text.strip():
            raise HTTPException(422, '文例の本文を入力してください。')
        with self.lock:
            old = self.active.get(facility_id)
            if facility_id is not None and (not old or old['version'] != payload.version):
                raise HTTPException(409, 'この文例は変更されています。候補を読み直してください。入力は残っています。')
            identity = (payload.age, payload.month, payload.field_code)
            normalized = unicodedata.normalize('NFKC', payload.text.strip()).casefold()
            for row in self.active.values():
                if row['facility_id'] != facility_id and (row['age'], row['registered_month'], row['field_code']) == identity:
                    if unicodedata.normalize('NFKC', row['text']).casefold() == normalized:
                        raise HTTPException(409, '同じ登録先に同じ本文の園文例があります。')
            phrase_id = 1000000 + len(self.versions) + 1
            row = {
                'phrase_id': phrase_id, 'source_key': 'preview-shared', 'kind': 'original',
                'facility_id': facility_id or phrase_id, 'version': payload.version + 1,
                'is_facility': True, 'text': payload.text.strip(), 'age': payload.age,
                'month': payload.month, 'registered_month': payload.month,
                'field_code': payload.field_code, 'field_label': d['label'],
                'section': d['section'], 'item': d['item'], 'ryoiki': d['ryoiki'],
                'year': 2026, 'source_note': payload.source_note.strip(),
                'created_by': '架空職員', 'updated_at': datetime.now().isoformat(timespec='seconds'),
                'relative_path': '園で追加した文例（見本）', 'sheet': d['label'],
                'cell_id': phrase_id, 'source_id': 4,
            }
            self.versions[phrase_id] = deepcopy(row)
            self.active[row['facility_id']] = row
            return deepcopy(row)

    def remove(self, facility_id, version):
        with self.lock:
            row = self.active.get(facility_id)
            if not row or row['version'] != version:
                raise HTTPException(409, 'この文例は変更されています。候補を読み直してください。')
            del self.active[facility_id]
            # Keep immutable versions for already-selected and saved sheet origins.

    def find(self, definition, age, month, phrase_ids=None):
        with self.lock:
            rows = self.active.values() if phrase_ids is None else (
                self.versions[i] for i in phrase_ids if i in self.versions)
            return [deepcopy(row) | {'month': month} for row in rows
                    if row['age'] == age and row['registered_month'] in (0, month)
                    and all(row[k] == definition[k] for k in ('section', 'item', 'ryoiki'))]


def install_routes(app, store):
    @app.post('/plans/monthly-library/preview-phrases')
    def add_phrase(payload: PhraseInput, request: Request):
        return store.save(payload)

    @app.put('/plans/monthly-library/preview-phrases/{facility_id}')
    def edit_phrase(facility_id: int, payload: PhraseInput, request: Request):
        return store.save(payload, facility_id)

    @app.delete('/plans/monthly-library/preview-phrases/{facility_id}')
    def delete_phrase(facility_id: int, version: int, request: Request):
        store.remove(facility_id, version)
        return {'removed': True}
