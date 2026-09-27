"""Non-administrator service supervision and a bounded loopback control endpoint."""
from __future__ import annotations

import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from urllib.request import ProxyHandler, build_opener

from scripts.restore_gateway import Supervisor
from windows_setup.storage import atomic_json, read_json


class WindowsSupervisor(Supervisor):
    def __init__(self):
        super().__init__()
        self.app_port = int(os.environ["HOIKUICT_GATEWAY_APP_PORT"])

    def start(self, mode: str):
        environment = {**os.environ, "HOIKUICT_RESTORE_PROBE": "1" if mode == "probe" else "0",
                       "FORWARDED_ALLOW_IPS": "127.0.0.1"}
        entry = Path(__file__).with_name("application_entry.py")
        self.process = subprocess.Popen([sys.executable, "-I", "-B", str(entry), str(self.app_port)],
                                        stdin=subprocess.PIPE, env=environment,
                                        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        self.mode = mode

    def stop(self):
        if self.process and self.process.poll() is None:
            try:
                self.process.stdin.write(b"STOP\n")
                self.process.stdin.flush()
                self.process.wait(timeout=40)
            except (OSError, subprocess.TimeoutExpired):
                self.process.terminate()
                self.process.wait(timeout=10)
        if self.process and self.process.stdin:
            self.process.stdin.close()
        self.process = None
        self.healthy = False
        self.mode = "stopped"


def run_application(port: int):
    import uvicorn
    from main import app
    from database import engine
    with socket.socket() as listener:
        if os.name == "nt":
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        listener.bind(("127.0.0.1", port))
        listener.listen(128)
        server = uvicorn.Server(uvicorn.Config(
            app, host="127.0.0.1", port=port, proxy_headers=True,
            forwarded_allow_ips="127.0.0.1", access_log=False, log_level="error",
            loop="asyncio", http="h11", ws="websockets", timeout_graceful_shutdown=30,
        ))
        thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
        thread.start()
        stop = threading.Event()
        threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
        try:
            while not stop.wait(.2):
                if not thread.is_alive():
                    raise RuntimeError('application_stopped')
        finally:
            server.should_exit = True
            thread.join(35)
            engine.dispose()


def run_gateway(settings: dict):
    import uvicorn
    from scripts.restore_gateway import create_gateway
    from starlette.responses import PlainTextResponse
    class ActivationGate:
        def __init__(self, app):
            self.app = app
        async def __call__(self, scope, receive, send):
            if scope['type'] in {'http', 'websocket'} and scope.get('path') != '/healthz' and not (Path(settings['root']) / 'ready').is_file():
                if scope['type'] == 'websocket':
                    await send({'type': 'websocket.close', 'code': 1013})
                else:
                    await PlainTextResponse('Server setup in progress', status_code=503)(scope, receive, send)
                return
            await self.app(scope, receive, send)
    gateway = create_gateway(WindowsSupervisor())
    gateway.add_middleware(ActivationGate)
    server = uvicorn.Server(uvicorn.Config(
        gateway, host="127.0.0.1",
        port=settings["ports"]["gateway"], proxy_headers=True,
        forwarded_allow_ips="127.0.0.1", access_log=False, log_level="error",
        ws="websockets", loop="asyncio", http="h11", timeout_graceful_shutdown=30,
    ))
    thread = threading.Thread(target=server.run)
    thread.start()
    stop = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), stop.set()), daemon=True).start()
    try:
        while not stop.wait(.2):
            if not thread.is_alive():
                raise RuntimeError('gateway_stopped')
    finally:
        server.should_exit = True
        thread.join(40)


class Service:
    def __init__(self, root: Path, settings: dict):
        self.root, self.settings = root, settings
        self.children = {}
        self.stopping = threading.Event()
        self.lock = threading.Lock()
        self.started = time.time()
        self.drill = {"state": "idle"}
        self.last_retention = 0
        self.http = build_opener(ProxyHandler({}))

    def status(self):
        from restore_control import service_state
        components = {name: process.poll() is None for name, process in self.children.items()}
        gateway = service_state("gateway")
        backup = service_state("backup")
        restore = service_state("worker")
        def fresh(record):
            return record.get('online', False) and record.get('seen', 0) >= self.started
        return {"running": all(components.values()) and bool(components),
                "components": components, "gateway": fresh(gateway) and gateway.get("healthy", False),
                "backup": fresh(backup), "restore": fresh(restore),
                "started_at": self.started, "drill": dict(self.drill),
                "public": bool(self.settings.get("public")),
                "instance": self.settings["instance"]}

    def spawn(self, name, arguments, environment=None):
        self.children[name] = subprocess.Popen(
            arguments, cwd=self.settings["code"] + "/app", env=environment or dict(os.environ),
            stdin=subprocess.PIPE if name == "gateway" else subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )

    def start(self):
        from windows_setup.mail_links import update_pending_links
        update_pending_links(self.settings)
        entry = Path(__file__).with_name("worker_entry.py")
        code = Path(self.settings["code"])
        for role in ("gateway", "backup", "restore"):
            self.spawn(role, [sys.executable, "-I", "-B", str(entry), str(self.root), role])
        env = {**os.environ, "CLOUDFLARE_API_TOKEN": self.settings["lan"].get("dnsToken", ""),
               'APPDATA': str(self.root / 'tls/profile'), 'XDG_CONFIG_HOME': str(self.root / 'tls/config'),
               'XDG_DATA_HOME': str(self.root / 'tls/data')}
        self.spawn("https", [str(code / "app/windows_setup/components/caddy.exe"), "run", "--config",
                            str(self.root / "config/caddy.json")], env)
        if self.settings.get("public"):
            env = {**os.environ, "TUNNEL_TOKEN": self.settings["public"]["tunnelToken"]}
            self.spawn("tunnel", [str(code / "app/windows_setup/components/cloudflared.exe"), "tunnel",
                                 "--no-autoupdate", "--loglevel", "error", "run"], env)

    def stop(self):
        self.stopping.set()
        # WinSW also kills the process tree if an owned child fails to stop.
        for name in ("tunnel", "https", "restore", "backup", "gateway"):
            child = self.children.get(name)
            if child and child.poll() is None:
                if name == "gateway" and child.stdin:
                    try:
                        child.stdin.write(b"STOP\n")
                        child.stdin.flush()
                    except OSError:
                        child.terminate()
                else:
                    child.terminate()
                try:
                    child.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    child.kill()
                    child.wait(timeout=10)
            if child and child.stdin:
                child.stdin.close()

    def begin_drill(self):
        with self.lock:
            if self.drill["state"] == "running":
                raise ValueError("busy")
            self.drill = {"state": "running"}
        threading.Thread(target=self._drill, daemon=True).start()

    def _drill(self):
        try:
            from windows_setup.recovery import recovery_drill
            result = recovery_drill(self.root)
            self.drill = {"state": "complete", **result}
        except Exception as error:
            self.drill = {"state": "failed", "message": "バックアップ・隔離復元の確認に失敗しました。",
                          "code": type(error).__name__}
        atomic_json(self.root / "drill-result.json", self.drill)

    def confirm(self, values: dict):
        state = read_json(self.root / "state.json")
        phase = values.get("phase")
        if phase == "lan":
            if not (values.get("otherDevice") is True and values.get("reboot") is True
                    and self.drill.get("state") == "complete"):
                raise ValueError("unconfirmed")
            if self.settings["lan"]["tls"] == "internal" and values.get("trust") is not True:
                raise ValueError("unconfirmed")
            health = self.status()
            if not all(health.get(key) for key in ("running", "gateway", "backup", "restore")):
                raise ValueError("unhealthy")
            state["lan_confirmed"] = True
        elif phase == "public":
            if not self.settings.get("public") or not state.get("lan_confirmed") or not all(
                values.get(key) is True for key in ("externalDevice", "externalMail", "externalReady")
            ):
                raise ValueError("unconfirmed")
            state["public_confirmed"] = True
        else:
            raise ValueError("invalid phase")
        atomic_json(self.root / "state.json", state)


class ControlHandler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def respond(self, code, value):
        data = json.dumps(value, ensure_ascii=True).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def authenticated(self):
        expected_host = "127.0.0.1:" + str(self.server.server_port)
        return (self.headers.get("Host") == expected_host and not self.headers.get("Origin")
                and hmac.compare_digest(self.headers.get("Authorization", ""),
                                        "Bearer " + self.server.service.settings["control_token"]))

    def do_GET(self):
        if not self.authenticated():
            self.respond(403, {"ok": False})
        elif self.path == "/status":
            self.respond(200, {"ok": True, **self.server.service.status()})
        else:
            self.respond(404, {"ok": False})

    def do_POST(self):
        if not self.authenticated():
            self.respond(403, {"ok": False})
            return
        try:
            if self.headers.get("Content-Type") != "application/json" or self.headers.get("Transfer-Encoding"):
                raise ValueError
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 4096:
                raise ValueError
            self.connection.settimeout(5)
            values = json.loads(self.rfile.read(length))
            if not isinstance(values, dict):
                raise ValueError
            if self.path == "/drill":
                self.server.service.begin_drill()
            elif self.path == "/confirm":
                self.server.service.confirm(values)
            else:
                self.respond(404, {"ok": False})
                return
            self.respond(200, {"ok": True})
        except (ValueError, OSError):
            self.respond(409, {"ok": False, "message": "確認状態を見直して再試行してください。"})


def run_service(root: Path, settings: dict):
    service = Service(root, settings)
    stop_file = root / "stop-requested"
    stop_file.unlink(missing_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", settings["ports"]["control"]), ControlHandler)
    server.daemon_threads = True
    server.service = service
    if (root / "drill-result.json").is_file():
        service.drill = read_json(root / "drill-result.json")
        if service.drill.get("state") == "running":
            service.drill = {"state": "failed", "message": "中断した復元確認をやり直してください。"}
    signal.signal(signal.SIGINT, lambda *_: service.stopping.set())
    signal.signal(signal.SIGTERM, lambda *_: service.stopping.set())
    serving = False
    try:
        service.start()
        threading.Thread(target=server.serve_forever, daemon=True).start()
        serving = True
        while not service.stopping.wait(2):
            if stop_file.exists():
                break
            if any(child.poll() is not None for child in service.children.values()):
                raise RuntimeError("component_stopped")
            atomic_json(root / "health.json", {**service.status(), "observed_at": time.time()})
            if time.monotonic() - service.last_retention > 3600 and service.drill['state'] != 'running':
                service.last_retention = time.monotonic()
                from windows_setup.retention import prune_backups
                threading.Thread(target=prune_backups, args=(settings,), daemon=True).start()
    finally:
        service.stop()
        if serving:
            server.shutdown()
        server.server_close()
