"""AI generation permissions, privacy boundaries and saved provenance."""
import json
from dataclasses import replace
from unittest.mock import patch

import httpx
import pytest

import test_monthly_library as fixtures
from plan_docs.contracts import Role
from plan_docs.services import monthly_ai


@pytest.fixture
def fixture():
    value = fixtures.MonthlyLibraryTests()
    value.setUp()
    with patch.dict('os.environ', {'HOIKU_MONTHLY_OLLAMA_SOURCES': json.dumps({
            'test-nursery': {'url': 'http://127.0.0.1:11434', 'model': 'qwen3:8b'}})}):
        yield value
    value.tearDown()


def install_model(monkeypatch, respond=None):
    requests = []
    def handler(request):
        requests.append(request)
        if respond:
            return respond(request)
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'details': {'format': 'gguf'}})
        return httpx.Response(200, json={'done': True, 'done_reason': 'stop',
            'message': {'content': json.dumps({'candidates': ['落ち着いて過ごせる場所を用意する。', '休息できる環境を整える。']})}})
    client_type = httpx.Client
    monkeypatch.setattr(monthly_ai.httpx, 'Client', lambda **kwargs:
                        client_type(transport=httpx.MockTransport(handler), **kwargs))
    return requests


def generate(fixture, **changes):
    return fixture.client.post('/plans/monthly-library/generate', json={
        'classroom_id': 1, 'target_month': '2026-10', 'age': 3,
        'field': 'group:care:environment', **changes})


def test_ai_scope_only_and_provenance_roundtrip(fixture, monkeypatch):
    calls = install_model(monkeypatch)
    context = fixture.context(age=3).json()
    assert context['ai'] == {'enabled': True, 'model': 'qwen3:8b'}
    response = generate(fixture)
    assert response.status_code == 200, response.text
    origin = response.json()['items'][0]
    sent = json.loads(calls[1].content)
    conditions = json.loads(sent['messages'][1]['content'])
    assert set(conditions) == {'年齢クラス', '対象月', '区分', '入力欄', '領域'}
    assert '架空' not in calls[1].content.decode()
    assert 'A組' not in calls[1].content.decode()
    fields = {'group:care:environment': {'body': '手入力\n○' + origin['text'],
              'origins': [{'kind': 'ai', 'token': origin['token']}]}}
    saved = fixture.save(fixture.payload(context, fields))
    assert saved.status_code == 200, saved.text
    stored = fixture.context(age=3).json()['sheet']['fields']['group:care:environment']['origins'][0]
    assert stored == origin
    assert stored['kind'] == 'ai' and stored['model'] == 'qwen3:8b'
    assert stored['reference_mode'] == 'conditions_only'
    with patch.dict('os.environ', {'HOIKU_MONTHLY_OLLAMA_SOURCES': '{}', 'HOIKUICT_SECRET_KEY': 'rotated'}):
        # The saved server snapshot survives provider downtime and key rotation.
        fixture.client.get('/plans/monthly-library')
        fixture.client.headers['X-CSRF-Token'] = fixture.client.cookies.get('hoikuict_csrf')
        assert fixture.save(fixture.payload(saved.json(), fields)).status_code == 200


def test_ai_rejects_forged_or_wrong_field_tokens(fixture, monkeypatch):
    install_model(monkeypatch)
    token = generate(fixture).json()['items'][0]['token']
    context = fixture.context(age=3).json()
    for field, value in [('group:care:goal', token), ('group:care:environment', token + 'x')]:
        fields = {field: {'body': '改ざん', 'origins': [{'kind': 'ai', 'token': value}]}}
        assert fixture.save(fixture.payload(context, fields)).status_code == 422
    with pytest.raises(Exception) as error:
        monthly_ai.resolve_origin(token, 'another-nursery', 1, '2026-10', 3, 'group:care:environment')
    assert error.value.status_code == 422
    fields = {'group:care:environment': {'body': '改ざん', 'origins': [{'kind': 'ai', 'token': token, 'text': '偽の原文'}]}}
    assert fixture.save(fixture.payload(context, fields)).status_code == 422


def test_ai_permissions_csrf_and_input_limits(fixture, monkeypatch):
    calls = install_model(monkeypatch)
    assert generate(fixture, classroom_id=2).status_code == 403
    assert generate(fixture, field='event:1').status_code == 422
    assert generate(fixture, field='child:999:life', age=1).status_code == 422
    assert generate(fixture, text='園児の本文を送らない').status_code == 422
    fixture.user = replace(fixture.user, role=Role.VIEW_ONLY)
    assert generate(fixture).status_code == 403
    fixture.user = replace(fixture.user, role=Role.CAN_EDIT)
    del fixture.client.headers['X-CSRF-Token']
    assert generate(fixture).status_code == 403
    assert calls == []


def test_ai_disabled_and_busy(fixture, monkeypatch):
    calls = install_model(monkeypatch)
    with patch.dict('os.environ', {'HOIKU_MONTHLY_OLLAMA_SOURCES': '{}'}):
        assert fixture.context().json()['ai'] == {'enabled': False}
        assert generate(fixture).status_code == 503
    assert monthly_ai._generation_slot.acquire(blocking=False)
    try:
        assert generate(fixture).status_code == 429
    finally:
        monthly_ai._generation_slot.release()
    assert calls == []


@pytest.mark.parametrize('failure,expected', [('timeout', 504), ('unavailable', 503), ('cloud', 503),
    ('invalid', 502), ('duplicate', 502), ('truncated', 502)])
def test_ai_failure_preserves_saved_input(fixture, monkeypatch, failure, expected):
    context = fixture.context(age=3).json()
    original = {'common:goal': {'body': '変更しない本文'}}
    assert fixture.save(fixture.payload(context, original)).status_code == 200
    def respond(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('test', request=request)
        if failure == 'unavailable':
            return httpx.Response(503)
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'details': {'format': 'gguf'},
                **({'remote_host': 'cloud.invalid'} if failure == 'cloud' else {})})
        texts = ['同じ文章', '同じ文章'] if failure == 'duplicate' else ['候補1', '候補2']
        return httpx.Response(200, json={'done': True, 'done_reason': 'length' if failure == 'truncated' else 'stop',
            'message': {'content': 'not json' if failure == 'invalid' else json.dumps({'candidates': texts})}})
    install_model(monkeypatch, respond)
    assert generate(fixture).status_code == expected
    assert fixture.context(age=3).json()['sheet']['fields']['common:goal']['body'] == '変更しない本文'
    assert monthly_ai._generation_slot.acquire(blocking=False)
    monthly_ai._generation_slot.release()
