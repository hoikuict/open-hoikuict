"""Download a pinned, published GitHub release without installer credentials."""
from __future__ import annotations

import hashlib
from http.client import HTTPException
import json
from pathlib import Path
import platform
import re
import sys
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from beta_setup.core import Cancelled, SetupError

REPOSITORY = "hoikuict/open-hoikuict"
RELEASES_URL = f"https://github.com/{REPOSITORY}/releases"
API_URL = f"https://api.github.com/repos/{REPOSITORY}/releases/latest"
INSTALLER_PROTOCOL = 2
MAX_METADATA = 8 * 1024 * 1024
MAX_PACKAGE = 512 * 1024 * 1024
ALLOWED_HOSTS = {"api.github.com", "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com"}


def checked_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS
            or parsed.username or parsed.password or parsed.port not in {None, 443} or parsed.fragment):
        raise SetupError("配布元の接続先を確認できませんでした。", "release_invalid")
    return url


class ReleaseRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        checked_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def open_download(url: str):
    request = Request(checked_url(url), headers={
        "User-Agent": "OpenHoikuICT-Installer/1", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    try:
        return build_opener(ReleaseRedirect()).open(request, timeout=20)
    except HTTPError as error:
        if error.code == 404:
            raise SetupError("このPCに導入できる配布版はまだ公開されていません。", "release_unavailable") from None
        if error.code in {403, 429}:
            raise SetupError("GitHubへの接続が制限されています。時間を置いてもう一度確認してください。", "rate_limited") from None
        raise SetupError("GitHubから取得できませんでした。接続を確認して再試行してください。", "download_failed") from None
    except (URLError, OSError):
        raise SetupError("GitHubに接続できませんでした。インターネット接続を確認してください。", "download_failed") from None


def read_json(url: str, *, expected_hash: str | None = None) -> dict:
    try:
        with open_download(url) as response:
            raw = response.read(MAX_METADATA + 1)
        if len(raw) > MAX_METADATA or (expected_hash and hashlib.sha256(raw).hexdigest() != expected_hash):
            raise ValueError
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError
        return data
    except (ValueError, UnicodeError, OSError, HTTPException):
        raise SetupError("配布情報を確認できませんでした。もう一度取得してください。", "release_invalid") from None


def platform_key() -> str:
    if sys.platform == "win32" and platform.machine().lower() in {"amd64", "x86_64"}:
        return "windows-x64"
    raise SetupError("このOS向けの配布版は準備中です。現在はWindows 11 x64に対応しています。", "unsupported_platform")


def asset(release: dict, name: str, limit: int) -> dict:
    matches = [item for item in release.get("assets", []) if isinstance(item, dict) and item.get("name") == name]
    if len(matches) != 1:
        raise SetupError("このPC向けの配布ファイルはまだ公開されていません。", "release_unavailable")
    item = matches[0]
    digest = item.get("digest", "")
    expected_url = f"{RELEASES_URL}/download/{quote(release['tag_name'], safe='')}/{name}"
    if (item.get("state") != "uploaded" or not isinstance(item.get("id"), int)
            or not isinstance(item.get("size"), int) or not 0 < item["size"] <= limit
            or not isinstance(digest, str) or not re.fullmatch(r"sha256:[0-9a-f]{64}", digest)
            or item.get("browser_download_url") != expected_url):
        raise SetupError("配布ファイルの情報を確認できませんでした。", "release_invalid")
    return {"id": item["id"], "name": name, "size": item["size"], "sha256": digest[7:], "url": checked_url(expected_url)}


def latest_release() -> dict:
    key = platform_key()
    release = read_json(API_URL)
    tag = release.get("tag_name", "")
    if (release.get("draft") is not False or release.get("prerelease") is not False
            or not isinstance(release.get("id"), int) or not isinstance(tag, str)
            or not re.fullmatch(r"v[0-9][0-9A-Za-z.-]{0,79}", tag)
            or release.get("html_url") != f"{RELEASES_URL}/tag/{tag}"):
        raise SetupError("公開済みの配布版を確認できませんでした。", "release_invalid")
    description = asset(release, f"OpenHoikuICT-{key}.json", MAX_METADATA)
    payload = asset(release, f"OpenHoikuICT-{key}.zip", MAX_PACKAGE)
    manifest = read_json(description["url"], expected_hash=description["sha256"])
    minimum = manifest.get("minimum_installer_protocol")
    if isinstance(minimum, int) and minimum > INSTALLER_PROTOCOL:
        raise SetupError("新しい導入アプリが必要です。公式配布ページから取得して開き直してください。", "installer_outdated")
    if (manifest.get("format") != 1 or type(minimum) is not int or minimum not in {1, INSTALLER_PROTOCOL} or manifest.get("runtime_protocol") != 1
            or manifest.get("platform") != sys.platform or manifest.get("architecture") != "x64"
            or manifest.get("release_tag") != tag or manifest.get("archive_sha256") != payload["sha256"]
            or manifest.get("archive_bytes") != payload["size"]
            or not re.fullmatch(r"[0-9a-f]{40}", str(manifest.get("source_commit", "")))
            or not isinstance(manifest.get("files"), dict) or not manifest["files"]):
        raise SetupError("この導入アプリに対応する配布情報を確認できませんでした。", "release_invalid")
    revision = hashlib.sha256(json.dumps([release["id"], tag, description, payload], sort_keys=True).encode()).hexdigest()
    return {"revision": revision, "version": tag, "release_id": release["id"], "platform": key,
            "size": payload["size"], "notes": str(release.get("body") or "")[:2000],
            "url": release["html_url"], "manifest": manifest, "payload": payload}


def public_release(release: dict) -> dict:
    return {key: release[key] for key in ("revision", "version", "platform", "size", "notes", "url")}


def download_bundle(release: dict, destination: Path, cancel, progress) -> None:
    """The caller owns destination and removes it on cancellation or failure."""
    destination.mkdir(mode=0o700)
    payload = release["payload"]
    digest = hashlib.sha256()
    received = 0
    try:
        with open_download(payload["url"]) as response, (destination / "payload.zip").open("xb") as stream:
            while True:
                if cancel.is_set():
                    raise Cancelled
                block = response.read(256 * 1024)
                if not block:
                    break
                received += len(block)
                if received > payload["size"]:
                    raise SetupError("取得したファイルのサイズが一致しませんでした。", "bundle_invalid")
                stream.write(block)
                digest.update(block)
                progress(received, payload["size"])
        if cancel.is_set():
            raise Cancelled
        if received != payload["size"] or digest.hexdigest() != payload["sha256"]:
            raise SetupError("配布ファイルを確認できませんでした。もう一度取得してください。", "bundle_invalid")
        (destination / "bundle.json").write_text(json.dumps(release["manifest"]), encoding="utf-8")
    except (OSError, URLError, HTTPException):
        raise SetupError("ダウンロードが中断されました。接続と空き容量を確認して再試行してください。", "download_failed") from None
