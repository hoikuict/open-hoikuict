from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import secrets
import shutil
import socket
import stat
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
import zipfile


FORMAT = 1
MARKER = "installation.json"
CONFIG = ".env.beta.local"


class SetupError(Exception):
    def __init__(self, message: str, code: str = "setup_error"):
        super().__init__(message)
        self.code = code


class Cancelled(Exception):
    pass


def write_json(path: Path, value: dict, *, exclusive: bool = True) -> None:
    with path.open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    path.chmod(0o600)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def reject_links(path: Path) -> None:
    for item in [path, *path.parents]:
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise SetupError("リンクやジャンクションを含まない保存場所を選んでください。", "path_link")


def target_path(value: str) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute() or ".." in path.parts:
        raise SetupError("保存場所を絶対パスで指定してください。", "path_invalid")
    reject_links(path)
    path = path.resolve()
    if path == Path(path.anchor) or len(path.parts) < 3:
        raise SetupError("専用の新しいフォルダーを指定してください。", "path_invalid")
    if os.name == "nt" and (str(path).startswith("\\\\") or path.is_reserved()):
        raise SetupError("PC内の通常のフォルダーを指定してください。", "path_invalid")
    return path


def normalize(values: dict, *, identity: bool = True) -> dict:
    if not isinstance(values, dict):
        raise SetupError("入力の形式を確認してください。")
    result = {}
    keys = ("name", "email", "login", "reason", "actor", "approver", "path", "port")
    for key in keys:
        value = values.get(key, "")
        if not isinstance(value, str) or len(value) > (1024 if key == "path" else 300):
            raise SetupError("入力が長すぎるか、形式が不正です。", "invalid_input")
        result[key] = value.strip()
    result["path"] = str(target_path(result["path"]))
    if not result["port"].isascii() or not result["port"].isdigit() or not 1024 <= int(result["port"]) <= 65535:
        raise SetupError("接続ポートは1024〜65535の整数にしてください。", "port_invalid")
    if not identity:
        return result
    for key in ("password", "confirm"):
        value = values.get(key, "")
        if not isinstance(value, str) or len(value) > 128:
            raise SetupError("パスワードは128文字以内にしてください。", "password_policy")
        result[key] = unicodedata.normalize("NFC", value)
    if not result["name"] or len(result["name"]) > 100:
        raise SetupError("管理者の名前を100文字以内で入力してください。", "invalid_identity")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result["email"]) or len(result["email"]) > 255:
        raise SetupError("メールアドレスを確認してください。", "invalid_identity")
    result["login"] = result["login"] or result["email"]
    result["actor"] = result["actor"] or result["name"]
    result["approver"] = result["approver"] or result["name"]
    result["reason"] = result["reason"] or "このPCでのβ版試用"
    if len(result["login"]) > 255 or any(unicodedata.category(c).startswith("C") for k in keys[:-2] for c in result[k]):
        raise SetupError("名前・ログインID・導入記録の入力を確認してください。", "invalid_identity")
    if len(result["password"]) < 8 or result["password"] != result["confirm"]:
        raise SetupError("パスワードを8文字以上にし、確認欄にも同じ内容を入力してください。", "password_policy")
    return result


def clean_environment() -> dict:
    return {k: v for k, v in os.environ.items()
            if not k.upper().startswith(("HOIKUICT_", "HOIKU_", "PYTHON", "UVICORN_"))
            and k.upper() not in {"FORWARDED_ALLOW_IPS", "VIRTUAL_ENV"}}


def make_config(path: Path, port: int) -> None:
    settings = {
        "HOIKUICT_ENV": "development", "HOIKUICT_ENABLE_MOCK_AUTH": "0",
        "HOIKUICT_STAFF_AUTH_MODE": "local_password", "HOIKUICT_PARENT_AUTH_MODE": "local_password",
        "HOIKUICT_SECRET_KEY": secrets.token_urlsafe(32),
        "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": secrets.token_urlsafe(32),
        "HOIKUICT_DATABASE_URL": "sqlite:///./hoikuict-beta-auth.db",
        "HOIKUICT_CSRF_ENFORCE": "1", "HOIKUICT_COOKIE_SECURE": "0",
        "HOIKUICT_KIOSK_ACCESS_MODE": "disabled", "HOIKUICT_PUSH_TRANSPORT": "disabled",
        "HOIKUICT_PARENT_MAIL_TRANSPORT": "capture",
        "HOIKUICT_PARENT_REGISTRATION_BASE_URL": f"http://127.0.0.1:{port}",
    }
    with path.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(f"{k}={v}" for k, v in settings.items()) + "\n")
    path.chmod(0o600)
    # main.load_dotenv() must stop here instead of finding an ancestor's .env.
    with (path.parent / ".env").open("x", encoding="utf-8") as stream:
        stream.write("# Settings are loaded explicitly from .env.beta.local.\n")


class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.stream = None

    def acquire(self) -> None:
        reject_links(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.stream = self.path.open("a+b")
        self.path.chmod(0o600)
        try:
            # Reading a locked byte itself fails on Windows; inspect its size.
            if os.fstat(self.stream.fileno()).st_size == 0:
                self.stream.write(b"0")
                self.stream.flush()
            self.stream.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.stream.close()
            self.stream = None
            raise SetupError("同じ環境で別の導入アプリが動いています。先に開いた画面を使ってください。", "busy") from None

    def close(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None


def python_at(root: Path) -> Path:
    return root / "runtime" / ("python.exe" if os.name == "nt" else "bin/python3")


def child(root: Path, mode: str) -> subprocess.Popen:
    return subprocess.Popen(
        [str(python_at(root)), "-I", "-B", str(root / "app" / "_beta_runtime.py"), mode],
        cwd=root / "app", env=clean_environment(), stdin=subprocess.PIPE,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


class Application:
    def __init__(self):
        self.process = None
        self.lock = None
        self.root = None

    def start(self, root: Path, port: int) -> None:
        if self.process and self.process.poll() is None:
            if root != self.root:
                raise SetupError("起動中のアプリを先に停止してください。", "busy")
            return
        if self.process is not None:
            self.stop()
        self.lock = FileLock(root / ".application.lock")
        self.lock.acquire()
        self.root = root
        try:
            self.process = child(root, "run")
            self.process.stdin.write((json.dumps({"port": port}) + "\n").encode())
            self.process.stdin.flush()
            replies = queue.Queue()
            threading.Thread(target=lambda: replies.put(self.process.stdout.readline(4096)), daemon=True).start()
            try:
                result = json.loads(replies.get(timeout=100))
            except (queue.Empty, ValueError):
                raise SetupError("アプリの起動を確認できませんでした。", "startup_failed") from None
            if not result.get("ready"):
                raise SetupError("アプリを起動できません。ポートの使用状況と保存先を確認してください。", "startup_failed")
        except Exception:
            self.stop()
            raise

    def stop(self) -> None:
        proc = self.process
        try:
            if proc and proc.poll() is None:
                try:
                    proc.stdin.write(b"STOP\n")
                    proc.stdin.flush()
                    proc.wait(timeout=20)
                except (OSError, subprocess.TimeoutExpired):
                    proc.terminate()
                    proc.wait(timeout=10)
        finally:
            if proc:
                for stream in (proc.stdin, proc.stdout):
                    if stream:
                        stream.close()
            self.process = None
            if self.lock:
                self.lock.close()
            self.lock = None

    @property
    def running(self) -> bool:
        return self.process is not None and self.process.poll() is None


def installation(root: Path) -> dict | None:
    reject_links(root)
    if not root.exists():
        return None
    marker = root / MARKER
    if not marker.is_file() or marker.stat().st_size > 8192:
        raise SetupError("保存先に既存のファイルがあります。新しい空の保存先を選んでください。", "existing_files")
    reject_links(marker)
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
        if data.get("format") != FORMAT or data.get("state") != "ready":
            raise ValueError
        if not 1024 <= int(data["port"]) <= 65535:
            raise ValueError
        for relative in ("app/.env.beta.local", "app/hoikuict-beta-auth.db", "app/_beta_runtime.py"):
            reject_links(root / relative)
            if not (root / relative).is_file():
                raise ValueError
        reject_links(python_at(root))
        if not python_at(root).is_file():
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise SetupError("導入情報が不完全です。この場所を上書きせず、保守担当者へ確認してください。", "invalid_installation") from None
    return data


def safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return (not path.is_absolute() and ".." not in path.parts and "\\" not in name
            and ":" not in name and path.parts and path.parts[0] in {"runtime", "app"})


def extract_bundle(bundle: Path, destination: Path, cancel: threading.Event) -> dict:
    manifest = json.loads((bundle / "bundle.json").read_text(encoding="utf-8"))
    archive = bundle / "payload.zip"
    if manifest.get("format") != FORMAT or manifest.get("platform") != sys.platform or sha256(archive) != manifest["archive_sha256"]:
        raise SetupError("配布ファイルの確認に失敗しました。元の配布物を展開し直してください。", "bundle_invalid")
    expected = manifest["files"]
    with zipfile.ZipFile(archive) as package:
        members = package.infolist()
        names = [item.filename for item in members]
        if len(set(names)) != len(names) or set(names) != set(expected):
            raise SetupError("配布ファイルの一覧が一致しません。", "bundle_invalid")
        if shutil.disk_usage(destination.parent).free < sum(m.file_size for m in members) + 128 * 1024 * 1024:
            raise SetupError("保存先の空き容量が不足しています。", "disk_full")
        for item in members:
            if cancel.is_set():
                raise Cancelled
            if not safe_member(item.filename) or stat.S_ISLNK(item.external_attr >> 16):
                raise SetupError("配布ファイルのパスが不正です。", "bundle_invalid")
            path = destination.joinpath(*PurePosixPath(item.filename).parts)
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            with package.open(item) as source, path.open("xb") as target:
                shutil.copyfileobj(source, target)
            if sha256(path) != expected[item.filename]:
                raise SetupError("配布ファイルが破損しています。", "bundle_invalid")
            path.chmod(0o700 if (item.external_attr >> 16) & 0o111 else 0o600)
    return manifest


class Installer:
    def __init__(self, bundle: Path, home: Path, launcher: Path | None = None, *, online: bool = False):
        self.bundle = bundle
        self.home = home
        self.launcher = launcher
        self.online = online
        self.release = None
        self.guard = threading.RLock()
        self.cancel = threading.Event()
        self.app = Application()
        self.job = {"state": "idle", "progress": 0, "message": ""}
        self.thread = None

    def snapshot(self) -> dict:
        with self.guard:
            return {**self.job, "running": self.app.running, "path": str(self.home)}

    def update(self, **values) -> None:
        with self.guard:
            self.job.update(values)

    def check_release(self) -> dict:
        from beta_setup.releases import latest_release, public_release
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise SetupError("準備中です。完了または中断を待ってください。", "busy")
            if not self.online:
                return {"offline": True}
            self.release = latest_release()
            return public_release(self.release)

    def check_cancel(self) -> None:
        if self.cancel.is_set():
            raise Cancelled

    def preflight(self, values: dict) -> dict:
        v = normalize(values, identity=False)
        root = Path(v["path"])
        if root == self.bundle or self.bundle.is_relative_to(root):
            raise SetupError("配布アプリとは別の新しい保存場所を選んでください。", "path_invalid")
        previous = installation(root)
        if previous:
            return {"existing": True, "port": previous["port"], "login": previous.get("login", "")}
        parent = root.parent
        while not parent.exists():
            parent = parent.parent
        if not parent.is_dir() or not os.access(parent, os.W_OK):
            raise SetupError("保存場所に書き込めません。別の場所を選んでください。", "permission_denied")
        with socket.socket() as sock:
            try:
                sock.bind(("127.0.0.1", int(v["port"])))
            except OSError:
                raise SetupError("この接続ポートは使用中です。別の番号を選んでください。", "port_busy") from None
        if not self.online and not (self.bundle / "bundle.json").is_file():
            raise SetupError("新規導入には元の配布フォルダーから導入アプリを開いてください。", "missing_bundle")
        return {"existing": False, "port": int(v["port"])}

    def begin(self, values: dict) -> None:
        v = normalize(values)
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise SetupError("準備中です。完了または中断を待ってください。", "busy")
            if self.app.running:
                raise SetupError("起動中のアプリを停止してから操作してください。", "busy")
            if self.preflight(v)["existing"]:
                raise SetupError("すでに導入済みです。起動ボタンを使ってください。", "already_installed")
            release = None
            if self.online:
                fresh = self.check_release()
                if not values.get("release_revision") or values["release_revision"] != fresh["revision"]:
                    raise SetupError("配布版が更新されました。導入する版をもう一度確認してください。", "release_changed")
                release = self.release
            self.cancel.clear()
            self.job = {"state": "installing", "progress": 0, "message": "保存先を確認しています"}
            self.thread = threading.Thread(target=self._install, args=(v, release), daemon=True)
            self.thread.start()

    def _install(self, values: dict, release: dict | None = None) -> None:
        root = Path(values["path"])
        stage = root.parent / f".{root.name}.setup-{uuid.uuid4().hex}"
        lock = FileLock(root.parent / f".{root.name}.setup.lock")
        created = False
        committed = False
        try:
            lock.acquire()
            if root.exists():
                raise SetupError("保存先が作成済みです。上書きせず停止しました。", "existing_files")
            stage.mkdir(mode=0o700)
            created = True
            self.check_cancel()
            bundle = self.bundle
            if release:
                from beta_setup.releases import download_bundle
                bundle = stage / ".download"
                self.update(progress=1, message="GitHubからダウンロードしています", version=release["version"])
                download_bundle(release, bundle, self.cancel,
                                lambda received, total: self.update(received=received, total=total))
            self.update(progress=2, message="配布ファイルを確認しています")
            manifest = extract_bundle(bundle, stage, self.cancel)
            if release:
                reject_links(bundle)
                if bundle.resolve().parent != stage.resolve():
                    raise SetupError("準備用フォルダーを確認できませんでした。")
                shutil.rmtree(bundle)
            self.update(progress=3, message="アプリと必要なソフトを準備しています")
            self.check_cancel()
            self.update(progress=4, message="データと設定を用意しています")
            make_config(stage / "app" / CONFIG, int(values["port"]))
            self.check_cancel()
            self.update(progress=5, message="管理者アカウントを作成しています")
            proc = child(stage, "initialize")
            try:
                raw, _ = proc.communicate((json.dumps(values) + "\n").encode("utf-8"), timeout=150)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(timeout=10)
                raise SetupError("管理者の作成が完了しませんでした。", "initialize_failed") from None
            finally:
                values.pop("password", None)
                values.pop("confirm", None)
            try:
                result = json.loads(raw)
            except ValueError:
                result = {}
            if proc.returncode or not result.get("ok"):
                if result.get("code") == "password_policy":
                    raise SetupError(result.get("message", "パスワードを確認してください。"), "password_policy")
                raise SetupError("管理者の作成に失敗しました。変更は確定していません。", "initialize_failed")
            self.check_cancel()
            self.update(progress=6, message="起動を確認しています")
            self.app.start(stage, int(values["port"]))
            self.app.stop()
            self.check_cancel()
            if self.launcher:
                name = "OpenHoikuICT.exe" if os.name == "nt" else "OpenHoikuICT"
                shutil.copyfile(self.launcher, stage / name)
                (stage / name).chmod(0o700)
            write_json(stage / MARKER, {"format": FORMAT, "state": "ready", "port": int(values["port"]),
                                       "login": values["login"], "source_commit": manifest["source_commit"],
                                       "version": manifest.get("release_tag", "同梱版"),
                                       "bundle_sha256": manifest["archive_sha256"], "installed_at": time.time()})
            reject_links(root)
            if root.exists():
                raise SetupError("保存先が作成済みです。上書きせず停止しました。", "existing_files")
            stage.rename(root)
            committed = True
            self.home = root
            self.update(state="complete", progress=7, message="準備ができました", login=values["login"],
                        version=manifest.get("release_tag", "同梱版"), port=int(values["port"]))
        except Cancelled:
            self.update(state="cancelled", message="確定前の準備を中断しました。")
        except SetupError as exc:
            self.update(state="error", code=exc.code, message=str(exc))
        except PermissionError:
            self.update(state="error", code="permission_denied", message="保存場所に書き込めません。権限や別の保存先を確認してください。")
        except Exception:
            self.update(state="error", code="setup_failed", message="準備を完了できませんでした。配布ファイルと保存先を確認してください。")
        finally:
            values.clear()
            if not committed:
                self.app.stop()
            if created and not committed:
                # Only our exact, randomly named staging directory is eligible.
                try:
                    reject_links(stage)
                    if stage.resolve().parent == root.parent.resolve() and stage.name.startswith(f".{root.name}.setup-"):
                        shutil.rmtree(stage)
                except (OSError, SetupError):
                    self.update(cleanup_path=str(stage), message=self.job["message"] + " 作成途中のフォルダーが残ったため、詳細に場所を表示しています。")
            lock.close()

    def launch(self, values: dict) -> dict:
        with self.guard:
            if self.thread and self.thread.is_alive():
                raise SetupError("準備の完了を待ってください。", "busy")
            root = target_path(values.get("path", str(self.home)))
            data = installation(root)
            if data is None:
                raise SetupError("導入先が見つかりません。", "not_installed")
            self.app.start(root, data["port"])
            self.home = root
            self.update(state="complete", progress=7, login=data.get("login", ""), port=data["port"],
                        version=data.get("version", "既存の版"), message="起動しています")
            return {"url": f"http://127.0.0.1:{data['port']}/staff/login"}

    def close(self) -> None:
        self.cancel.set()
        if self.thread:
            self.thread.join(180)
        self.app.stop()
