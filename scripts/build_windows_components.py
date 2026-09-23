"""Build-time download of official Windows components; never run by the installer.

First use requires --record-lock. Subsequent builds verify the committed lock.
The resulting executables are covered by the application's release manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    "caddy.exe": "https://caddyserver.com/api/download?os=windows&arch=amd64&p=github.com%2Fcaddy-dns%2Fcloudflare",
    "winsw.exe": "https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET461.exe",
    "cloudflared.exe": "https://github.com/cloudflare/cloudflared/releases/download/2026.9.1/cloudflared-windows-amd64.exe",
}
KNOWN = {"cloudflared.exe": "2837888cc0f5d58f15b6dc478376de90b4d3ba5241c7947455d1e0a0df429712"}
HOSTS = {"caddyserver.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def check(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("untrusted component source")


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        check(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--record-lock", action="store_true")
    args = parser.parse_args()
    lock_path = ROOT / "windows_setup/components-lock.json"
    lock = {} if args.record_lock else json.loads(lock_path.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    result = {}
    opener = build_opener(Redirect())
    for name, url in SOURCES.items():
        check(url)
        path = args.output / name
        expected = KNOWN.get(name) or lock.get(name, {}).get("sha256")
        if not path.exists():
            request = Request(url, headers={"User-Agent": "OpenHoikuICT-Build/2"})
            with opener.open(request, timeout=120) as response, path.with_suffix(".partial").open("xb") as output:
                received = 0
                while block := response.read(1024 * 1024):
                    received += len(block)
                    if received > 150 * 1024 * 1024:
                        raise ValueError("component too large")
                    output.write(block)
            path.with_suffix(".partial").rename(path)
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
        if expected and digest != expected:
            raise ValueError("component checksum mismatch: " + name)
        if not expected and not args.record_lock:
            raise ValueError("missing component lock")
        with path.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("not a Windows executable")
        result[name] = {"url": url, "sha256": digest, "bytes": path.stat().st_size}
        print(json.dumps({"name": name, **result[name]}), flush=True)
    modules = subprocess.check_output([str(args.output / "caddy.exe"), "list-modules", "--versions"], text=True)
    if "dns.providers.cloudflare" not in modules:
        raise ValueError("Caddy must include the Cloudflare DNS module")
    result["caddy.exe"]["modules"] = modules.splitlines()
    result["caddy.exe"]["version"] = subprocess.check_output([str(args.output / "caddy.exe"), "version"], text=True).strip()
    if args.record_lock:
        lock_path.write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
    print("All Windows components verified.", flush=True)


if __name__ == "__main__":
    main()
