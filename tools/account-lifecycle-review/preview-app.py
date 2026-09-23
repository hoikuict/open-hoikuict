"""Local-only implementation preview. Fresh synthetic in-memory DB; no mail worker."""
from pathlib import Path
import os
import sys

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
os.environ.update({
    "HOIKUICT_ENV": "test", "HOIKUICT_PARENT_AUTH_MODE": "local_password",
    "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture", "HOIKUICT_ENABLE_MOCK_AUTH": "0",
    "HOIKUICT_PARENT_REGISTRATION_BASE_URL": "http://127.0.0.1:8877",
    "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "local-synthetic-lifecycle-preview-key",
    "HOIKUICT_CSRF_ENFORCE": "1",
})

from datetime import date
from fastapi import Depends, FastAPI
from fastapi.staticfiles import StaticFiles
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine
import uvicorn

import database
import auth
from auth import Role, StaffUser, get_current_staff_user
from csrf import CsrfTokenMiddleware, verify_csrf
from models import Child, ParentAccount, ParentChildLink, User
from parent_auth import ensure_parent_credential, hash_password, disable_parent_authentication
from routers import parent_accounts, parent_auth

engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
database.engine = engine
auth._parent_portal_auth_backend = auth.LocalPasswordParentPortalAuthBackend()
SQLModel.metadata.create_all(engine)
with Session(engine) as session:
    actor = User(email="admin@example.test", display_name="見本の管理者", staff_role="admin")
    account = ParentAccount(display_name="見本 さくら", email="guardian@example.test",
        registration_verification_name="ミホン サクラ", registration_verification_name_type="kana",
        phone="000-0000-0000", home_address="見本市あおぞら町1-2-3", workplace="架空の勤務先",
        workplace_address="見本市若葉町4-5-6", workplace_phone="000-0000-1111")
    session.add_all([actor, account])
    session.flush()
    actor_id = actor.id
    for number in range(100):
        child = Child(last_name="架空", first_name=f"園児{number + 1:03d}",
            last_name_kana="カクウ", first_name_kana=f"エンジ{number + 1:03d}",
            birth_date=date(2022, 4, 1), enrollment_date=date(2026, 4, 1),
            registration_verification_name=f"カクウ エンジ{number + 1}", registration_verification_name_type="kana")
        session.add(child)
        session.flush()
        if number < 98:
            session.add(ParentChildLink(parent_account_id=account.id, child_id=child.id))
    credential = ensure_parent_credential(session, account)
    credential.password_hash = hash_password("Synthetic!Preview9284")
    session.add(credential)
    session.commit()
    disable_parent_authentication(session, account, actor, "架空データでの一時停止")

app = FastAPI(dependencies=[Depends(verify_csrf)])
app.add_middleware(CsrfTokenMiddleware)
app.include_router(parent_accounts.router)
app.include_router(parent_auth.router)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
def get_session():
    with Session(engine) as session:
        yield session
app.dependency_overrides[database.get_session] = get_session
app.dependency_overrides[get_current_staff_user] = lambda: StaffUser(
    role=Role.ADMIN, name="確認用・架空データ", user_id=actor_id)

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8877)
