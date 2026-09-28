from datetime import timedelta
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import child_records.models  # noqa: F401
import plan_docs.db_models  # noqa: F401
from auth import Role
from models import (
    AttendanceAlarmState, AttendanceVerification, AttendanceVerificationStatus,
    Child, ChildStatus, Classroom, StaffClassroomAssignment, Survey,
    SurveyAnswerUnit, SurveyAudienceType, SurveyStatus, SurveyTarget,
    SurveyTargetType, User,
)
import routers.staff_portal as portal
from testing_helpers import authenticate_mock_staff, configure_test_environment
from time_utils import local_today, utc_now


@pytest.fixture(params=[Role.ADMIN, Role.CAN_EDIT, Role.VIEW_ONLY])
def nursery(request):
    configure_test_environment()
    engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(portal.router)

    def get_session():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[portal.get_session] = get_session
    today = local_today()
    with Session(engine) as session:
        user = User(email='attention@example.invalid', display_name='確認職員', staff_role=request.param.value)
        session.add(user)
        session.flush()
        for index, count in enumerate((7, 15, 20, 20, 17, 19)):
            classroom = Classroom(name=f'架空{index + 1}組', display_order=index)
            session.add(classroom)
            session.flush()
            if index < 4:
                session.add(StaffClassroomAssignment(staff_user_id=user.id, classroom_id=classroom.id,
                    starts_on=today, display_order=index))
            for number in range(count):
                session.add(Child(last_name=f'架空{index + 1}', first_name=f'園児{number + 1}',
                    last_name_kana='カクウ', first_name_kana='エンジ', classroom_id=classroom.id,
                    birth_date=today - timedelta(days=900), enrollment_date=today - timedelta(days=10),
                    status=ChildStatus.enrolled))
        session.commit()
        user_id = user.id
    with TestClient(app) as client:
        authenticate_mock_staff(client, role=request.param, user_id=user_id, name='確認職員')
        yield client, engine, user_id, request.param
    engine.dispose()


def test_count_uses_all_assignments_and_links_to_matching_list(nursery):
    client, _, _, role = nursery
    for url, visible in [('/?scope=assigned', 3), ('/?scope=all', 6), ('/staff/portal?scope=all', 6)]:
        response = client.get(url)
        assert response.status_code == 200
        assert response.context['attention_count'] == 62
        assert not response.context['attention_error']
        assert len(response.context['attendance_summaries']) == visible
        assert response.context['attention_url'] == '/staff/attention'
        assert 'href="/staff/attention?scope=all"' not in response.text
        assert '集計対象：担当する全クラス' in response.text
        assert response.headers['cache-control'] == 'private, no-store'
    details = client.get('/staff/attention')
    assert details.context['attention_count'] == 62
    assert len(details.context['attention_items']) == 62
    assert '架空5 園児1' not in details.text
    all_details = client.get('/staff/attention?scope=all')
    assert all_details.context['attention_count'] == (98 if role == Role.ADMIN else 62)
    assert all_details.context['show_all'] == (role == Role.ADMIN)


def test_overlapping_assignments_do_not_duplicate_children_or_hide_fourth_class(nursery):
    client, engine, user_id, _ = nursery
    with Session(engine) as session:
        assignments = session.exec(select(StaffClassroomAssignment).order_by(StaffClassroomAssignment.id)).all()
        for item in assignments:
            session.add(StaffClassroomAssignment(staff_user_id=user_id, classroom_id=item.classroom_id,
                starts_on=local_today() - timedelta(days=1), ends_on=local_today(), display_order=item.display_order))
        session.commit()
    for url in ('/?scope=assigned', '/?scope=all', '/staff/attention'):
        response = client.get(url)
        assert response.context['attention_count'] == 62
        if url.startswith('/?scope=assigned'):
            assert len(response.context['attendance_summaries']) == 3
            assert response.context['classroom_remaining_count'] == 1
            assert response.context['assignment_remaining_count'] == 1


def test_expired_future_and_other_staff_assignments_do_not_expand_scope(nursery):
    client, engine, user_id, _ = nursery
    with Session(engine) as session:
        rooms = session.exec(select(Classroom).order_by(Classroom.id)).all()
        other = User(email='other@example.invalid', display_name='別職員')
        session.add(other)
        session.flush()
        today = local_today()
        session.add_all([
            StaffClassroomAssignment(staff_user_id=user_id, classroom_id=rooms[4].id,
                starts_on=today - timedelta(days=5), ends_on=today - timedelta(days=1)),
            StaffClassroomAssignment(staff_user_id=user_id, classroom_id=rooms[5].id,
                starts_on=today + timedelta(days=1)),
            StaffClassroomAssignment(staff_user_id=other.id, classroom_id=rooms[4].id, starts_on=today),
        ])
        session.commit()
    for url in ('/?scope=assigned', '/?scope=all', '/staff/attention'):
        assert client.get(url).context['attention_count'] == 62


def test_unassigned_staff_count_only_their_pending_surveys(nursery):
    client, engine, _, role = nursery
    with Session(engine) as session:
        for item in session.exec(select(StaffClassroomAssignment)).all():
            session.delete(item)
        survey = Survey(title='研修希望（架空）', status=SurveyStatus.published,
            audience_type=SurveyAudienceType.staff, answer_unit=SurveyAnswerUnit.staff_user,
            closes_at=utc_now() + timedelta(days=1))
        session.add(survey)
        session.flush()
        session.add(SurveyTarget(survey_id=survey.id, target_type=SurveyTargetType.all_staff))
        session.commit()
    for url in ('/?scope=assigned', '/?scope=all', '/staff/attention'):
        response = client.get(url)
        assert response.context['attention_count'] == 1
        if url == '/staff/attention':
            assert response.context['attendance_attention_count'] == 0
            assert response.context['survey_attention_count'] == 1
            assert not response.context['show_all']
        elif url == '/?scope=assigned':
            assert len(response.context['attendance_summaries']) == (6 if role == Role.ADMIN else 0)
    assert client.get('/staff/attention?scope=all').context['attention_count'] == (99 if role == Role.ADMIN else 1)


def test_unknown_and_alarm_count_once_and_confirmed_children_drop_out(nursery):
    client, engine, _, _ = nursery
    with Session(engine) as session:
        children = session.exec(select(Child).order_by(Child.id)).all()
        for child in children:
            session.add(AttendanceVerification(child_id=child.id, target_date=local_today(),
                status=AttendanceVerificationStatus.present))
        session.flush()
        unknown = session.exec(select(AttendanceVerification).where(AttendanceVerification.child_id == children[0].id)).one()
        unknown.status = AttendanceVerificationStatus.unknown
        for child in (children[0], children[42], children[-1]):
            session.add(AttendanceAlarmState(child_id=child.id, target_date=local_today(), is_active=True,
                reasons=['missing_arrival']))
        session.commit()
    for url in ('/?scope=assigned', '/?scope=all', '/staff/attention'):
        assert client.get(url).context['attention_count'] == 2


def test_all_confirmed_has_zero_attention(nursery):
    client, engine, _, _ = nursery
    with Session(engine) as session:
        for child in session.exec(select(Child)).all():
            session.add(AttendanceVerification(child_id=child.id, target_date=local_today(),
                status=AttendanceVerificationStatus.present))
        session.commit()
    assert client.get('/?scope=all').context['attention_count'] == 0
    details = client.get('/staff/attention')
    assert details.context['attention_count'] == 0
    assert '現在、確認が必要な項目はありません。' in details.text


def test_attention_failure_is_visible_in_header_and_card(nursery):
    client, _, _, _ = nursery
    real_build = portal.build_attendance_summaries

    def fail_personal(session, classrooms, day, **kwargs):
        if len(classrooms) == 4:
            raise RuntimeError('fixture: personal attention unavailable')
        return real_build(session, classrooms, day, **kwargs)

    with patch.object(portal, 'build_attendance_summaries', side_effect=fail_personal):
        for url in ('/?scope=assigned', '/?scope=all', '/staff/attention'):
            response = client.get(url)
            assert response.status_code == 200
            assert response.context['attention_error']
            assert '取得不可' in response.text
            assert '要確認情報を取得できませんでした。' in response.text
            if url != '/staff/attention':
                assert not response.context['attendance_error']


def test_attendance_card_failure_does_not_replace_personal_attention(nursery):
    client, _, _, _ = nursery
    real_build = portal.build_attendance_summaries

    def fail_visible(session, classrooms, day, **kwargs):
        if len(classrooms) == 3:
            raise RuntimeError('fixture: visible attendance unavailable')
        return real_build(session, classrooms, day, **kwargs)

    with patch.object(portal, 'build_attendance_summaries', side_effect=fail_visible):
        response = client.get('/?scope=assigned')
        assert response.context['attendance_error']
        assert not response.context['attention_error']
        assert response.context['attention_count'] == 62
