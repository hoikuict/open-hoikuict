from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import webbrowser

from beta_setup.core import FileLock, Installer, MARKER, SetupError, reject_links, target_path, write_json
from beta_setup.server import SetupServer


def default_home(base: Path) -> Path:
    if (base / MARKER).is_file():
        return base
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData/Local"))) / "OpenHoikuICT/beta"
    return Path.home() / ".local/share/open-hoikuict/beta"


def main() -> int:
    parser = argparse.ArgumentParser(description="OpenHoikuICT local beta setup")
    parser.add_argument("--home", type=Path)
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--apply-server", type=Path)
    parser.add_argument("--request-hash")
    args = parser.parse_args()
    if args.apply_server:
        if not args.request_hash:
            return 2
        from windows_setup.operations import execute_job
        try:
            execute_job(args.apply_server.resolve(), args.request_hash)
            return 0
        except Exception:
            return 1
    frozen = bool(getattr(sys, "frozen", False))
    base = Path(sys.executable).resolve().parent if frozen else Path(__file__).resolve().parent
    home = target_path(str(args.home or default_home(base)))
    session_dir = home.parent / f".{home.name}.launcher"
    reject_links(session_dir)
    session_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    lock = FileLock(session_dir / "session.lock")
    session_file = session_dir / "session.json"
    reject_links(session_file)
    try:
        lock.acquire()
    except SetupError:
        try:
            session = json.loads(session_file.read_text(encoding="utf-8"))
            url = session["url"]
            from urllib.parse import urlsplit
            parsed = urlsplit(url)
            if parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or not parsed.fragment:
                return 1
            if not args.no_browser:
                webbrowser.open(url)
            return 0
        except (OSError, ValueError, KeyError):
            return 1
    manager = Installer((args.bundle or base).resolve(), home, Path(sys.executable) if frozen else None,
                        online=args.bundle is None)
    server = SetupServer(manager)
    try:
        write_json(session_file, {"url": server.url, "pid": os.getpid()}, exclusive=False)
        if not args.no_browser:
            webbrowser.open(server.url)
        server.serve_forever(poll_interval=.25)
    finally:
        manager.close()
        server.server_close()
        session_file.unlink(missing_ok=True)
        lock.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
