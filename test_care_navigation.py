from copy import deepcopy
from datetime import date

import pytest
from sqlmodel import Session, select

from child_care_certification_service import effective_certification
from family_care_service import child_care_context
from models import Child, ChildCareCertification, FamilyCareCertification, FamilyCareChildSetting, FamilyCareAudit
import test_family_care as care_fixtures
from test_family_care import state, payload, save, count

case = care_fixtures.case


def individual(c, **changes):
    s = state(c)
    return dict(revision=s['revision'], childId=c.individual_id,
                cert=deepcopy(s['store']['children'][str(c.individual_id)]['cert']), reason='', **changes)


def test_individual_preview_and_save_without_common(case):
    before = state(case)
    p = individual(case);p['cert']['from']='2026-10-01';p['cert']['category']='standard'
    r=case.client.post(case.endpoint+'/preview-individual',json=p)
    assert r.status_code==200, r.text
    assert state(case)['revision']==before['revision']
    r=case.client.post(case.endpoint+'/save-individual',json=p)
    assert r.status_code==200,r.text
    assert count(case,FamilyCareCertification)==0
    with Session(case.engine) as s:
        assert effective_certification(s,case.individual_id,date(2026,9,30)).care_time_category.value=='short'
        assert effective_certification(s,case.individual_id,date(2026,10,1)).care_time_category.value=='standard'
    assert r.json()['store']['children'][str(case.child_id)]==before['store']['children'][str(case.child_id)]
    assert case.client.post(case.endpoint+'/save-individual',json=p).status_code==409


def test_individual_correction_reason_and_history(case):
    p=individual(case);p['cert']['category']='standard'
    assert case.client.post(case.endpoint+'/save-individual',json=p).status_code==400
    p['reason']='転記誤りを訂正'
    r=case.client.post(case.endpoint+'/save-individual',json=p)
    assert r.status_code==200,r.text
    rows=r.json()['store']['childHistory'][str(case.individual_id)]
    assert len(rows)==2 and [x['active'] for x in rows]==[True,False]
    assert rows[0]['reasons'][0]['name']=='検証 母'


def test_individual_deactivation_scoped_and_audited(case):
    save(case);before=state(case)
    record=before['store']['childHistory'][str(case.individual_id)][0]
    p=dict(revision=before['revision'],childId=case.individual_id,certificationId=record['id'],reason='')
    assert case.client.post(case.endpoint+'/deactivate-individual',json=p).status_code==400
    p['reason']='誤登録の取消'
    r=case.client.post(case.endpoint+'/deactivate-individual',json=p)
    assert r.status_code==200,r.text
    after=r.json()
    assert after['store']['common']==before['store']['common']
    assert after['store']['children'][str(case.child_id)]==before['store']['children'][str(case.child_id)]
    assert after['store']['children'][str(case.individual_id)]==dict(mode='individual',cert=None)
    assert not after['store']['childHistory'][str(case.individual_id)][0]['active']
    with Session(case.engine) as s:
        assert s.exec(select(FamilyCareAudit).where(FamilyCareAudit.action=='individual_deactivated')).one().reason==p['reason']
    # Cancelled individual remains empty during a later common save.
    p=payload(case,'2026-11-01');p['draft']['children'][str(case.individual_id)]['cert']={k:'' for k in record['cert']}
    save(case,p)
    assert state(case)['store']['children'][str(case.individual_id)]['cert'] is None


def test_cannot_deactivate_common_snapshot_as_individual(case):
    s=save(case)
    record=s['store']['childHistory'][str(case.child_id)][0]
    p=dict(revision=s['revision'],childId=case.child_id,certificationId=record['id'],reason='取消')
    assert case.client.post(case.endpoint+'/deactivate-individual',json=p).status_code==409
    assert not record['canDeactivate']


@pytest.mark.parametrize('action',['save-individual','preview-individual','deactivate-individual'])
def test_individual_wrong_family_and_permissions(case,action):
    p=individual(case);p['childId']=9999
    assert case.client.post(case.endpoint+'/'+action,json=p).status_code==404
    case.current_user.can_manage_child_records=False
    assert case.client.post(case.endpoint+'/'+action,json=p).status_code==403


def test_past_nonoverlapping_individual_and_retired_child(case):
    with Session(case.engine) as s:
        child=s.get(Child,case.individual_id);child.withdrawal_date=date(2026,9,30);s.add(child);s.commit()
    p=individual(case);p['cert'].update({'from':'2025-04-01','to':'2026-03-31'})
    r=case.client.post(case.endpoint+'/save-individual',json=p)
    assert r.status_code==200,r.text
    with Session(case.engine) as s:
        assert effective_certification(s,case.individual_id,date(2025,9,1))
    p=individual(case);p['cert']['from']='2026-10-01'
    assert case.client.post(case.endpoint+'/save-individual',json=p).status_code==400
    with Session(case.engine) as s:
        setting=s.get(FamilyCareChildSetting,case.individual_id);setting.joined_on=date(2026,10,1);s.add(setting);s.commit()
    p=individual(case);p['cert'].update({'from':'2026-09-01','to':''});p['reason']='在籍期間の確認'
    assert case.client.post(case.endpoint+'/save-individual',json=p).status_code==400


def test_orphan_editor_register_and_redirect_to_family(case):
    with Session(case.engine) as s:
        child=s.get(Child,case.child_id);child.family_id=None;s.add(child);s.commit()
    url=f'/children/{case.child_id}/care-certifications'
    r=case.client.get(url)
    assert r.status_code==200 and '家族未登録のため' in r.text and 'guardian_reason_1' in r.text
    r=case.client.post(url,data=dict(care_time_category='standard',effective_from='2026-04-01',guardian_reason_1='employment'),follow_redirects=False)
    assert r.status_code==303 and r.headers['location'].startswith(url+'?')
    with Session(case.engine) as s:
        cert=s.exec(select(ChildCareCertification).where(ChildCareCertification.child_id==case.child_id)).one()
        cert_id=cert.id
    r=case.client.post(url+f'/{cert_id}/deactivate',data=dict(deactivation_reason='取消'),follow_redirects=False)
    assert r.status_code==303
    with Session(case.engine) as s:
        assert not s.get(ChildCareCertification,cert_id).is_active
        child=s.get(Child,case.child_id);child.family_id=case.family_id;s.add(child);s.commit()
    r=case.client.get(url,follow_redirects=False)
    assert r.status_code==303 and r.headers['location'].startswith(case.endpoint+'?') and r.headers['location'].endswith(f'#child-{case.child_id}')


def test_detail_readonly_current_and_source_history(case):
    from routers.children import router
    case.app.include_router(router)
    save(case)
    r=case.client.get(f'/children/{case.child_id}')
    assert r.status_code==200,r.text
    section=r.text.split('<section id="care-certifications"',1)[1].split('</section>',1)[0]
    assert '家族共通を使用中' in section and '保育認定を変更' in section and '認定履歴を確認' in section
    assert '<form' not in section and '<input' not in section and '/deactivate' not in section
    assert f'/families/{case.family_id}/care-certifications#child-{case.child_id}' in section
    with Session(case.engine) as s:
        child=s.get(Child,case.individual_id)
        assert child_care_context(s,child)['care_mode_label']=='園児個別設定'


def test_common_to_individual_only_changes_selected_child(case):
    before=save(case)
    p=dict(revision=before['revision'],childId=case.child_id,cert=dict(before['store']['common'],category='short'),reason='園児の通知に合わせる')
    r=case.client.post(case.endpoint+'/save-individual',json=p)
    assert r.status_code==200,r.text
    assert r.json()['store']['common']==before['store']['common']
    assert r.json()['store']['children'][str(case.future_id)]==before['store']['children'][str(case.future_id)]
    assert r.json()['store']['children'][str(case.child_id)]['mode']=='individual'


def test_aggregate_save_keeps_individual_correction_reason(case):
    from models import ChildCareCertificationAuditLog
    p=payload(case)
    p['draft']['children'][str(case.individual_id)]['cert']['category']='standard'
    p['individualReasons']={str(case.individual_id):'園児通知の転記訂正'}
    save(case,p)
    with Session(case.engine) as s:
        logs=s.exec(select(ChildCareCertificationAuditLog).where(ChildCareCertificationAuditLog.child_id==case.individual_id)).all()
        assert any(x.reason=='園児通知の転記訂正' for x in logs)
