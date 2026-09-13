from datetime import timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel, Session, create_engine, select

from auth import Role
import database
from models import Classroom, DocumentReviewRequest, User
from plan_docs.auth_adapter import DEFAULT_NURSERY_REF
from plan_docs.contracts import DocumentStatus, DocumentType
from plan_docs.db_models import PlanReviewNotificationRow
from plan_docs.models import PlanDocument
from plan_docs.routers.documents import router as plans_router
from plan_docs.routers.home import router as plans_home_router
from plan_docs.store import SqlModelDocumentRepository
from routers.document_reviews import router as reviews_router
from routers.staff_portal import router as portal_router
from testing_helpers import authenticate_mock_staff
from time_utils import utc_now


@pytest.fixture
def portal(monkeypatch):
    monkeypatch.setenv("HOIKU_NURSERY_REF", DEFAULT_NURSERY_REF)
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
    SQLModel.metadata.create_all(engine)
    app = FastAPI()
    app.include_router(portal_router)
    app.include_router(reviews_router)
    app.include_router(plans_router, prefix="/plans")
    app.include_router(plans_home_router, prefix="/plans")

    def sessions():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[database.get_session] = sessions
    users = {}
    with Session(engine) as session:
        session.add(Classroom(name="ひよこ組"))
        for name, role in [("作成者", "can_edit"), ("園長", "admin"), ("別の職員", "can_edit")]:
            user = User(email=f"{role}-{len(users)}@example.test", display_name=name, staff_role=role)
            session.add(user)
            session.flush()
            users[name] = user.id
        session.commit()
    with TestClient(app) as client:
        yield client, engine, users
    engine.dispose()


def sign_in(client, users, name):
    authenticate_mock_staff(
        client, user_id=users[name], name=name,
        role=Role.ADMIN if name == "園長" else Role.CAN_EDIT,
    )


def return_plan(portal, document_type=DocumentType.DAILY_PLAN):
    client, engine, users = portal
    with Session(engine) as session:
        document = SqlModelDocumentRepository(session).create(PlanDocument(
            id=0, document_type=document_type, status=DocumentStatus.DRAFT,
            title=f"検証用 {document_type.value}", nursery_ref=DEFAULT_NURSERY_REF,
            classroom_ref="ひよこ組", actor_ref=f"staff:{users['作成者']}",
            owner_name="作成者", sections=[],
        ))
    sign_in(client, users, "作成者")
    url = f"/plans/documents/{document.id}"
    submitted = client.post(url + "/status", data={"status": "in_review", "lock_version": 1}, follow_redirects=False)
    assert submitted.status_code == 303, submitted.text
    sign_in(client, users, "園長")
    returned = client.post(url + "/status", data={
        "status": "rejected", "lock_version": 2, "comment": "活動のねらいを追記してください。",
    }, follow_redirects=False)
    assert returned.status_code == 303, returned.text
    with Session(engine) as session:
        notification = session.exec(select(PlanReviewNotificationRow).where(
            PlanReviewNotificationRow.document_id == document.id,
            PlanReviewNotificationRow.notification_kind == "review_outcome",
        )).one()
        notification_id = notification.id
    return document, notification_id


@pytest.mark.parametrize("creator_name", ["作成者", "園長"])
def test_returned_review_is_private_and_acknowledgement_keeps_decision(portal, creator_name):
    client, engine, users = portal
    sign_in(client, users, creator_name)
    created = client.post("/document-reviews/", data={"title": "提出文書の差し戻し検証"}, follow_redirects=False)
    assert created.status_code == 303
    url = created.headers["location"]
    assert 'id="returned-documents"' not in client.get("/").text
    sign_in(client, users, "園長")
    note = "日付を直してください。\n<script>alert('unsafe')</script>"
    returned = client.post(url + "/decision", data={"decision": "returned", "note": note}, follow_redirects=False)
    assert returned.status_code == 303

    sign_in(client, users, "別の職員")
    assert "提出文書の差し戻し検証" not in client.get("/").text
    assert client.post(url + "/dismiss-return", follow_redirects=False).status_code == 404
    if creator_name != "園長":
        sign_in(client, users, "園長")
        assert "提出文書の差し戻し検証" not in client.get("/").text
        assert client.post(url + "/dismiss-return", follow_redirects=False).status_code == 404
    client.cookies.clear()
    assert "提出文書の差し戻し検証" not in client.get("/").text

    sign_in(client, users, creator_name)
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="returned-documents"' in home.text
    assert "園長さんから差し戻されました" in home.text
    assert home.text.count("提出文書の差し戻し検証") == 1
    assert "日付を直してください。" in home.text
    assert "<script>alert('unsafe')</script>" not in home.text
    assert "&lt;script&gt;" in home.text
    assert home.text.index('id="returned-documents"') < home.text.index('id="attendance"')
    assert "no-store" in home.headers["cache-control"]
    assert client.get(url).status_code == 200
    assert "提出文書の差し戻し検証" in client.get("/").text
    assert client.post(url + "/dismiss-return", follow_redirects=False).status_code == 303
    with Session(engine) as session:
        item = session.get(DocumentReviewRequest, int(url.rsplit("/", 1)[1]))
        acknowledged_at = item.return_acknowledged_at
        assert acknowledged_at is not None
        assert item.status == "returned" and item.decision_note == note
    assert client.post(url + "/dismiss-return", follow_redirects=False).status_code == 303
    assert 'id="returned-documents"' not in client.get("/").text
    assert "日付を直してください。" in client.get(url).text
    with Session(engine) as session:
        assert session.get(DocumentReviewRequest, int(url.rsplit("/", 1)[1])).return_acknowledged_at == acknowledged_at


@pytest.mark.parametrize("document_type", [DocumentType.DAILY_PLAN, DocumentType.WEEKLY_PLAN, DocumentType.MONTHLY_PLAN])
def test_plan_return_appears_on_home_until_confirmed(portal, document_type):
    client, engine, users = portal
    document, notification_id = return_plan(portal, document_type)
    sign_in(client, users, "作成者")
    home = client.get("/")
    assert home.status_code == 200
    assert 'id="returned-documents"' in home.text
    assert home.text.count(document.title) == 1
    assert "活動のねらいを追記してください。" in home.text
    notification_url = f"/plans/notifications/{notification_id}"
    opened = client.post(notification_url + "/open", follow_redirects=False)
    assert opened.headers["location"] == f"/plans/documents/{document.id}"
    assert document.title in client.get("/").text
    sign_in(client, users, "別の職員")
    assert document.title not in client.get("/").text
    assert client.post(notification_url + "/dismiss", follow_redirects=False).status_code == 404
    sign_in(client, users, "作成者")
    assert client.post(notification_url + "/dismiss", follow_redirects=False).status_code == 303
    assert document.title not in client.get("/").text
    assert "活動のねらいを追記してください。" in client.get(f"/plans/documents/{document.id}").text
    with Session(engine) as session:
        assert session.get(PlanReviewNotificationRow, notification_id).resolved_at is not None


def test_home_combines_both_return_types_and_excludes_other_statuses(portal):
    client, engine, users = portal
    document, _ = return_plan(portal)
    with Session(engine) as session:
        for index, status in enumerate(["returned", "pending", "approved"]):
            session.add(DocumentReviewRequest(
                title=f"文書確認 {status}", requested_by_user_id=users["作成者"],
                requested_by_name="作成者", status=status, decision_note="確認用の理由",
                decided_at=utc_now() + timedelta(minutes=index + 1),
            ))
        session.commit()
    sign_in(client, users, "作成者")
    home = client.get("/")
    assert home.status_code == 200
    assert home.text.count(">2件<") == 2
    assert home.text.index("文書確認 returned") < home.text.index(document.title)
    for status in ["pending", "approved"]:
        assert f"文書確認 {status}" not in home.text
        with Session(engine) as session:
            item = session.exec(select(DocumentReviewRequest).where(DocumentReviewRequest.status == status)).one()
            item_id = item.id
        assert client.post(f"/document-reviews/{item_id}/dismiss-return", follow_redirects=False).status_code == 404
    sign_in(client, users, "別の職員")
    assert 'id="returned-documents"' not in client.get("/").text


def test_legacy_review_migration_preserves_returned_records_and_is_repeatable(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql("""CREATE TABLE document_review_requests (
                id INTEGER PRIMARY KEY, title VARCHAR(200) NOT NULL, body VARCHAR NOT NULL,
                requested_by_user_id CHAR(32), requested_by_name VARCHAR NOT NULL,
                status VARCHAR NOT NULL, attachments JSON NOT NULL, decision_note VARCHAR NOT NULL,
                decided_by_user_id CHAR(32), decided_by_name VARCHAR, decided_at DATETIME,
                created_at DATETIME NOT NULL)""")
            connection.exec_driver_sql("""INSERT INTO document_review_requests
                (id, title, body, requested_by_name, status, attachments, decision_note, created_at)
                VALUES (1, '既存の依頼', '本文', '作成者', 'returned', '[]', '既存の差し戻し理由', '2026-09-13 00:00:00')""")
        monkeypatch.setattr(database, "engine", engine)
        database.create_db_and_tables()
        database.create_db_and_tables()
        with Session(engine) as session:
            item = session.get(DocumentReviewRequest, 1)
            assert item.title == "既存の依頼" and item.status == "returned"
            assert item.decision_note == "既存の差し戻し理由"
            assert item.return_acknowledged_at is None
    finally:
        engine.dispose()
