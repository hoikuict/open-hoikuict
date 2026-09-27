"""Acceptance checks for the proposal, using disposable fictional data only."""
from preview import build_preview, DEFAULT_SOURCE
from search_behavior import matches, search_key


def main():
    assert search_key('ﾎﾞｰﾙ ＡＢＣ') == search_key('ぼーる abc')
    assert search_key('ｶﾞ') == search_key('が')
    assert matches('保育者の真似をして遊ぶ', 'マネをして')
    assert not matches('友達を招いて遊ぶ', '真似')
    fixture = build_preview(DEFAULT_SOURCE)
    client = fixture.client
    checks = 4
    try:
        def search(query, mode='spelling', **extra):
            response = client.get('/plans/monthly-library/candidates', params={
                'classroom_id': 1, 'target_month': '2026-10', 'age': 1,
                'field': 'child:1:play', 'keyword': query, 'preview_match': mode, **extra})
            response.raise_for_status()
            return response.json()['items']

        expected = search('まね')
        assert len(expected) == 5
        checks += 1
        for query in ('マネ', 'ﾏﾈ', '真似'):
            assert search(query) == expected, query
            checks += 1
        assert len({tuple(row['phrase_id'] for row in search(query, 'current'))
                    for query in ('まね', 'マネ', '真似')}) == 3
        checks += 1
        assert len(search('真似', 'related')) == 6
        assert search('模倣', 'related') == search('まね', 'related')
        assert len(search('模倣')) == 1
        checks += 3
        assert len(search('友達 真似')) == 4
        assert search('友達　マネ') == search('友達 真似')
        assert len(search('ぼーる')) == 2
        assert search('見つからない語') == []
        assert search('まね', field='child:1:life') == []
        assert all(row['age'] == 3 and row['month'] == 11 for row in
                   search('真似', age=3, target_month='2026-11', field='common:goal'))
        checks += 6
        # Match keys must not merge hiragana / katakana / kanji phrase identities.
        assert len({row['phrase_id'] for row in expected}) == 5
        context = fixture.context().json()
        row = expected[0]
        payload = fixture.payload(context, {'child:1:play': {
            'body': '【架空の手入力】\n○' + row['text'],
            'origins': [{'source_key': row['source_key'], 'phrase_id': row['phrase_id']}]}})
        response = fixture.save(payload)
        response.raise_for_status()
        fields = response.json()['sheet']['fields']
        assert fields['child:1:play']['origins'][0]['text'] == row['text']
        assert fields['child:1:play']['body'] == payload['fields']['child:1:play']['body']
        checks += 3
        response = client.get('/plans/monthly-library/candidates', params={'preview_error': '1'})
        assert response.status_code == 503
        assert fixture.context().json()['sheet']['fields'] == fields
        assert fixture.context().json()['ai']['enabled'] is False
        response = client.get('/plans/monthly-library?document_id=1')
        assert response.status_code == 200 and '検索の操作見本' in response.text
        checks += 4

        phrase = {'age': 1, 'month': 10, 'field_code': 'personal:play',
                  'text': '【架空の共有例】友達の真似をして、布のトンネルで遊ぶ。', 'source_note': '操作確認'}
        response = client.post('/plans/monthly-library/preview-phrases', json=phrase | {'text': '  '})
        assert response.status_code == 422
        response = client.post('/plans/monthly-library/preview-phrases', json=phrase)
        response.raise_for_status()
        added = response.json()
        assert added['is_facility'] and added['text'] == phrase['text']
        assert search('トンネル マネ')[0]['phrase_id'] == added['phrase_id']
        assert search('トンネル', age=2) == []
        assert search('トンネル', target_month='2026-11') == []
        assert search('トンネル', field='child:1:life') == []
        assert fixture.context().json()['sheet']['fields'] == fields  # Registration alone never inserts text.
        checks += 7
        from fastapi.testclient import TestClient
        with TestClient(fixture.app, base_url='https://testserver') as another_browser:
            response = another_browser.get('/plans/monthly-library/candidates', params={
                'classroom_id': 1, 'target_month': '2026-10', 'age': 1,
                'field': 'child:2:play', 'keyword': 'トンネル'})
            assert response.json()['items'][0]['phrase_id'] == added['phrase_id']
        assert client.post('/plans/monthly-library/preview-phrases', json=phrase).status_code == 409
        checks += 2
        url = '/plans/monthly-library/preview-phrases/' + str(added['facility_id'])
        changed = phrase | {'text': '【架空の共有例】布のトンネルを友達とくぐって遊ぶ。', 'version': added['version']}
        response = client.put(url, json=changed)
        response.raise_for_status()
        revised = response.json()
        assert revised['phrase_id'] != added['phrase_id'] and revised['facility_id'] == added['facility_id']
        assert len(search('トンネル')) == 1 and search('トンネル')[0]['text'] == changed['text']
        assert client.put(url, json=changed).status_code == 409
        # A phrase selected before another staff member edits it keeps its original version.
        context = fixture.context().json()
        fields = {'child:2:play': {
            'body': added['text'], 'origins': [{'source_key': added['source_key'], 'phrase_id': added['phrase_id']}]}}
        response = fixture.save(fixture.payload(context, fields))
        response.raise_for_status()
        assert response.json()['sheet']['fields']['child:2:play']['origins'][0]['text'] == phrase['text']
        checks += 4
        response = client.delete(url, params={'version': revised['version']})
        assert response.status_code == 200
        assert search('トンネル') == []
        assert fixture.context().json()['sheet']['fields']['child:2:play']['body'] == phrase['text']
        assert fixture.context().json()['sheet']['fields']['child:2:play']['origins'][0]['text'] == phrase['text']
        checks += 4
        response = client.post('/plans/monthly-library/preview-phrases', json=phrase | {'month': 0})
        response.raise_for_status()
        assert search('トンネル', target_month='2026-11')[0]['registered_month'] == 0
        checks += 1
    finally:
        fixture.tearDown()  # Includes byte-for-byte check of the fictional corpus.
    print(f'{checks} proposal checks passed; fictional corpus unchanged')


if __name__ == '__main__':
    main()
