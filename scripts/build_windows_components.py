"""Build-time download of official Windows components; never run by the installer.

Downloads always verify the committed lock. Caddy uses a fixed, digest-pinned
release archive, never the mutable public build service.
The resulting executables are covered by the application's release manifest.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import shutil
import tempfile
import zipfile
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

ROOT = Path(__file__).resolve().parents[1]
HOSTS = {"github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def check(url):
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in HOSTS or parsed.username or parsed.password or parsed.port not in {None, 443}:
        raise ValueError("untrusted component source")


class Redirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        check(newurl)
        return super().redirect_request(request, fp, code, message, headers, newurl)


def verify(path, digest, size):
    if path.stat().st_size != size:
        raise ValueError("component size mismatch")
    with path.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != digest:
            raise ValueError("component checksum mismatch")


def download(entry, path, opener):
    check(entry["url"])
    size = entry["bytes"]
    if type(size) is not int or not 0 < size <= 512 * 1024 * 1024:
        raise ValueError("invalid download size")
    with opener.open(Request(entry["url"], headers={"User-Agent": "OpenHoikuICT-Build/3"}), timeout=120) as response, path.open("xb") as output:
        received = 0
        while block := response.read(1024 * 1024):
            received += len(block)
            if received > size:
                raise ValueError("download exceeds locked size")
            output.write(block)
    verify(path, entry["sha256"], size)


def acquire(name, entry, output, opener):
    destination = output / name
    if destination.exists():
        verify(destination, entry["sha256"], entry["bytes"])
        return destination
    with tempfile.TemporaryDirectory(prefix=".components-", dir=output) as scratch:
        scratch = Path(scratch)
        candidate = scratch / name
        if "archive" in entry:
            archive = scratch / "release.zip"
            download(entry["archive"], archive, opener)
            with zipfile.ZipFile(archive) as package:
                members = [item for item in package.infolist() if item.filename == entry["member"]]
                if len(members) != 1 or members[0].file_size != entry["bytes"]:
                    raise ValueError("unexpected component archive member")
                # Copy only one exact member; never extract paths chosen by ZIP.
                with package.open(members[0]) as source, candidate.open("xb") as target:
                    shutil.copyfileobj(source, target)
        else:
            download(entry, candidate, opener)
        verify(candidate, entry["sha256"], entry["bytes"])
        with candidate.open("rb") as stream:
            if stream.read(2) != b"MZ":
                raise ValueError("not a Windows executable")
        candidate.rename(destination)
    return destination


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    lock = json.loads((ROOT / "windows_setup/components-lock.json").read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    opener = build_opener(Redirect())
    for name in ("caddy.exe", "winsw.exe", "cloudflared.exe"):
        acquire(name, lock[name], args.output, opener)
        print(f"Verified {name}", flush=True)
    modules = subprocess.check_output([str(args.output / "caddy.exe"), "list-modules", "--versions"], text=True)
    version = subprocess.check_output([str(args.output / "caddy.exe"), "version"], text=True).strip()
    if modules.splitlines() != lock["caddy.exe"]["modules"] or version != lock["caddy.exe"]["version"]:
        raise ValueError("Caddy version/modules mismatch")
    print("All Windows components verified.", flush=True)


if __name__ == "__main__":
    main()
