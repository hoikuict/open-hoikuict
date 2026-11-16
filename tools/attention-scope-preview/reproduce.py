"""Reproduce the deployed count mismatch with an isolated in-memory nursery."""
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / '.local-dev/truenas-monthly-export-20260927/source'
sys.dont_write_bytecode = True
sys.path[:0] = [str(SOURCE), str(ROOT)]
os.chdir(SOURCE)
os.environ['HOIKUICT_DATABASE_URL'] = 'sqlite://'
os.environ['HOIKUICT_ENV'] = 'development'

from datetime import timedelta
import json
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
import child_records.models  # noqa: F401
import plan_docs.db_models  # noqa: F401
from auth import Role
from models import Child, ChildStatus, Classroom, StaffClassroomAssignment, User
import routers.staff_portal as portal
from testing_helpers import authenticate_mock_staff, configure_test_environment
from time_utils import local_today

assert Path(portal.__file__).resolve().is_relative_to(SOURCE)
configure_test_environment()
results = []
for role in (Role.ADMIN, Role.CAN_EDIT):
    for assigned in (6, 4):
        engine = create_engine('sqlite://', connect_args={'check_same_thread': False}, poolclass=StaticPool)
        SQLModel.metadata.create_all(engine)
        app = FastAPI()
        app.include_router(portal.router)

        def session_override():
            with Session(engine) as session:
                yield session

        app.dependency_overrides[portal.get_session] = session_override
        today = local_today()
        with Session(engine) as session:
            user = User(email='fixture@example.invalid', display_name='確認用職員', staff_role=role.value)
            session.add(user)
            session.flush()
            for index, count in enumerate((7, 15, 20, 20, 17, 19)):
                classroom = Classroom(name=f'架空{index + 1}組', display_order=index)
                session.add(classroom)
                session.flush()
                if index < assigned:
                    session.add(StaffClassroomAssignment(staff_user_id=user.id, classroom_id=classroom.id,
                                                        starts_on=today, display_order=index))
                for number in range(count):
                    session.add(Child(last_name=f'架空{index}', first_name=f'園児{number}',
                        last_name_kana='カクウ', first_name_kana='エンジ', classroom_id=classroom.id,
                        birth_date=today - timedelta(days=900), enrollment_date=today - timedelta(days=10), status=ChildStatus.enrolled))
            session.commit()
            user_id = user.id
        with TestClient(app) as client:
            authenticate_mock_staff(client, role=role, user_id=user_id, name='確認用職員')
            row = dict(role=role.value, assigned_classes=assigned)
            for label, url in [('home_assigned', '/?scope=assigned'), ('home_all', '/?scope=all'), ('attention_assigned', '/staff/attention')]:
                response = client.get(url)
                assert response.status_code == 200
                assert not response.context.get('attention_error'), response.context.get('attention_error')
                row[label] = response.context['attention_count']
            assert row['home_assigned'] == 42
            assert row['home_all'] == 98
            assert row['attention_assigned'] == (98 if assigned == 6 else 62)
            results.append(row)
        engine.dispose()
out = dict(source_commit='4581393839d40d0e4eddbf71b9b4b28a7ba461ea', database='in-memory fictional data only', results=results)
path = ROOT / 'docs/verification-attention-scope-2026-09-28.json'
path.write_text(json.dumps(out, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print(json.dumps(out, ensure_ascii=False, indent=2))
