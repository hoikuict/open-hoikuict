"""Private kiosk ingress. Bind only to loopback behind the facility's TLS proxy.

The public app never supplies the ingress marker. This separate process replaces
untrusted forwarding headers and marks only kiosk paths; it holds no database or
staff/device credentials. Network publication is configured by the operator.
"""
import os
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx
from fastapi import FastAPI, Request
from starlette.background import BackgroundTask
from starlette.responses import JSONResponse, RedirectResponse, StreamingResponse


HOP_HEADERS = {"connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
               "te", "trailer", "transfer-encoding", "upgrade"}
MAX_BODY = 52 * 1024 * 1024


def make_client(upstream):
    return httpx.AsyncClient(base_url=upstream, follow_redirects=False, trust_env=False,
                             timeout=httpx.Timeout(45, connect=5))


@asynccontextmanager
async def lifespan(app):
    origin = os.environ["HOIKUICT_CLASS_KIOSK_ORIGIN"].rstrip("/")
    parsed = urlsplit(origin)
    marker = os.environ["HOIKUICT_CLASS_KIOSK_INGRESS_KEY"]
    upstream = os.getenv("HOIKUICT_CLASS_KIOSK_UPSTREAM", "http://app:8000")
    if parsed.scheme != "https" or not parsed.netloc or parsed.path or len(marker) < 32:
        raise RuntimeError("A private HTTPS origin and ingress key are required")
    app.state.origin, app.state.host, app.state.marker = origin, parsed.netloc, marker
    async with make_client(upstream) as client:
        app.state.client = client
        yield


app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


def kiosk_path(path):
    return path in {"/class-kiosk", "/settings/class-kiosk"} or path.startswith(("/class-kiosk/", "/settings/class-kiosk/"))


@app.api_route("/{path:path}", methods=["GET", "HEAD", "POST"])
async def proxy(request: Request, path: str):
    route = request.url.path
    if route == "/healthz" and request.method in {"GET", "HEAD"}:
        return JSONResponse({"ready": True})
    if request.headers.get("host", "").lower() != app.state.host.lower():
        return JSONResponse({"detail": "Unknown private host"}, status_code=400)
    if route == "/":
        return RedirectResponse("/class-kiosk/", status_code=303)
    allowed = kiosk_path(route) or route in {"/staff/login", "/staff/logout"} or route.startswith("/static/")
    if not allowed or "\\" in route or any(p in {".", ".."} for p in route.split("/")):
        return JSONResponse({"detail": "Not found"}, status_code=404)
    if route.startswith("/static/") and request.method not in {"GET", "HEAD"}:
        return JSONResponse({"detail": "Method not allowed"}, status_code=405)
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > MAX_BODY:
            return JSONResponse({"detail": "Upload too large"}, status_code=413)
    stripped = HOP_HEADERS | {"host", "content-length", "forwarded", "x-class-kiosk-ingress"}
    stripped |= {h.strip().lower() for h in request.headers.get("connection", "").split(",")}
    headers = [(k, v) for k, v in request.headers.items()
               if k.lower() not in stripped and not k.lower().startswith(("x-forwarded-", "tailscale-"))]
    headers += [("host", app.state.host), ("x-forwarded-proto", "https")]
    if kiosk_path(route):
        headers.append(("x-class-kiosk-ingress", app.state.marker))
    # Preserve the encoded path and query; never accept an upstream URL from input.
    target = request.scope["raw_path"].decode("ascii")
    if request.scope["query_string"]:
        target += "?" + request.scope["query_string"].decode("ascii")
    outgoing = app.state.client.build_request(request.method, target, headers=headers, content=bytes(body))
    try:
        upstream = await app.state.client.send(outgoing, stream=True)
    except httpx.HTTPError:
        return JSONResponse({"detail": "接続できません。しばらくして再取得してください。"}, status_code=502)
    excluded = HOP_HEADERS | {h.strip().lower() for h in upstream.headers.get("connection", "").split(",")}
    response = StreamingResponse(upstream.aiter_raw(), status_code=upstream.status_code,
                                 background=BackgroundTask(upstream.aclose))
    response.raw_headers = [(k, v) for k, v in upstream.headers.raw if k.decode().lower() not in excluded]
    location = response.headers.get("location", "")
    insecure_origin = "http://" + app.state.host
    if location.startswith(insecure_origin + "/"):
        response.headers["location"] = app.state.origin + location[len(insecure_origin):]
    response.headers["cache-control"] = "no-store"
    return response
