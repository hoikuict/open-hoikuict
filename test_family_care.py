from copy import deepcopy
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
import json

import pytest
from sqlmodel import Session, select

import test_care_certifications as legacy
from auth import Role
from child_care_certification_service import effective_certification
from family_care_service import bootstrap, materialize
from models import (Child, Family, ChildCareCertification, FamilyCareAudit,
    FamilyCareCertification, FamilyCareChildSetting, FamilyCareCertificationLink,
    ChildCareCertificationAuditLog, ExtendedCareCharge)
from routers.family_care import router


@pytest.fixture
def case():
    c = legacy.CareCertificationTests(); c.setUp(); c.app.include_router(router)
    with Session(c.engine) as session:
        first=session.get(Child,c.child_id); c.family_id=first.family_id
        for name, enrolled in [('予定',date(2026,10,15)), ('個別',date(2024,4,1))]:
            child=Child(last_name='検証',first_name=name,last_name_kana='ケンショウ',first_name_kana='エンジ',
                        birth_date=date(2023,4,1),enrollment_date=enrolled,family_id=c.family_id)
            session.add(child);session.flush()
            if name=='予定': c.future_id=child.id
            else: c.individual_id=child.id
        session.commit()
    c.client.post(f'/children/{c.individual_id}/care-certifications',data=dict(
        care_time_category='short', effective_from='2026-04-01',guardian_reason_1='employment',guardian_reason_2='employment'))
    c.endpoint=f'/families/{c.family_id}/care-certifications'
    yield c
    c.tearDown()


def state(c):
    with Session(c.engine) as session:
        return bootstrap(session,session.get(Family,c.family_id))


def payload(c, start='2026-10-01'):
    s=state(c)
    plan=dict(category='standard', **{'from':start,'to':''},reason1='employment',reason2='employment',other1='',other2='',note='確認用')
    return dict(revision=s['revision'],operation='new',editReason='',draft=dict(common=plan,children=deepcopy(s['store']['children'])))


def save(c,p=None):
    r=c.client.post(c.endpoint+'/save',json=p or payload(c)); assert r.status_code==200,r.text
    return r.json()


def count(c,model):
    with Session(c.engine) as s: return len(s.exec(select(model)).all())


def test_common_individual_and_enrollment_dates(case):
    result=save(case)
    with Session(case.engine) as s:
        assert effective_certification(s,case.child_id,date(2026,10,1)).care_time_category.value=='standard'
        assert effective_certification(s,case.future_id,date(2026,10,14)) is None
        assert effective_certification(s,case.future_id,date(2026,10,15)).care_time_category.value=='standard'
        assert effective_certification(s,case.individual_id,date(2026,10,1)).care_time_category.value=='short'
        assert s.exec(select(ExtendedCareCharge)).all()==[]
    assert result['store']['children'][str(case.individual_id)]['mode']=='individual'


def test_preview_rolls_back_all_rows(case):
    p=payload(case);before=count(case,ChildCareCertification)
    r=case.client.post(case.endpoint+'/preview',json=p)
    assert r.status_code==200,r.text
    assert count(case,FamilyCareAudit)==count(case,FamilyCareCertification)==count(case,FamilyCareChildSetting)==0
    assert count(case,ChildCareCertification)==before
    assert state(case)['revision']==p['revision']
    save(case,p)


def test_stale_submission_cannot_duplicate_or_overwrite(case):
    p=payload(case);save(case,p)
    assert case.client.post(case.endpoint+'/save',json=p).status_code==409
    assert count(case,FamilyCareCertification)==1


@pytest.mark.parametrize('field,value',[('category','invalid'),('from','bad'),('to','2026-09-30'),('reason1',''),('reason2','other_municipal'),('note','x'*501)])
def test_invalid_payload_is_atomic(case,field,value):
    p=payload(case);p['draft']['common'][field]=value
    assert case.client.post(case.endpoint+'/save',json=p).status_code==400
    assert count(case,FamilyCareCertification)==0
    assert count(case,ChildCareCertification)==1


def test_child_period_failure_rolls_back_common_and_first_child(case):
    p=payload(case);p['draft']['children'][str(case.individual_id)]['cert']['from']='2025-01-01'
    r=case.client.post(case.endpoint+'/save',json=p)
    assert r.status_code==400,r.text
    assert count(case,FamilyCareCertification)==0
    assert count(case,ChildCareCertification)==1


def test_new_period_ends_old_without_touching_individual(case):
    save(case);p=payload(case,'2026-11-01');p['draft']['common']['category']='short';save(case,p)
    with Session(case.engine) as s:
        assert effective_certification(s,case.child_id,date(2026,10,31)).care_time_category.value=='standard'
        assert effective_certification(s,case.child_id,date(2026,11,1)).care_time_category.value=='short'
        cert=s.get(ChildCareCertification,1); assert cert.effective_to is None
        assert len(s.exec(select(ChildCareCertificationAuditLog).where(ChildCareCertificationAuditLog.action=='period_ended')).all())==2


def test_correction_requires_reason_and_retains_audit(case):
    save(case);p=payload(case);p['operation']='correct';p['draft']['common']['category']='short'
    assert case.client.post(case.endpoint+'/save',json=p).status_code==400
    p['editReason']='通知の転記誤り';save(case,p)
    with Session(case.engine) as s:
        assert effective_certification(s,case.child_id,date(2026,10,1)).care_time_category.value=='short'
        log=s.exec(select(FamilyCareAudit).where(FamilyCareAudit.action=='correct')).one()
        assert log.reason=='通知の転記誤り' and log.before_snapshot['common']['category']=='standard'


def test_individual_to_common_switch_is_explicit(case):
    p=payload(case);p['draft']['children'][str(case.individual_id)]['mode']='inherit';save(case,p)
    with Session(case.engine) as s:
        assert effective_certification(s,case.individual_id,date(2026,9,30)).care_time_category.value=='short'
        assert effective_certification(s,case.individual_id,date(2026,10,1)).care_time_category.value=='standard'


def test_common_to_individual_keeps_personal_fields(case):
    save(case);p=payload(case,'2026-11-01');entry=p['draft']['children'][str(case.child_id)]
    entry['mode']='individual';entry['cert']=dict(p['draft']['common'],category='short',reason2='childcare_leave_continuation',note='個別の事情')
    save(case,p)
    with Session(case.engine) as s:
        cert=effective_certification(s,case.child_id,date(2026,11,5))
        assert cert.care_time_category.value=='short' and cert.internal_note=='個別の事情'
        assert cert.reasons[1].reason.value=='childcare_leave_continuation'


def test_deactivation_keeps_individual_and_does_not_revive_old_period(case):
    save(case);save(case,payload(case,'2026-11-01'))
    s=state(case)
    assert case.client.post(case.endpoint+'/deactivate',json=dict(revision=s['revision'],reason='')).status_code==400
    r=case.client.post(case.endpoint+'/deactivate',json=dict(revision=s['revision'],reason='誤登録の取消'))
    assert r.status_code==200 and r.json()['store']['common'] is None
    with Session(case.engine) as session:
        assert effective_certification(session,case.child_id,date(2026,11,1)) is None
        assert effective_certification(session,case.individual_id,date(2026,11,1)).care_time_category.value=='short'


def test_new_child_inherits_and_profile_update_does_not_erase(case):
    save(case)
    with Session(case.engine) as s:
        child=Child(last_name='新規',first_name='園児',last_name_kana='シンキ',first_name_kana='エンジ',
                    birth_date=date(2023,4,1),enrollment_date=date(2026,11,1),family_id=case.family_id)
        s.add(child);s.commit()
        assert effective_certification(s,child.id,date(2026,11,1)).care_time_category.value=='standard'
        family=s.get(Family,case.family_id);family.shared_profile={};s.add(family);s.commit()
        assert effective_certification(s,child.id,date(2026,11,1)).care_time_category.value=='standard'


def test_family_move_preserves_past_and_stops_old_common(case):
    save(case)
    with Session(case.engine) as s, patch('family_care_sync.local_today',return_value=date(2026,10,20)):
        family=Family(family_name='転出先');s.add(family);s.flush()
        child=s.get(Child,case.child_id);child.family_id=family.id;s.add(child);s.commit()
        assert effective_certification(s,child.id,date(2026,10,19)).care_time_category.value=='standard'
        assert effective_certification(s,child.id,date(2026,10,20)) is None


def test_membership_change_invalidates_open_form(case):
    p=payload(case)
    with Session(case.engine) as s:
        child=s.get(Child,case.child_id);child.first_name='名前変更';s.add(child);s.commit()
    assert case.client.post(case.endpoint+'/save',json=p).status_code==409


@pytest.mark.parametrize('role',[Role.VIEW_ONLY,Role.CAN_EDIT])
def test_permissions(case,role):
    case.current_user.role=role;case.current_user.can_manage_child_records=False
    assert case.client.get(case.endpoint).status_code in (403,401)
    assert case.client.post(case.endpoint+'/save',json=payload(case)).status_code in (403,401)


def test_get_is_readonly_and_renders_all_fields(case):
    response=case.client.get(case.endpoint)
    assert response.status_code==200,response.text
    assert '家族共通の保育認定' in response.text and 'data-state=' in response.text
    assert count(case,FamilyCareCertification)==0


def test_tampered_child_set_is_rejected(case):
    p=payload(case);p['draft']['children']['99999']=p['draft']['children'][str(case.child_id)]
    assert case.client.post(case.endpoint+'/save',json=p).status_code==400


def test_legacy_child_endpoint_cannot_desync_common_mode(case):
    save(case)
    r=case.client.post(f'/children/{case.child_id}/care-certifications',data=dict(
        care_time_category='short',effective_from='2027-01-01',guardian_reason_1='employment'))
    assert r.status_code==409


def test_common_ending_before_enrollment_never_revives_previous(case):
    save(case,payload(case,'2026-09-01'))
    p=payload(case,'2026-10-01');p['draft']['common']['to']='2026-10-10';save(case,p)
    with Session(case.engine) as s:
        assert effective_certification(s,case.future_id,date(2026,10,15)) is None


def test_family_move_inherits_new_family_from_change_date(case):
    save(case)
    with Session(case.engine) as s:
        family=Family(family_name='転入先',shared_profile={'guardians':[{'order':1,'last_name':'架空','first_name':'母','relationship':'母'}]})
        s.add(family);s.commit();new_id=family.id
        target=bootstrap(s,family)
    p=payload(case);p['revision']=target['revision'];p['draft']['children']={};p['draft']['common']['category']='short'
    assert case.client.post(f'/families/{new_id}/care-certifications/save',json=p).status_code==200
    with Session(case.engine) as s, patch('family_care_sync.local_today',return_value=date(2026,10,20)):
        child=s.get(Child,case.child_id);child.family_id=new_id;s.add(child);s.commit()
        assert effective_certification(s,child.id,date(2026,10,19)).care_time_category.value=='standard'
        assert effective_certification(s,child.id,date(2026,10,20)).care_time_category.value=='short'


def test_family_routes_require_csrf_for_save_and_preview(case,monkeypatch):
    from fastapi import FastAPI, Depends
    from fastapi.testclient import TestClient
    from csrf import verify_csrf, CsrfTokenMiddleware, CSRF_COOKIE_NAME
    monkeypatch.setenv('HOIKUICT_CSRF_ENFORCE','1')
    app=FastAPI(dependencies=[Depends(verify_csrf)]);app.add_middleware(CsrfTokenMiddleware)
    app.include_router(router);app.dependency_overrides=case.app.dependency_overrides
    with TestClient(app,base_url='https://testserver') as client:
        assert client.get(case.endpoint).status_code==200
        p=payload(case)
        for action in ('save','preview','deactivate'):
            assert client.post(case.endpoint+'/'+action,json=p).status_code==403
        assert client.post(case.endpoint+'/preview',json=p,headers={'X-CSRF-Token':client.cookies[CSRF_COOKIE_NAME]}).status_code==200


def test_readonly_verifier(case):
    from tools import verify_family_care_readonly
    with patch.object(verify_family_care_readonly,'engine',case.engine):
        assert verify_family_care_readonly.verify()['records_written']==0
