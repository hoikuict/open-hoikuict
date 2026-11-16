"""Real Caddy -> restore gateway -> Uvicorn checks using fictional accounts.

Set HOIKUICT_TEST_CADDY to the digest-pinned Windows binary. CI runs these in
its Windows job. All listeners and data are isolated; no service, DNS, mail,
certificate store, or installed application is changed.
"""
from contextlib import contextmanager, ExitStack
import json
import os
from pathlib import Path
import socket
import subprocess
import threading
import time
from types import SimpleNamespace

from fastapi import FastAPI, Form, Request, WebSocket
from fastapi.responses import JSONResponse
import httpx
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine
import uvicorn
from websockets.sync.client import connect

from local_auth import AuthenticationFailed, LoginThrottled, authenticate_staff, hash_password
from models import ParentAccount, ParentAccountStatus, PasswordCredential, User
from parent_auth import authenticate_parent
from scripts import restore_gateway
from scripts.build_windows_components import verify
from windows_setup.configuration import caddy_config


@contextmanager
def serve(app):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(128)
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, proxy_headers=True,
            forwarded_allow_ips="127.0.0.1", access_log=False, log_level="error",
            loop="asyncio", http="h11", ws="websockets",
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline, "Uvicorn failed to start"
                time.sleep(0.02)
            yield port
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive(), "Test server did not stop"


def unused_port():
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


@pytest.fixture
def proxy_chain(tmp_path, monkeypatch):
    configured = os.getenv("HOIKUICT_TEST_CADDY")
    if not configured:
        pytest.skip("Windows CI supplies HOIKUICT_TEST_CADDY")
    binary = Path(configured).resolve()
    lock = json.loads(Path("windows_setup/components-lock.json").read_text(encoding="utf-8"))["caddy.exe"]
    verify(binary, lock["sha256"], lock["bytes"])
    for name, value in {
        "HOIKUICT_ENV": "test", "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": "t" * 40,
        "HOIKUICT_SECRET_KEY": "s" * 40,
    }.items():
        monkeypatch.setenv(name, value)
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    password = "Fictional!Password2026"
    password_hash = hash_password(password)
    with Session(engine) as session:
        parent = ParentAccount(display_name="架空保護者", email="parent@example.test", status=ParentAccountStatus.active)
        staff = User(display_name="架空職員", email="staff@example.test", staff_role="admin", is_active=True)
        session.add_all([parent, staff])
        session.flush()
        for role, owner in [("parent", {"parent_account_id": parent.id}), ("staff", {"staff_user_id": staff.id})]:
            session.add(PasswordCredential(principal_type=role, login_id="valid", login_id_normalized="valid",
                                           password_hash=password_hash, **owner))
        session.commit()
    app = FastAPI()

    @app.get("/peer")
    def peer(request: Request):
        return {"client": request.client.host, "scheme": request.url.scheme,
                "forwarded_for": request.headers.get("x-forwarded-for")}

    @app.websocket("/peer")
    async def websocket_peer(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"client": websocket.client.host, "scheme": websocket.scope["scheme"]})
        await websocket.close()

    @app.post("/login/{role}")
    def login(role: str, request: Request, login_id: str = Form(...), password: str = Form(...)):
        authenticate = {"parent": authenticate_parent, "staff": authenticate_staff}[role]
        with Session(engine) as session:
            try:
                authenticate(session, login_id=login_id, password=password, request=request)
            except LoginThrottled:
                return JSONResponse({"result": "blocked"}, status_code=429)
            except AuthenticationFailed:
                return JSONResponse({"result": "invalid"}, status_code=401)
        return {"result": "ok"}

    try:
        with ExitStack() as stack:
            app_port = stack.enter_context(serve(app))
            monkeypatch.setattr(restore_gateway, "APP_PORT", app_port)
            # Use the production proxy routes, but never launch/supervise a real app.
            supervisor = SimpleNamespace(tick=lambda: None, stop=lambda: None, serving=lambda: True)
            gateway_port = stack.enter_context(serve(restore_gateway.create_gateway(supervisor)))
            config = caddy_config({"tls": "internal", "localHostname": "proxy.test", "ip": "127.0.0.1"},
                                  tmp_path, "e" * 32, {"publicHostname": "public.test"})
            servers = config["apps"]["http"]["servers"]
            ports = {name: unused_port() for name in servers}
            assert len(set(ports.values())) == len(ports)
            for name, server in servers.items():
                server["listen"] = [f"127.0.0.1:{ports[name]}"]
                # TLS issuance is separate from client IP forwarding. Exercise
                # the generated proxy and trust rules over loopback HTTP only.
                server.pop("tls_connection_policies", None)
                server["automatic_https"] = {"disable": True}
                server["routes"][0]["handle"][1]["upstreams"] = [{"dial": f"127.0.0.1:{gateway_port}"}]
            config["apps"] = {"http": {"servers": servers}}
            config["admin"]["config"] = {"persist": False}
            config_path = tmp_path / "caddy.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")
            log_path = tmp_path / "caddy.log"
            log = stack.enter_context(log_path.open("wb"))
            child_env = {**os.environ, "XDG_DATA_HOME": str(tmp_path / "data"), "XDG_CONFIG_HOME": str(tmp_path / "config")}
            process = subprocess.Popen([str(binary), "run", "--config", str(config_path)],
                                       stdin=subprocess.DEVNULL, stdout=log, stderr=log, env=child_env,
                                       creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
            try:
                client = stack.enter_context(httpx.Client(trust_env=False, timeout=10, headers={"Host": "proxy.test"}))
                deadline = time.monotonic() + 10
                while True:
                    assert process.poll() is None, log_path.read_text(encoding="utf-8")
                    try:
                        ready = client.get(f"http://127.0.0.1:{ports['tunnel']}/peer")
                        ready.raise_for_status()
                        break
                    except httpx.ConnectError:
                        assert time.monotonic() < deadline, "Caddy failed to start"
                        time.sleep(0.05)
                yield client, ports, password
            finally:
                process.terminate()
                try:
                    process.wait(10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(10)
    finally:
        engine.dispose()


@pytest.mark.parametrize("visitor", ["198.51.100.10", "203.0.113.20", "2001:db8::123"])
def test_tunnel_preserves_visitor_through_gateway_and_ignores_spoofed_xff(proxy_chain, visitor):
    client, ports, _ = proxy_chain
    response = client.get(f"http://127.0.0.1:{ports['tunnel']}/peer", headers={
        "CF-Connecting-IP": visitor, "X-Forwarded-For": "192.0.2.99, 192.0.2.100",
        "Forwarded": "for=192.0.2.200", "X-Forwarded-Proto": "http",
    })
    assert response.json() == {"client": visitor, "scheme": "https", "forwarded_for": visitor}


def test_lan_never_trusts_cloudflare_or_forwarded_headers(proxy_chain):
    client, ports, _ = proxy_chain
    response = client.get(f"http://127.0.0.1:{ports['lan']}/peer", headers={
        "CF-Connecting-IP": "198.51.100.10", "X-Forwarded-For": "203.0.113.20",
    })
    assert response.json()["client"] == "127.0.0.1"


@pytest.mark.parametrize("visitor", [None, "invalid-ip"])
def test_missing_or_invalid_cloudflare_ip_does_not_fall_back_to_user_xff(proxy_chain, visitor):
    client, ports, _ = proxy_chain
    headers = {"X-Forwarded-For": "203.0.113.20"}
    if visitor:
        headers["CF-Connecting-IP"] = visitor
    response = client.get(f"http://127.0.0.1:{ports['tunnel']}/peer", headers=headers)
    assert response.json()["client"] == "127.0.0.1"


@pytest.mark.parametrize("role", ["parent", "staff"])
def test_login_failures_only_block_their_visitor(proxy_chain, role):
    client, ports, password = proxy_chain
    url = f"http://127.0.0.1:{ports['tunnel']}/login/{role}"
    attacker = {"CF-Connecting-IP": "198.51.100.10"}
    for index in range(20):
        response = client.post(url, headers=attacker, data={"login_id": f"missing{index}", "password": "wrong"})
        assert response.status_code == 401
    # Correct credentials on the blocked IP are rejected, even with forged XFF.
    assert client.post(url, headers={**attacker, "X-Forwarded-For": "203.0.113.20"},
                       data={"login_id": "valid", "password": password}).status_code == 429
    # Another visitor can still authenticate through the exact same proxy chain.
    assert client.post(url, headers={"CF-Connecting-IP": "203.0.113.20"},
                       data={"login_id": "valid", "password": password}).status_code == 200


def test_websocket_preserves_visitor_through_gateway(proxy_chain):
    _, ports, _ = proxy_chain
    with socket.create_connection(("127.0.0.1", ports["tunnel"])) as sock:
        with connect("ws://proxy.test/peer", sock=sock, proxy=None,
                     additional_headers={"CF-Connecting-IP": "198.51.100.10", "X-Forwarded-For": "203.0.113.20"}) as websocket:
            assert json.loads(websocket.recv()) == {"client": "198.51.100.10", "scheme": "wss"}
