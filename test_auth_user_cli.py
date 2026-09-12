import io
import json
from unittest.mock import patch

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

import database
from local_auth import ACTION_CODE_LENGTH
from models import (
    CredentialActionToken,
    InitialAdminBootstrapAudit,
    PasswordCredential,
    User,
)
from scripts import auth_user


@pytest.fixture
def bootstrap_db(monkeypatch):
    engine = create_engine("sqlite://", poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    monkeypatch.setattr(database, "engine", engine)
    with patch.object(auth_user, "create_db_and_tables") as initialize:
        yield engine, initialize
    engine.dispose()


@pytest.fixture
def values():
    return dict(display_name="園長", email="admin@example.com", login_id="principal",
                reason="初期導入", actor="山田 太郎", approver="鈴木 花子")


def test_utf8_bom_file_creates_admin_and_audit_once(tmp_path, values, bootstrap_db, capsys):
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(values, ensure_ascii=False), encoding="utf-8-sig")
    args = ["bootstrap-admin", "--input-json", str(path), "--yes"]
    assert auth_user.main(args) == 0
    output = capsys.readouterr().out
    assert len(output.splitlines()[-2]) == ACTION_CODE_LENGTH
    engine, initialize = bootstrap_db
    with Session(engine) as session:
        user = session.exec(select(User)).one()
        assert user.display_name == "園長"
        assert user.email == values["email"]
        assert user.staff_role == "admin"
        credential = session.exec(select(PasswordCredential)).one()
        assert credential.password_hash is None
        audit = session.exec(select(InitialAdminBootstrapAudit)).one()
        assert (audit.reason, audit.actor, audit.approver) == (
            values["reason"], values["actor"], values["approver"])
    assert auth_user.main(args) == 2
    assert "既に存在" in capsys.readouterr().err
    with Session(engine) as session:
        assert len(session.exec(select(User)).all()) == 1
        assert len(session.exec(select(CredentialActionToken)).all()) == 1
    assert initialize.call_count == 2


def test_stdin_reads_utf8_bytes_even_if_terminal_decoder_is_wrong(values, bootstrap_db, monkeypatch):
    raw = json.dumps(values, ensure_ascii=False).encode("utf-8")
    stream = io.TextIOWrapper(io.BytesIO(raw), encoding="ascii", errors="surrogateescape")
    monkeypatch.setattr("sys.stdin", stream)
    with patch("builtins.input", side_effect=AssertionError("Must not prompt")):
        assert auth_user.main(["bootstrap-admin", "--input-json", "-", "--yes"]) == 0
    with Session(bootstrap_db[0]) as session:
        assert session.exec(select(User)).one().display_name == "園長"


@pytest.mark.parametrize("mutation", [
    lambda v: {**v, "display_name": "\udce7"},
    lambda v: {**v, "approver": "\ud800"},
    lambda v: {**v, "email": None},
    lambda v: {**v, "actor": "  "},
    lambda v: {**v, "login_id": 1},
    lambda v: {**v, "password": "do-not-echo-this-value"},
    lambda v: {k: value for k, value in v.items() if k != "reason"},
    lambda v: [v],
])
def test_invalid_fields_do_not_initialize_or_write_database(
    mutation, tmp_path, values, bootstrap_db, capsys,
):
    path = tmp_path / "invalid.json"
    path.write_text(json.dumps(mutation(values)), encoding="utf-8")
    assert auth_user.main(["bootstrap-admin", "--input-json", str(path), "--yes"]) == 2
    bootstrap_db[1].assert_not_called()
    with Session(bootstrap_db[0]) as session:
        assert session.exec(select(User)).all() == []
    output = capsys.readouterr()
    assert "do-not-echo-this-value" not in output.err + output.out
    assert "Traceback" not in output.err


@pytest.mark.parametrize("raw", [
    b'not-json-do-not-echo', b'\xff', b'{"actor":"one", "actor":"two"}',
    b' ' * (auth_user.MAX_BOOTSTRAP_JSON_BYTES + 1),
], ids=["syntax", "encoding", "duplicate-key", "oversize"])
def test_bad_json_fails_before_database(raw, tmp_path, bootstrap_db, capsys):
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    assert auth_user.main(["bootstrap-admin", "--input-json", str(path), "--yes"]) == 2
    bootstrap_db[1].assert_not_called()
    assert "do-not-echo" not in capsys.readouterr().err


def test_missing_file_does_not_initialize_database(tmp_path, bootstrap_db):
    assert auth_user.main([
        "bootstrap-admin", "--input-json", str(tmp_path / "missing.json"), "--yes",
    ]) == 2
    bootstrap_db[1].assert_not_called()


@pytest.mark.parametrize("args", [["--yes"], ["--input-json", "-"]])
def test_explicit_json_consent_is_required(args, bootstrap_db):
    with patch("builtins.input", side_effect=AssertionError("Must not prompt")):
        assert auth_user.main(["bootstrap-admin", *args]) == 2
    bootstrap_db[1].assert_not_called()


def test_file_confirmation_can_cancel(tmp_path, values, bootstrap_db):
    path = tmp_path / "bootstrap.json"
    path.write_text(json.dumps(values), encoding="utf-8")
    with patch("builtins.input", return_value="no"):
        assert auth_user.main(["bootstrap-admin", "--input-json", str(path)]) == 1
    bootstrap_db[1].assert_not_called()


def test_interactive_surrogate_input_is_rejected_without_writes(values, bootstrap_db, capsys):
    values["display_name"] = "\udce7"
    with patch("builtins.input", side_effect=list(values.values())):
        assert auth_user.main(["bootstrap-admin"]) == 2
    bootstrap_db[1].assert_not_called()
    assert "--input-json" in capsys.readouterr().err


def test_existing_interactive_flow_still_works(values, bootstrap_db):
    with patch("builtins.input", side_effect=[*values.values(), "yes"]):
        assert auth_user.main(["bootstrap-admin"]) == 0
