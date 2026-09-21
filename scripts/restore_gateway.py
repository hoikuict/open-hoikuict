"""Keep the public endpoint alive while the unprivileged app process is stopped.

Only the fixed local application is proxied. The gateway has no Docker/host access,
and the job capability permits reading one job, never changing data or restoring.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import urllib.request

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, Response, StreamingResponse
import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake
from jinja2 import Environment, FileSystemLoader, select_autoescape
from starlette.background import BackgroundTask

from restore_control import (
    STEPS, TERMINAL, RestoreError, heartbeat, maintenance, read_job, viewer_allowed, viewer_cookie,
)

logger = logging.getLogger("open_hoikuict.restore_gateway")
TEMPLATES = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[1] / "templates"),
                        autoescape=select_autoescape(["html"]))
JOB_PATH = re.compile(r"/settings/backups/restore/jobs/([0-9a-f-]{36})$")
HOP_HEADERS = {b"connection", b"keep-alive", b"proxy-authenticate", b"proxy-authorization", b"te", b"trailer", b"transfer-encoding", b"upgrade"}


class Supervisor:
    def __init__(self):
        self.process = None
        self.mode = "stopped"
        self.healthy = False
        self.job_id = None
        self.failed_mode = None
        self.http = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def stop(self):
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=40)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=10)
        self.process = None
        self.healthy = False
        self.mode = "stopped"

    def start(self, mode: str):
        environment = {**os.environ, "HOIKUICT_RESTORE_PROBE": "1" if mode == "probe" else "0",
                       "FORWARDED_ALLOW_IPS": "127.0.0.1"}
        self.process = subprocess.Popen([sys.executable, "-m", "uvicorn", "main:app", "--host", "127.0.0.1",
                                         "--port", "8001", "--proxy-headers", "--timeout-graceful-shutdown", "30"],
                                        env=environment)
        self.mode = mode

    def tick(self):
        try:
            marker = maintenance()
            wanted = marker.get("mode") if marker else "normal"
            if wanted == "resume":
                wanted = "normal"
            self.job_id = marker.get("job_id") if marker else None
            if wanted not in {"normal", "stop", "probe"}:
                raise RestoreError("Invalid maintenance mode")
        except Exception:
            wanted = "stop"
        if wanted == "stop":
            self.stop()
            self.failed_mode = None
        else:
            if self.process and self.process.poll() is not None:
                # Do not repeatedly boot a failing image while the executor decides rollback.
                self.stop()
                self.failed_mode = wanted if wanted == "probe" else None
            if self.mode != wanted and self.failed_mode != wanted:
                self.stop()
                self.start(wanted)
            if self.process and self.process.poll() is None:
                try:
                    with self.http.open("http://127.0.0.1:8001/healthz", timeout=2) as response:
                        self.healthy = response.status == 200
                except Exception:
                    self.healthy = False
            else:
                self.healthy = False
        heartbeat("gateway", mode=self.mode, stopped=self.process is None,
                  healthy=self.healthy, job_id=self.job_id)

    def serving(self) -> bool:
        try:
            return maintenance() is None and self.mode == "normal" and self.healthy
        except RestoreError:
            return False


def status_response(job: dict) -> HTMLResponse:
    markup = TEMPLATES.get_template("backups/restore_progress.html").render(
        job=job, steps=STEPS, terminal=job["state"] in TERMINAL)
    return HTMLResponse(markup, headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer",
                                         "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY"})


def unavailable(message="現在、復元または起動確認を行っています。完了までお待ちください。", status=503):
    markup = TEMPLATES.get_template("backups/restore_maintenance.html").render(message=message, retry=status == 503)
    return HTMLResponse(markup, status_code=status, headers={"Cache-Control": "no-store", "Retry-After": "5",
                                                           "X-Content-Type-Options": "nosniff"})


def without_hop_headers(headers):
    ignored = set(HOP_HEADERS)
    for key, value in headers:
        if key.lower() == b"connection":
            ignored.update(part.strip().lower() for part in value.split(b","))
    return [(k, v) for k, v in headers if k.lower() not in ignored]


def create_gateway(supervisor: Supervisor | None = None) -> FastAPI:
    supervisor = supervisor or Supervisor()

    @asynccontextmanager
    async def lifespan(app):
        stop = asyncio.Event()
        async def supervise():
            while not stop.is_set():
                await asyncio.to_thread(supervisor.tick)
                try:
                    await asyncio.wait_for(stop.wait(), timeout=1)
                except TimeoutError:
                    pass
        task = asyncio.create_task(supervise())
        async with httpx.AsyncClient(trust_env=False, follow_redirects=False,
                                     timeout=httpx.Timeout(None, connect=5, pool=10)) as client:
            app.state.client = client
            try:
                yield
            finally:
                stop.set()
                await task
                await asyncio.to_thread(supervisor.stop)

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    @app.websocket("/{path:path}")
    async def websocket_route(websocket: WebSocket, path: str):
        if not supervisor.serving():
            await websocket.close(code=1013)
            return
        raw_path = websocket.scope.get("raw_path", websocket.url.path.encode()).decode("ascii")
        query = websocket.scope.get("query_string", b"").decode("ascii")
        # Preserve the public Host/Origin for the app's origin checks. Socket destination
        # is fixed independently of the URI and environment proxies are disabled.
        uri = "ws://" + websocket.headers.get("host", "localhost") + raw_path + ("?" + query if query else "")
        headers = [(k.decode("latin-1"), v.decode("latin-1")) for k, v in without_hop_headers(websocket.headers.raw)
                   if k.lower() not in {b"host", b"x-forwarded-for", b"x-forwarded-proto", b"forwarded"}
                   and not k.lower().startswith(b"sec-websocket-")]
        headers += [("x-forwarded-proto", "https" if websocket.scope["scheme"] == "wss" else "http"),
                    ("x-forwarded-for", websocket.client.host if websocket.client else "127.0.0.1")]
        try:
            async with connect(uri, host="127.0.0.1", port=8001, proxy=None, additional_headers=headers,
                               subprotocols=websocket.scope.get("subprotocols") or None,
                               max_size=16 * 1024 * 1024) as upstream:
                await websocket.accept(subprotocol=upstream.subprotocol)

                async def to_app():
                    while True:
                        message = await websocket.receive()
                        if message["type"] == "websocket.disconnect":
                            return
                        await upstream.send(message.get("bytes") if message.get("bytes") is not None else message["text"])

                async def to_browser():
                    async for message in upstream:
                        if isinstance(message, bytes):
                            await websocket.send_bytes(message)
                        else:
                            await websocket.send_text(message)

                tasks = [asyncio.create_task(to_app()), asyncio.create_task(to_browser())]
                try:
                    done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        task.result()
                finally:
                    for task in tasks:
                        task.cancel()
                    await asyncio.gather(*tasks, return_exceptions=True)
        except (OSError, ValueError, InvalidHandshake, ConnectionClosed, WebSocketDisconnect):
            pass
        finally:
            from contextlib import suppress
            with suppress(RuntimeError, WebSocketDisconnect):
                await websocket.close(code=1001)

    @app.api_route("/{path:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def route(request: Request, path: str):
        matched = JOB_PATH.fullmatch(request.url.path)
        if matched:
            if request.method not in {"GET", "HEAD"}:
                return Response(status_code=405)
            try:
                job_id = matched.group(1)
                job = read_job(job_id)
                if not viewer_allowed(job, request.cookies.get(viewer_cookie(job_id))):
                    return unavailable("この作業を表示する権限がありません。管理者としてログインし、復元履歴から開いてください。", 403)
                return status_response(job)
            except RestoreError:
                return unavailable("復元の作業記録を確認できません。運用担当者に確認してください。", 404)
        if not supervisor.serving():
            return unavailable()
        raw_path = request.scope.get("raw_path", request.url.path.encode()).decode("ascii")
        query = request.scope.get("query_string", b"").decode("ascii")
        target = "http://127.0.0.1:8001" + raw_path + ("?" + query if query else "")
        headers = [(k, v) for k, v in without_hop_headers(request.headers.raw)
                   if k.lower() not in {b"x-forwarded-for", b"x-forwarded-proto", b"forwarded"}]
        # Uvicorn has already checked the configured trusted proxy before setting scope.
        headers += [(b"x-forwarded-proto", request.scope["scheme"].encode()),
                    (b"x-forwarded-for", (request.client.host if request.client else "127.0.0.1").encode())]
        try:
            upstream = await app.state.client.send(app.state.client.build_request(
                request.method, target, headers=headers, content=request.stream()), stream=True)
        except httpx.HTTPError:
            return unavailable()
        response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                     background=BackgroundTask(upstream.aclose))
        response.raw_headers = without_hop_headers(upstream.headers.raw)
        return response

    return app


if __name__ == "__main__":
    import uvicorn
    logging.basicConfig(level=logging.INFO)
    os.umask(0o077)
    uvicorn.run(create_gateway(), host="0.0.0.0", port=8000, proxy_headers=True,
                forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"))
