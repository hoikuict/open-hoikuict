"""Two fictional editors exercising server-side merge and conflict behavior."""
from copy import deepcopy
from tools.monthly_assignment_preview import AssignmentPreview
from tools.monthly_cell_merge_preview import wire_cell


def main():
    preview = AssignmentPreview()
    client = preview.fixture.client
    checks = []
    try:
        def actor(name):
            response = client.post('/preview/state', json={'actor':name,'dataset':'partial'})
            assert response.status_code == 200

        def snapshot(name='teacher_a', month='2026-10', age=1):
            actor(name)
            response = preview.fixture.context(month,age)
            assert response.status_code == 200
            return response.json()

        def write(name, base, changes):
            actor(name)
            fields = {key:wire_cell(value) for key,value in base['sheet']['fields'].items()}
            owner = base['owner_name']
            for key,value in changes.items():
                if key=='@owner': owner=value
                elif value is None: fields.pop(key,None)
                else: fields[key]={'body':value,'origins':[]} if isinstance(value,str) else value
            payload = {key:base[key] for key in ('document_id','lock_version','classroom_id','target_month','age')}
            return client.post('/preview/cell-save',json=payload | {
                'base_token':base['preview_base_token'],'owner_name':owner,'fields':fields})

        def ok(response):
            assert response.status_code==200,response.text
            return response.json()

        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'child:1:play':'Cのあそび'}))
        merged=ok(write('teacher_a',a,{'child:1:life':'Aの生活'}))
        assert merged['sheet']['fields']['child:1:play']['body']=='Cのあそび'
        assert merged['sheet']['fields']['child:1:life']['body']=='Aの生活'
        assert len(merged['merged_remote_fields'])==1
        checks.append('different cells by two assigned users both survive')

        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'child:1:life':'Cが先に保存'}))
        response=write('teacher_a',a,{'child:1:life':'Aの別の入力','common:home':'同時保存しない別欄'})
        assert response.status_code==409,response.text
        conflict=response.json()['detail']
        assert [v['key'] for v in conflict['conflicts']]==['child:1:life']
        latest=snapshot()
        assert latest['sheet']['fields']['child:1:life']['body']=='Cが先に保存'
        assert latest['sheet']['fields'].get('common:home',{}).get('body')!='同時保存しない別欄'
        # A third update while the comparison is open must still conflict.
        ok(write('support',snapshot('support'),{'child:1:life':'Cがさらに保存'}))
        assert write('teacher_a',conflict['latest'],{'child:1:life':'Aの別の入力'}).status_code==409
        resolved=ok(write('teacher_a',snapshot(),{'child:1:life':'両者を確認した文章','common:home':'確認後に保存'}))
        assert resolved['sheet']['fields']['common:home']['body']=='確認後に保存'
        checks.append('same-cell conflict is atomic; a newer update during resolution conflicts again')

        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'@owner':'CとA'}))
        merged=ok(write('teacher_a',a,{'child:2:play':'別の園児のあそび'}))
        assert merged['owner_name']=='CとA'
        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'@owner':'CとD'}))
        response=write('teacher_a',a,{'@owner':'AとD'})
        assert response.status_code==409 and response.json()['detail']['conflicts'][0]['key']=='@owner'
        checks.append('owner name is independent and same-owner edits conflict')

        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'child:2:play':'Cの修正'}))
        merged=ok(write('teacher_a',a,{'child:1:life':None}))
        assert 'child:1:life' not in merged['sheet']['fields']
        assert merged['sheet']['fields']['child:2:play']['body']=='Cの修正'
        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'child:2:play':'Cの再修正'}))
        assert write('teacher_a',a,{'child:2:play':None}).status_code==409
        checks.append('deleting a cell merges with unrelated changes but conflicts with editing that cell')

        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'child:1:life':'同じ完成文'}))
        ok(write('teacher_a',a,{'child:1:life':'同じ完成文'}))
        a,c=snapshot(),snapshot('support')
        ok(write('support',c,{'child:1:life':{'body':'出典付き','origins':[{'source_key':'fixture','phrase_id':1}]}}))
        merged=ok(write('teacher_a',a,{'common:goal':'共通のねらい'}))
        assert merged['sheet']['fields']['child:1:life']['origins'][0]['phrase_id']==1
        checks.append('identical edits converge; merging retains source provenance')

        a,c=snapshot('admin_a','2026-12',3),snapshot('support','2026-12',3)
        assert a['document_id'] is None and c['document_id'] is None
        ok(write('support',c,{'common:home':'新規C'}))
        merged=ok(write('admin_a',a,{'common:goal':'新規A'}))
        assert merged['sheet']['fields']['common:home']['body']=='新規C'
        assert merged['sheet']['fields']['common:goal']['body']=='新規A'
        checks.append('simultaneously opened unsaved sheets merge into one document')

        a=snapshot()
        actor('teacher_a')
        client.post('/preview/revoke',json={})
        payload=preview.fixture.payload(a)
        payload['fields']={key:wire_cell(value) for key,value in a['sheet']['fields'].items()}
        payload['base_token']=a['preview_base_token']
        response=client.post('/preview/cell-save',json=payload)
        assert response.status_code==403
        client.post('/preview/restore',json={})
        assert write('admin_none',a,{'common:goal':'拒否'}).status_code==409
        invalid=deepcopy(a);invalid['classroom_id']=2
        assert write('teacher_a',invalid,{'common:goal':'別クラス'}).status_code==409
        checks.append('revocation, foreign actor baseline, and changed classroom cannot bypass access')
        print('PASS\n'+'\n'.join(checks))
    finally:
        preview.close()


if __name__=='__main__':
    main()
