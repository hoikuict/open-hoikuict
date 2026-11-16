"""Existing-child invitations use only the invited guardian; legacy submissions stay readable."""
from copy import deepcopy
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from sqlmodel import Session, select

from child_profile_changes import child_profile_form_data_from_child
from local_auth import AuthenticationFailed
from models import Child, Family, ParentAccount, ParentChildLink, ParentEnrollment, ParentMailDelivery, ParentRegistrationRequest
from parent_enrollment import GUARDIAN_ONLY_FIELDS, GUARDIAN_ONLY_SCOPE, enrollment_state, submit_enrollment
from test_parent_enrollment import invite, open_form, profile, review
from test_guardian_account_sync import pilot as pilot_fixture
from time_utils import utc_now
import routers.parent_auth as routes


@pytest.fixture
def pilot(monkeypatch):
    yield from pilot_fixture.__wrapped__(monkeypatch)


def own_profile(**extra):
    return {**{key: value for key, value in profile().items() if key in GUARDIAN_ONLY_FIELDS}, **extra}


class Inputs(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.names = []
        self.required = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in {"input", "textarea", "select"} or not attrs.get("name") or attrs.get("type") == "hidden":
            return
        self.names.append(attrs["name"])
        if "required" in attrs:
            self.required.append(attrs["name"])


@pytest.mark.parametrize("order", [0, 1])
def test_existing_invite_only_accepts_own_fields_and_preserves_ledger(pilot, order):
    client, engine, ids, _ = pilot
    with Session(engine) as session:
        child = session.get(Child, ids["child"])
        child.extra_data = {"allergy": ["Milk"], "medical_notes": "園の記録", "staff_only": "個別メモ"}
        session.add(child)
        session.commit()
        before = deepcopy(child_profile_form_data_from_child(child))
        sibling = session.get(Child, ids["sibling"])
        sibling_birth = sibling.birth_date
        before_profiles = deepcopy(child.family.guardian_profiles())
    registration_id, account_id, token = invite(pilot, child_id=ids["child"], guardian_order=order)
    with Session(engine) as session:
        delivery = session.exec(select(ParentMailDelivery)).one()
        assert delivery.subject == "保護者アカウント登録のお願い"
        assert "再入力は不要" in delivery.body and "入園に必要" not in delivery.body
    form = open_form(client, token, guardian_only=True)
    assert "no-store" in form.headers["cache-control"]
    assert set(Inputs(form.text).names) == set(GUARDIAN_ONLY_FIELDS)
    assert len(Inputs(form.text).required) == 6
    assert "旧住所" not in form.text and "園の記録" not in form.text
    assert ("09011112222" in form.text) == (order == 1)
    assert "園児情報の再入力は不要" in client.get(
        f"/parent-accounts/enrollment/new?child_id={ids['child']}&guardian_order={order}"
    ).text
    raw_state = client.cookies.get(routes.REGISTRATION_COOKIE)
    # Ignore extra fields, even malformed values, rather than validate or persist them.
    response = client.post('/parent-portal/register/enrollment', data=own_profile(
        g1_workplace='', g1_workplace_address='', g1_workplace_phone='',
        child_id=ids['sibling'], guardian_order=2, family_id=ids['other'],
        home_address='攻撃者の住所', last_name='違う園児', birth_date='invalid',
        medical_notes='x' * 3000, g2_last_name='別人', _input_scope='full',
    ))
    assert response.status_code == 200, response.text
    with Session(engine) as session:
        enrollment = session.get(ParentEnrollment, registration_id)
        assert set(enrollment.submitted_data) == {*GUARDIAN_ONLY_FIELDS, '_input_scope'}
        assert enrollment.submitted_data['_input_scope'] == GUARDIAN_ONLY_SCOPE
        assert not session.exec(select(ParentChildLink)).all()
        assert session.get(Family, ids['family']).guardian_profiles() == before_profiles
        assert child_profile_form_data_from_child(session.get(Child, ids['child'])) == before
    admin = client.get(f'/parent-accounts/{account_id}/authentication')
    assert '在園児の保護者登録' in admin.text and '家族共通の住所や電話は変更しません' in admin.text
    assert '保護者・続柄' in admin.text and '保護者2・' not in admin.text
    assert '攻撃者の住所' not in admin.text and '旧形式の提出内容' not in admin.text
    assert review(client, account_id, registration_id, enrollment_confirmed='').status_code == 400
    assert review(client, account_id, registration_id).status_code == 303
    assert review(client, account_id, registration_id).status_code == 400
    client.cookies.set(routes.REGISTRATION_COOKIE, raw_state)
    assert client.post('/parent-portal/register/enrollment', data=own_profile(), follow_redirects=False).status_code == 303
    with Session(engine) as session:
        child = session.get(Child, ids['child'])
        after = child_profile_form_data_from_child(child)
        for key in ('child_data', 'home_address', 'home_phone'):
            assert after[key] == before[key]
        assert child.extra_data['staff_only'] == '個別メモ'
        assert child.registration_verification_name == 'ケンショウ アオイ'
        assert session.get(Child, ids['sibling']).birth_date == sibling_birth
        assert session.get(Family, ids['family']).home_address == '旧住所'
        profiles = child.family.guardian_profiles()
        target_order = 3 if order == 0 else order
        for original in before_profiles:
            updated = next(p for p in profiles if p['order'] == original['order'])
            if original['order'] != target_order:
                assert all(updated[key] == value for key, value in original.items())
                assert all(value in ('', None) for key, value in updated.items() if key not in original)
            else:
                assert updated['workplace'] == original['workplace']
                assert updated['workplace_address'] == original['workplace_address']
                assert updated['workplace_phone'] == original['workplace_phone']
        assert session.get(ParentAccount, account_id).email == 'intake@example.test'
        assert [(link.parent_account_id, link.child_id) for link in session.exec(select(ParentChildLink)).all()] == [(account_id, ids['child'])]
        assert len(session.exec(select(Child)).all()) == 2
        assert session.exec(select(ParentMailDelivery).where(ParentMailDelivery.message_type == 'completion')).one()


@pytest.mark.parametrize('missing', ['g1_last_name', 'g1_first_name', 'g1_last_name_kana', 'g1_first_name_kana', 'g1_relationship', 'g1_phone'])
def test_missing_required_guardian_field_keeps_input_without_submission(pilot, missing):
    client, engine, ids, _ = pilot
    registration_id, _, token = invite(pilot, child_id=ids['child'], guardian_order=0)
    open_form(client, token, guardian_only=True)
    response = client.post('/parent-portal/register/enrollment', data=own_profile(**{missing:''}))
    assert response.status_code == 400 and '検証会社' in response.text
    assert set(Inputs(response.text).names) == set(GUARDIAN_ONLY_FIELDS)
    with Session(engine) as session:
        assert session.get(ParentEnrollment, registration_id).submitted_data is None
        assert session.get(ParentRegistrationRequest, registration_id).status == 'invited'


@pytest.mark.parametrize('order', [0, 1])
def test_previously_submitted_full_form_stays_legacy_and_can_be_reviewed(pilot, order):
    client, engine, ids, _ = pilot
    registration_id, account_id, token = invite(pilot, child_id=ids['child'], guardian_order=order)
    open_form(client, token, guardian_only=True)
    # Model a request already submitted before the upgrade: no format marker.
    with Session(engine) as session:
        state, registration, enrollment, _ = enrollment_state(session, client.cookies.get(routes.REGISTRATION_COOKIE))
        from parent_enrollment import validate_enrollment_data
        enrollment.submitted_data = validate_enrollment_data(profile(last_name='検証', first_name='葵'), existing_child=True)
        registration.status = 'pending_review'
        registration.submitted_at = utc_now()
        state.consumed_at = utc_now()
        session.add_all([state, registration, enrollment])
        session.commit()
    admin = client.get(f'/parent-accounts/{account_id}/authentication')
    assert '旧形式の提出内容' in admin.text and '入園予定日' in admin.text
    assert review(client, account_id, registration_id).status_code == 303
    with Session(engine) as session:
        child = session.get(Child, ids['child'])
        assert child.birth_date.isoformat() == ('2021-05-04' if order == 0 else '2023-06-10')
        assert child.home_address == ('旧住所' if order == 0 else '検証用の住所')


def test_new_enrollment_cannot_choose_guardian_only_with_post_fields(pilot):
    client, engine, _, _ = pilot
    registration_id, _, token = invite(pilot)
    form = open_form(client, token, guardian_only=False)
    assert len(Inputs(form.text).names) == 28
    assert len(Inputs(form.text).required) == 13
    response = client.post('/parent-portal/register/enrollment', data=own_profile(
        _input_scope=GUARDIAN_ONLY_SCOPE, guardian_only='true', child_id=999,
    ))
    assert response.status_code == 400 and '子どもの姓を入力' in response.text
    with Session(engine) as session:
        assert session.get(ParentEnrollment, registration_id).submitted_data is None


def test_unsubmitted_old_invitation_and_resend_use_new_form(pilot):
    client, engine, ids, _ = pilot
    registration_id, account_id, token = invite(pilot, child_id=ids['child'], guardian_order=1)
    # Old and new unsubmitted invitations share the same persisted target/snapshot.
    with Session(engine) as session:
        assert '_input_scope' not in session.get(ParentEnrollment, registration_id).source_snapshot
    open_form(client, token, guardian_only=True)
    old_state = client.cookies.get(routes.REGISTRATION_COOKIE)
    with Session(engine) as session:
        delivery = session.exec(select(ParentMailDelivery)).one()
        delivery.created_at = utc_now() - timedelta(minutes=2)
        session.add(delivery)
        session.commit()
    response = client.post(f'/parent-accounts/{account_id}/authentication/invite', data={'reason':'再送'}, follow_redirects=False)
    assert response.status_code == 303
    with Session(engine) as session:
        with pytest.raises(AuthenticationFailed):
            submit_enrollment(session, old_state, own_profile())
        newest = session.exec(select(ParentMailDelivery).order_by(ParentMailDelivery.created_at.desc())).first()
        assert newest.subject == '保護者アカウント登録のお願い'
        token = newest.body.split('#')[1].split()[0]
    open_form(client, token, guardian_only=True)
    assert client.post('/parent-portal/register/enrollment', data=own_profile()).status_code == 200


def test_guardian_form_escapes_child_name_and_input_errors(pilot):
    client, engine, ids, _ = pilot
    with Session(engine) as session:
        child = session.get(Child, ids['child'])
        child.first_name = '<script>alert(1)</script>'
        session.add(child)
        session.commit()
    _, _, token = invite(pilot, child_id=ids['child'], guardian_order=0)
    form = open_form(client, token, guardian_only=True)
    assert '<script>alert(1)</script>' not in form.text
    response = client.post('/parent-portal/register/enrollment', data=own_profile(g1_phone='', g1_workplace='<img src=x onerror=alert(1)>'))
    assert response.status_code == 400 and '<img src=x onerror=alert(1)>' not in response.text
