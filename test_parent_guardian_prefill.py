"""Prefill only the invited adult, and keep user edits on validation errors."""
from copy import deepcopy
from datetime import timedelta
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from sqlmodel import Session, select

from models import Child, Family, ParentEnrollment, ParentPublicRegistration, ParentRegistrationRequest
from parent_enrollment import GUARDIAN_FIELDS, guardian_prefill_values, enrollment_state
from test_guardian_account_sync import pilot as pilot_fixture
from test_parent_enrollment import invite, open_form, review
from test_parent_public_registration import begin, enable
from time_utils import utc_now
import routers.parent_auth as routes


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


class Values(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.values = {}
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input' and attrs.get('name', '').startswith('g1_'):
            self.values[attrs['name']] = attrs.get('value', '')


@pytest.mark.parametrize('order', [1, 2, 3])
def test_selected_guardian_prefills_all_nine_fields_and_submits_without_retyping(pilot, order):
    client, engine, ids, _ = pilot
    with Session(engine) as session:
        family = session.get(Family, ids['family'])
        profiles = [{**{key:f'本人{number}の{key}' for key in GUARDIAN_FIELDS}, 'order':number,
                     'email':f'private{number}@example.test', 'staff_note':'非公開メモ'} for number in [1, 2, 3]]
        family.shared_profile = {'guardians':profiles}
        session.add(family)
        session.commit()
        before = deepcopy(family.guardian_profiles())
    registration_id, account_id, token = invite(pilot, child_id=ids['child'], guardian_order=order)
    form = open_form(client, token, guardian_only=True)
    expected = {f'g1_{key}':profiles[order-1][key] for key in GUARDIAN_FIELDS}
    assert Values(form.text).values == expected
    assert form.context['prefilled_guardian']
    assert '登録情報を確認' in form.text and '未入力の必須項目だけ' in form.text
    assert form.headers['cache-control'] == 'private, no-store'
    assert form.headers['referrer-policy'] == 'no-referrer'
    for number in [1, 2, 3]:
        assert f'private{number}@example.test' not in form.text
        if number != order:
            assert f'本人{number}の' not in form.text
    assert '非公開メモ' not in form.text and '旧住所' not in form.text
    # GET query parameters cannot change the invitation's target.
    changed = client.get('/parent-portal/register/identity?guardian_order=99&child_id=999')
    assert Values(changed.text).values == expected
    assert client.post('/parent-portal/register/enrollment', data=Values(form.text).values).status_code == 200
    with Session(engine) as session:
        assert session.get(Family, ids['family']).guardian_profiles() == before
        assert session.get(ParentEnrollment, registration_id).applied_at is None
    assert review(client, account_id, registration_id).status_code == 303
    with Session(engine) as session:
        target = next(p for p in session.get(Family, ids['family']).guardian_profiles() if p['order']==order)
        assert {f'g1_{key}':target[key] for key in GUARDIAN_FIELDS} == expected


@pytest.mark.parametrize('kind', ['new_guardian', 'new_child', 'public'])
def test_new_and_public_registration_do_not_prefill_an_existing_guardian(pilot, kind):
    client, engine, ids, _ = pilot
    if kind == 'public':
        enable(pilot)
        registration_id, _, token = begin(pilot)
        with Session(engine) as session:
            assert session.get(ParentPublicRegistration, registration_id)
        form = client.post('/parent-portal/register/invite/verify', data={'token':token})
        assert form.status_code == 200
    else:
        extra = {'child_id':ids['child'], 'guardian_order':0} if kind == 'new_guardian' else {}
        _, _, token = invite(pilot, **extra)
        form = open_form(client, token)
    assert not form.context['prefilled_guardian']
    assert len(Values(form.text).values) == 9
    assert not any(Values(form.text).values.values())
    assert '試験会社' not in form.text and '09011112222' not in form.text


@pytest.mark.parametrize('missing', ['last_name','first_name','last_name_kana','first_name_kana','relationship','phone'])
def test_error_keeps_edited_and_cleared_values_instead_of_reloading_snapshot(pilot, missing):
    client, engine, ids, _ = pilot
    registration_id, _, token = invite(pilot, child_id=ids['child'], guardian_order=1)
    form = open_form(client, token)
    values = Values(form.text).values
    values.update(g1_first_name='修正後の本人', g1_phone='09099998888', g1_workplace='')
    values['g1_'+missing] = ''
    error = client.post('/parent-portal/register/enrollment', data=values)
    assert error.status_code == 400
    assert Values(error.text).values == values
    assert error.context['prefilled_guardian']
    with Session(engine) as session:
        assert session.get(ParentEnrollment, registration_id).submitted_data is None
        assert session.get(Family, ids['family']).guardian_profiles()[0]['workplace'] == '試験会社'


def test_partial_guardian_does_not_borrow_missing_fields_from_first_guardian(pilot):
    _, _, ids, _ = pilot
    _, _, token = invite(pilot, child_id=ids['child'], guardian_order=2)
    form = open_form(pilot[0], token)
    assert Values(form.text).values == {f'g1_{key}':{'last_name':'検証','first_name':'太郎','relationship':'父'}.get(key,'') for key in GUARDIAN_FIELDS}


@pytest.mark.parametrize('snapshot', [None, {}, {'profile':{}}, {'profile':{'guardians_data':'invalid'}},
    {'profile':{'guardians_data':[{'order':2,'phone':'other'}]}},
    {'profile':{'guardians_data':[{'order':1,'phone':'first'},{'order':1,'phone':'second'}]}}])
def test_missing_or_ambiguous_target_never_exposes_another_guardian(snapshot):
    enrollment = SimpleNamespace(child_id=1, guardian_order=1, source_snapshot=snapshot)
    assert guardian_prefill_values(enrollment) == {}


def test_public_scope_and_new_guardian_flags_block_prefill_even_with_snapshot():
    enrollment = SimpleNamespace(child_id=1, guardian_order=1, source_snapshot={'profile':{'guardians_data':[{'order':1,'phone':'private'}]}})
    assert guardian_prefill_values(enrollment, public_application=True) == {}
    enrollment.source_snapshot['adding_guardian'] = True
    assert guardian_prefill_values(enrollment) == {}


@pytest.mark.parametrize('invalid', ['expired','cancelled','consumed'])
def test_invalid_registration_session_cannot_read_prefilled_information(pilot, invalid):
    client, engine, ids, _ = pilot
    _, _, token = invite(pilot, child_id=ids['child'], guardian_order=1)
    open_form(client, token)
    with Session(engine) as session:
        state, registration, _, _ = enrollment_state(session, client.cookies.get(routes.REGISTRATION_COOKIE))
        if invalid == 'expired':
            state.expires_at = utc_now()-timedelta(seconds=1)
        elif invalid == 'consumed':
            state.consumed_at = utc_now()
        else:
            registration.status = 'cancelled'
        session.add_all([state, registration])
        session.commit()
    response = client.get('/parent-portal/register/identity', follow_redirects=False)
    assert response.status_code == 303 and response.headers['location'].endswith('state=invalid')
    assert '09011112222' not in response.text


def test_prefilled_values_are_html_escaped_and_get_does_not_consume_invitation(pilot):
    client, engine, ids, _ = pilot
    with Session(engine) as session:
        family = session.get(Family, ids['family'])
        profiles = deepcopy(family.guardian_profiles())
        profiles[0]['workplace'] = '\"><img src=x onerror=alert(1)>'
        family.shared_profile = {'guardians':profiles}
        session.add(family)
        session.commit()
    registration_id, _, token = invite(pilot, child_id=ids['child'], guardian_order=1)
    form = open_form(client, token)
    assert '<img src=x' not in form.text
    assert Values(form.text).values['g1_workplace'] == '\"><img src=x onerror=alert(1)>'
    assert Values(client.get('/parent-portal/register/identity').text).values == Values(form.text).values
    with Session(engine) as session:
        assert session.get(ParentRegistrationRequest, registration_id).status == 'invited'
        assert session.get(ParentEnrollment, registration_id).submitted_data is None
        assert len(session.exec(select(Child)).all()) == 2
