"""Low-privilege coordinator used by the authenticated, loopback installer UI."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import sys
import threading
import time

from beta_setup.core import Cancelled, FileLock, SetupError, installation, reject_links, sha256
from windows_setup.configuration import ports
from windows_setup.model import check_revision, lan_hostname, normalize_lan
from windows_setup import platform
from windows_setup.storage import DraftStore, atomic_json, load_secrets, read_json, save_secrets


class ServerManager:
    def __init__(self, installer):
        self.installer = installer
        self.guard = threading.RLock()
        self.checks = {}
        self.job_path = None
        self.job = {"state": "idle"}
        self.thread = None
        self.cancel = threading.Event()
        self._adapters = None
        self.helper = None
        self.recovery_attempted = False
        self.loaded_home = None
        self.operation = None

    def _resume_job(self):
        if self.loaded_home == self.home:
            return
        self.loaded_home = self.home
        active = self.home / '.server-setup/active-job.json'
        if not active.is_file():
            return
        record = read_json(active)
        import re
        if not re.fullmatch(r'[0-9a-f]{32}', record.get('id', '')):
            raise SetupError('設定処理の記録を確認してください。', 'job_invalid')
        self.job_path = active.parent / 'jobs' / record['id']
        self.operation = record.get('operation')
        self.job = {'state': 'running', 'operation': record.get('operation')}

    def _interrupted(self):
        if self.helper:
            return self.helper.poll() is not None
        active = read_json(self.home / '.server-setup/active-job.json')
        if time.time() - active.get('created_at', 0) < 30:
            return False
        lock = FileLock(self.home / '.server-setup/operation.lock')
        try:
            lock.acquire()
        except SetupError as error:
            if error.code == 'busy':
                return False
            raise
        finally:
            lock.close()
        return True

    @property
    def home(self):
        return self.installer.home

    def _private_folder(self):
        folder = self.home / ".server-setup"
        reject_links(folder)
        folder.mkdir(parents=True, exist_ok=True)
        platform.restrict_directory(folder, owner_sid=platform.current_sid())
        return folder

    def state(self):
        previous = installation(self.home)
        if not previous or not previous.get("server"):
            return None
        instance = previous["server"]["instance"]
        _, root = platform.instance_paths(instance)
        result = read_json(root / "state.json")
        if result.get("instance") != instance or result.get("source") != str(self.home):
            raise SetupError("サーバーの導入情報が一致しません。", "server_state_invalid")
        return result

    def status(self):
        with self.guard:
            self._resume_job()
            if self.job_path and (self.job_path / "status.json").is_file():
                self.job = read_json(self.job_path / "status.json")
                if self.job.get("state") == "running" and self._interrupted():
                    self.job = {"state": "blocked", "message": "設定処理が中断しました。データを保持したまま状態確認が必要です。"}
                    atomic_json(self.job_path / 'status.json', self.job)
                if (not self.recovery_attempted and self.job.get("state") in {"error", "cancelled"}
                        and self.job.get("recovered")):
                    self.recovery_attempted = True
                    if not self.state() and not self.installer.app.running:
                        try:
                            previous = installation(self.home)
                            self.installer.app.start(self.home, previous["port"])
                        except Exception:
                            self.job["recovery"] = "試用環境のデータは保持しています。再起動を確認してください。"
                if self.job.get("state") in {"complete", "error", "cancelled", "blocked"}:
                    self.job_path = None
                    if self.helper:
                        self.helper.close()
                        self.helper = None
            state = self.state()
            health = {}
            if state:
                try:
                    health = self._control("/status")
                except SetupError:
                    health = {"running": False}
            return {"state": state, "health": health, "job": {**self.job, 'operation': self.operation},
                    "ports": ports(state['instance']) if state else {}}

    def info(self):
        result = self.status()
        if os.name == "nt" and self._adapters is None:
            try:
                self._adapters = platform.network_adapters()
            except SetupError:
                self._adapters = []
        result.update(adapters=self._adapters or [], draft=DraftStore(self.home).load()
                      if (self.home / ".server-setup/draft.json").exists() else {"flow": "home", "step": 0, "values": {}})
        return result

    def check(self, kind: str, values: dict):
        from windows_setup import preflight
        with self.guard:
            if self.busy:
                raise SetupError("設定処理の完了を待ってください。", "busy")
            proof = "dns" if kind == "connection" else kind
            self.checks.pop(proof, None)
            if kind == "adapters":
                self._adapters = platform.network_adapters()
                self.checks.pop("pc", None)
                self.checks.pop("dns", None)
                return {"adapters": self._adapters, "message": "PCの接続情報を読み直しました。"}
            if kind == "connection":
                result = preflight.inspect_connection(values)
                if result["complete"]:
                    self.checks["dns"] = check_revision("dns", values)
                return result
            functions = {"pc": lambda: preflight.check_pc(self.home, values),
                         "dns": lambda: preflight.check_dns(values),
                         "mail": lambda: preflight.check_mail(values),
                         "backup": lambda: preflight.check_backup(self.home, values)}
            if kind == "tunnel":
                state = self.state()
                if not state or not state.get("lan_confirmed"):
                    raise SetupError("園内の動作確認が必要です。", "lan_unconfirmed")
                result = preflight.check_tunnel(values, state["lan"])
            elif kind in functions:
                result = functions[kind]()
            else:
                raise SetupError("確認対象が不正です。", "check_invalid")
            self.checks[kind] = check_revision(kind, values)
            return result

    @property
    def busy(self):
        return bool((self.thread and self.thread.is_alive()) or self.job_path)

    def draft(self, values: dict):
        if not installation(self.home):
            raise SetupError("導入先を確認してください。", "not_installed")
        self._private_folder()
        DraftStore(self.home).save(values.get("flow"), values.get("step"), values.get("values", {}), values.get("guide"))

    def begin(self, operation: str, values: dict):
        with self.guard, self.installer.guard:
            self.status()
            if self.job.get('state') == 'blocked':
                raise SetupError('中断した設定の状態確認が必要です。データを保持しているため重ねて設定できません。', 'recovery_required')
            if self.busy or self.installer.thread and self.installer.thread.is_alive():
                raise SetupError("処理の完了を待ってください。", "busy")
            if os.name != "nt" or not self.installer.launcher:
                raise SetupError("Windows版の導入アプリから実行してください。", "windows_launcher_required")
            if operation == "lan":
                normalize_lan(values)
                if values.get("mailReceived") is not True:
                    raise SetupError("確認メールの受信を確認してください。", "mail_unconfirmed")
                for kind in ("pc", "dns", "mail", "backup"):
                    if self.checks.get(kind) != check_revision(kind, values):
                        raise SetupError("設定が変更された項目を、もう一度確認してください。", "check_expired")
            elif operation == "public":
                if self.checks.get("tunnel") != check_revision("tunnel", values):
                    raise SetupError("園外接続の準備を確認してください。", "check_expired")
            elif operation != "stop-public":
                raise SetupError("未対応の操作です。", "operation_invalid")
            self.cancel.clear()
            self.operation = operation
            self.recovery_attempted = False
            self.job = {"state": "running", "progress": 0, "message": "設定の準備をしています"}
            self.thread = threading.Thread(target=self._prepare, args=(operation, dict(values)), daemon=True)
            self.thread.start()

    def _prepare(self, operation, values):
        try:
            folder = self._private_folder()
            state = self.state()
            release = None
            if operation == "lan":
                from beta_setup.releases import latest_release, download_bundle
                release = latest_release()
                manifest = release["manifest"]
                if manifest.get("server_protocol") != 1:
                    raise SetupError("サーバー設定に対応した配布版を取得してください。", "server_bundle_required")
                payload = folder / ("download-" + manifest["archive_sha256"][:16])
                if not (payload / 'bundle.json').is_file() or sha256(payload / 'payload.zip') != manifest['archive_sha256']:
                    if payload.exists():
                        # Delete only files created by this download operation.
                        for name in ('payload.zip', 'bundle.json'):
                            reject_links(payload / name)
                            (payload / name).unlink(missing_ok=True)
                        payload.rmdir()
                    self.job.update(message="検証済みのサーバー用プログラムを取得しています", progress=0)
                    download_bundle(release, payload, self.cancel,
                                    lambda received, total: self.job.update(received=received, total=total))
                instance = secrets.token_hex(16)
                current_launcher = Path(self.installer.launcher).resolve()
                installed_launcher = self.home / 'OpenHoikuICT.exe'
                reject_links(installed_launcher)
                if current_launcher != installed_launcher.resolve():
                    staged_launcher = folder / ('launcher-' + secrets.token_hex(8) + '.exe')
                    try:
                        shutil.copyfile(current_launcher, staged_launcher)
                        os.replace(staged_launcher, installed_launcher)
                    finally:
                        staged_launcher.unlink(missing_ok=True)
                self.installer.app.stop()
            else:
                if not state or not state.get("lan_confirmed"):
                    raise SetupError("園内の動作確認を完了してください。", "lan_unconfirmed")
                instance = state["instance"]
            if self.cancel.is_set():
                raise SetupError("設定の準備を中断しました。", "cancelled")
            job = folder / "jobs" / secrets.token_hex(16)
            job.mkdir(parents=True)
            request = {"format": 1, "operation": operation, "source": str(self.home),
                       "instance": instance, "owner_sid": platform.current_sid(),
                       "values": values, "created_at": time.time(),
                       "release_revision": release["revision"] if release else None}
            request_file = job / "request.bin"
            save_secrets(request_file, request)
            atomic_json(job / "status.json", {"state": "running", "progress": 0, "message": "Windowsの管理者許可を待っています"})
            digest = sha256(request_file)
            atomic_json(folder / 'active-job.json', {'id': job.name, 'operation': operation, 'created_at': time.time()})
            self.loaded_home = self.home
            self.job_path = job
            self.helper = platform.elevate(self.installer.launcher, ["--apply-server", str(request_file), "--request-hash", digest])
        except Exception as error:
            if self.job_path:
                failed_job = self.job_path
                (self.job_path / "request.bin").unlink(missing_ok=True)
                self.job_path = None
            else:
                failed_job = None
            self.job = {"state": "cancelled" if isinstance(error, Cancelled) or getattr(error, "code", "") == "cancelled" else "error",
                        "code": getattr(error, "code", "server_prepare_failed"),
                        "message": str(error) if isinstance(error, SetupError) else "設定の準備に失敗しました。入力は保持しています。"}
            if failed_job:
                atomic_json(failed_job / 'status.json', self.job)
            if operation == 'lan' and not self.state() and not self.installer.app.running:
                try:
                    previous = installation(self.home)
                    if previous:
                        self.installer.app.start(self.home, previous['port'])
                except Exception:
                    self.job['recovery'] = '既存データは保持しています。試用アプリの再起動を確認してください。'
        finally:
            values.clear()

    def cancel_job(self):
        self.cancel.set()
        if self.job_path:
            (self.job_path / "cancel").touch()

    def _control(self, path: str, values=None):
        from windows_setup.operations import control
        credentials = load_secrets(self.home / ".server-setup/controller.bin")
        _, root = platform.instance_paths(credentials["instance"])
        return control(root, credentials["token"], path, values)

    def drill(self):
        if self.busy:
            raise SetupError("設定中です。完了してから実行してください。", "busy")
        return self._control("/drill", {})

    def confirm(self, values):
        if self.busy:
            raise SetupError("設定中です。完了してから確認してください。", "busy")
        return self._control("/confirm", values)

    def launch_url(self):
        state = self.state()
        if not state:
            raise SetupError("サーバー設定がありません。", "server_missing")
        health = self._control("/status")
        if not health.get("running"):
            raise SetupError("Windowsサービスの起動を確認してください。", "service_unavailable")
        return {"url": "https://" + lan_hostname(state["lan"]) + "/staff/login"}

    def certificate(self) -> bytes:
        state = self.state()
        if not state or state["lan"]["tls"] != "internal":
            raise SetupError("園内証明書はありません。", "certificate_missing")
        # Only the public certificate is exported by the elevated installer.
        path = self.home / ".server-setup/lan-root.crt"
        reject_links(path)
        if not path.is_file() or path.stat().st_size > 32768:
            raise SetupError("園内証明書を読み取れません。", "certificate_missing")
        return path.read_bytes()
