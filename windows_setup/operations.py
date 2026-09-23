"""Privileged setup actions. Only a fixed schema may cross the UAC boundary."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import time
import zipfile
from urllib.request import ProxyHandler, Request, build_opener

from beta_setup.core import FileLock, SetupError, installation, reject_links, safe_member, sha256
from windows_setup.configuration import caddy_config, ports, production_environment, service_name, service_xml
from windows_setup.migration import migrate
from windows_setup.model import normalize_lan, normalize_public, public_values
from windows_setup import platform
from windows_setup.storage import atomic_json, load_secrets, read_json, save_secrets


def package_manifest(request: dict) -> dict:
    # Re-fetch only the fixed official repository. The low-privilege launcher
    # cannot choose an elevated download URL or fabricate the trusted file list.
    from beta_setup.releases import latest_release
    release = latest_release()
    if release["revision"] != request["release_revision"]:
        raise SetupError("確認後に配布版が変わりました。もう一度確認してください。", "release_changed")
    manifest = release["manifest"]
    if manifest.get("server_protocol") != 1:
        raise SetupError("この配布版はサーバー設定に未対応です。対応する最新版を取得してください。", "server_bundle_required")
    return manifest


def extract_verified_payload(archive: Path, destination: Path, manifest: dict) -> None:
    reject_links(archive)
    if destination.exists() or sha256(archive) != manifest['archive_sha256']:
        raise SetupError('配布ファイルまたはサービスの保存先を確認してください。', 'bundle_invalid')
    # Expand only after UAC into the short, protected service path. Expanding in
    # a user's deep profile/cache directory can exceed Windows MAX_PATH.
    from beta_setup.core import check_bundle_paths
    with zipfile.ZipFile(archive) as package:
        names = package.namelist()
        if len(names) != len(set(names)) or set(names) != set(manifest['files']):
            raise SetupError('配布ファイルの一覧が一致しません。', 'bundle_invalid')
        check_bundle_paths(destination, names)
        if any(not safe_member(name) for name in names):
            raise SetupError('配布ファイルの場所が不正です。', 'bundle_invalid')
        destination.mkdir(parents=True)
        platform.restrict_directory(destination)
        for name in names:
            target = destination.joinpath(*name.split('/'))
            reject_links(target)
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256()
            with package.open(name) as source, target.open('xb') as output:
                for block in iter(lambda: source.read(1024*1024), b''):
                    digest.update(block); output.write(block)
            if digest.hexdigest() != manifest['files'][name]:
                raise SetupError('配布ファイルが変更されています。実行せず停止しました。', 'bundle_invalid')
    lock = read_json(Path(__file__).with_name('components-lock.json'))
    for name in ('winsw.exe', 'caddy.exe', 'cloudflared.exe'):
        if sha256(destination / 'app/windows_setup/components' / name) != lock[name]['sha256']:
            raise SetupError('常駐用プログラムの検証に失敗しました。', 'component_invalid')
    shutil.copyfile(destination / 'app/windows_setup/components/winsw.exe', destination / 'service.exe')


def control(root: Path, token: str, route: str, values: dict | None = None) -> dict:
    state = read_json(root / "state.json")
    port = ports(state["instance"])["control"]
    headers = {"Authorization": "Bearer " + token}
    if values is not None:
        headers["Content-Type"] = "application/json"
    request = Request(f"http://127.0.0.1:{port}" + route, headers=headers,
                      data=json.dumps(values).encode() if values is not None else None)
    try:
        with build_opener(ProxyHandler({})).open(request, timeout=8) as response:
            result = json.loads(response.read(32768))
        if not result.get("ok"):
            raise ValueError
        return result
    except Exception:
        raise SetupError("サーバーとの接続を確認できません。起動状態を確認してください。", "service_unavailable") from None


def wait_healthy(root: Path, token: str, *, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            result = control(root, token, "/status")
            if all(result.get(key) for key in ("running", "gateway", "backup", "restore")):
                return result
        except SetupError:
            pass
        time.sleep(1)
    raise SetupError("サービスの起動を確認できませんでした。", "service_unhealthy")


def ensure_ports_free(lan: dict, instance: str):
    for host, port in [(lan["ip"], 443), *[("127.0.0.1", p) for p in ports(instance).values()]]:
        with socket.socket() as probe:
            if os.name == "nt":
                probe.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            try:
                probe.bind((host, port))
            except OSError:
                raise SetupError("接続ポートを利用できません。既存のサービスを確認してください。", "port_busy") from None


class Operation:
    def __init__(self, request: dict, job: Path):
        self.request, self.job = request, job
        self.instance = request["instance"]
        self.code, self.root = platform.instance_paths(self.instance)
        self.source = Path(request["source"]).resolve()
        self.journal = {"instance": self.instance, "operation": request["operation"], "steps": [], "state": "running"}

    def update(self, message: str, progress: int, **values):
        atomic_json(self.job / "status.json", {"state": "running", "message": message,
                    "progress": progress, **values})
        if (self.job / "cancel").exists():
            raise SetupError("設定を中断しました。", "cancelled")

    def record(self, step: str):
        self.journal["steps"].append(step)
        atomic_json(self.root / "operation.json", self.journal)

    def apply_lan(self):
        lan = normalize_lan(self.request["values"])
        metadata = installation(self.source)
        if not metadata or metadata.get("server"):
            raise SetupError("この環境を新規のLAN設定へ切り替えられません。", "already_configured")
        self.update("配布版と引継ぎ元を確認しています", 0)
        manifest = package_manifest(self.request)
        payload = self.source / ".server-setup" / ("download-" + manifest["archive_sha256"][:16]) / 'payload.zip'
        reject_links(payload)
        ensure_ports_free(lan, self.instance)
        if self.root.exists() or self.code.exists():
            raise SetupError("作成途中の環境があります。状態を確認してから復旧してください。", "target_exists")
        from windows_setup.preflight import check_pc, check_dns
        check_pc(self.source, lan)
        check_dns(lan)
        self.root.mkdir(parents=True)
        platform.restrict_directory(self.root)
        self.record("created_root")
        backup = Path(lan["backupPath"]) / ("open-hoikuict-" + self.instance)
        if backup.exists():
            raise SetupError("バックアップの専用保存先が存在します。上書きしません。", "backup_exists")
        for protected in (self.source, self.code, self.root):
            if backup == protected or backup.is_relative_to(protected) or protected.is_relative_to(backup):
                raise SetupError("バックアップ先がアプリの保存先と重なっています。", "backup_overlaps")
        backup.mkdir(parents=True)
        platform.restrict_directory(backup)
        lan["backupPath"] = str(backup)
        self.record("created_backup")
        self.update("検証したアプリをサービス用の場所に配置しています", 1)
        extract_verified_payload(payload, self.code, manifest)
        self.record("copied_code")
        self.update("データ・添付・認証鍵を引き継いでいます", 2)
        lock = FileLock(self.source / ".application.lock")
        lock.acquire()
        try:
            keys = migrate(self.source, self.root)
            for name in ("config", "logs", "restore-control", "restore-staging", "restore-drills", "tls"):
                (self.root / name).mkdir()
            token = secrets.token_urlsafe(32)
            environment = production_environment(lan, self.root, self.code, keys, self.instance, manifest["source_commit"])
            settings = {"instance": self.instance, "root": str(self.root), "code": str(self.code), "lan": lan,
                        "public": None, "control_token": token, "ports": ports(self.instance),
                        "environment": environment, "source_commit": manifest["source_commit"]}
            (self.root / "config/restore-signing-key").write_bytes(secrets.token_bytes(32))
            save_secrets(self.root / "config/settings.bin", settings)
            atomic_json(self.root / "config/caddy.json", caddy_config(lan, self.root, self.instance))
            state = {"format": 1, "instance": self.instance, "source": str(self.source),
                     "code": str(self.code), "owner_sid": self.request["owner_sid"],
                     "lan": public_values(lan), "lan_confirmed": False, "public": None,
                     "public_confirmed": False, "version": manifest["release_tag"]}
            atomic_json(self.root / "state.json", state)
            schedule = {"schema_version": 1, "enabled": True, "frequency": "daily", "run_time": lan["backupTime"],
                        "weekday": 0, "updated_at_utc": None, "updated_at_jst": None,
                        "updated_by": {"name": "Windows導入アプリ", "id": None}}
            atomic_json(self.root / "data/backup-control/schedule.json", schedule)
            (self.code / "service.xml").write_text(service_xml(self.code, self.root, self.instance), encoding="utf-8")
            self.update("Windowsサービスと保存権限を設定しています", 3)
            # Journal before service installation so a partial install is undone.
            self.record("installing_service")
            platform.install_service(self.code, self.root, self.instance)
            platform.restrict_directory(self.root / "tls", service=service_name(self.instance), writable=True)
            platform.restrict_directory(backup, service=service_name(self.instance), writable=True)
            self.record("installed_service")
            if lan["noSleep"]:
                self.journal["power_before"] = platform.power_settings()
                self.record("changing_power")
                platform.power_settings(prevent_sleep=True)
            self.update("サービスの起動とバックアップを確認しています", 4)
            platform.change_service(self.code, self.instance, "start")
            wait_healthy(self.root, token)
            from windows_setup.preflight import lan_https_health
            deadline = time.monotonic() + 240
            while not lan_https_health(lan, self.root, self.instance):
                if time.monotonic() > deadline:
                    raise SetupError("HTTPS証明書と園内URLの接続を確認できませんでした。", "https_unavailable")
                self.update("HTTPS証明書と園内URLを確認しています", 4)
                time.sleep(2)
            control(self.root, token, "/drill", {})
            deadline = time.monotonic() + 300
            while time.monotonic() < deadline:
                status = control(self.root, token, "/status")
                if status["drill"]["state"] == "complete":
                    break
                if status["drill"]["state"] == "failed":
                    raise SetupError("サービスからバックアップ・隔離復元を確認できませんでした。", "backup_failed")
                self.update("初回バックアップと隔離復元を確認しています", 4)
                time.sleep(1)
            else:
                raise SetupError("初回バックアップが完了しませんでした。", "backup_timeout")
            self.update("園内からの接続を有効にしています", 5)
            self.record("enabling_firewall")
            platform.firewall(lan, self.instance)
            # Marker is the commit point. The old launcher must not start stale
            # trial data after the nursery begins using the copied live data.
            os.replace(self.source / "app/.env.beta.local", self.source / "app/.env.beta.migrated")
            self.record("retired_trial")
            atomic_json(self.source / "installation.json", {**metadata, "server": {"instance": self.instance}})
            save_secrets(self.source / ".server-setup/controller.bin", {"instance": self.instance, "token": token})
            if lan["tls"] == "internal":
                shutil.copyfile(self.root / "tls/pki/authorities/local/root.crt", self.source / ".server-setup/lan-root.crt")
            # An individual operator may inspect non-secret state, but never
            # write service binaries or protected settings.
            platform.powershell("""
              $p=$v.path; $a=Get-Acl -LiteralPath $p
              $r=[Security.AccessControl.FileSystemAccessRule]::new(
                [Security.Principal.SecurityIdentifier]::new($v.sid), 'ReadAndExecute',
                'ContainerInherit,ObjectInherit','None','Allow')
              $a.AddAccessRule($r); Set-Acl -LiteralPath $p -AclObject $a
            """, {"path": str(self.root), "sid": self.request["owner_sid"]})
            # HTTP requests remain gated until all migration metadata is durable.
            # Once ready exists, never return to the stale trial database.
            self.journal["state"] = "complete"
            atomic_json(self.root / "operation.json", self.journal)
            (self.root / 'ready').touch(exist_ok=False)
            atomic_json(self.job / "status.json", {"state": "complete", "progress": 6,
                        "message": "LAN設定を適用しました。別の端末からの接続を確認してください。",
                        "instance": self.instance})
        finally:
            lock.close()

    def change_public(self, *, disable=False):
        state = read_json(self.root / "state.json")
        if state.get("source") != str(self.source) or not state.get("lan_confirmed"):
            raise SetupError("園内の動作確認を先に完了してください。", "lan_unconfirmed")
        previous = load_secrets(self.root / "config/settings.bin")
        public = None if disable else normalize_public(self.request["values"], previous["lan"])
        settings = {**previous, "public": public}
        original_environment = previous["environment"]
        settings["environment"] = production_environment(
            previous["lan"], self.root, self.code, original_environment, self.instance,
            previous["source_commit"], public, suspended=disable)
        origins = list(dict.fromkeys([*previous.get('mail_origins', []),
            previous['environment']['HOIKUICT_PARENT_REGISTRATION_BASE_URL'],
            settings['environment']['HOIKUICT_PARENT_REGISTRATION_BASE_URL']]))
        previous['mail_origins'] = origins
        settings['mail_origins'] = origins
        self.update("現在の公開設定を退避しています", 0)
        save_secrets(self.root / "config/before-public.bin", previous)
        atomic_json(self.root / "config/before-public-state.json", state)
        self.record("public_previous_saved")
        self.update("接続設定を切り替えています", 1)
        platform.change_service(self.code, self.instance, "stop")
        save_secrets(self.root / "config/settings.bin", settings)
        atomic_json(self.root / "config/caddy.json", caddy_config(settings["lan"], self.root, self.instance, public))
        self.record("public_settings_changed")
        platform.change_service(self.code, self.instance, "start")
        wait_healthy(self.root, settings["control_token"])
        if public:
            self.update("公開URLからの接続を確認しています", 2)
            from windows_setup.preflight import external_health
            deadline = time.monotonic() + 120
            while not external_health(public["publicHostname"], self.instance):
                if time.monotonic() > deadline:
                    raise SetupError("公開URLがこのPCへつながりません。Cloudflareの接続先を確認してください。", "public_health_failed")
                self.update("公開URLからの接続を確認しています", 2)
                time.sleep(3)
        state.update(public=public_values(public) if public else None, public_confirmed=False,
                     action_mail_suspended=disable)
        atomic_json(self.root / "state.json", state)
        self.journal["state"] = "complete"
        atomic_json(self.root / "operation.json", self.journal)
        atomic_json(self.job / "status.json", {"state": "complete", "progress": 4,
                    "message": "園外からの利用を停止しました。園内で引き続き使えます。" if disable else "公開接続を開始しました。携帯回線から確認してください。"})

    def rollback(self) -> bool:
        steps = self.journal["steps"]
        failures = []
        def attempt(label, action):
            try:
                action()
            except Exception:
                failures.append(label)
        if self.request["operation"] in {"public", "stop-public"}:
            if "public_previous_saved" in steps:
                previous = load_secrets(self.root / "config/before-public.bin")
                attempt("service_stop", lambda: platform.change_service(self.code, self.instance, "stop"))
                attempt("settings_restore", lambda: save_secrets(self.root / "config/settings.bin", previous))
                attempt("https_restore", lambda: atomic_json(self.root / "config/caddy.json",
                        caddy_config(previous["lan"], self.root, self.instance, previous.get("public"))))
                attempt("state_restore", lambda: atomic_json(self.root / "state.json",
                        read_json(self.root / "config/before-public-state.json")))
                attempt("service_start", lambda: platform.change_service(self.code, self.instance, "start"))
                attempt("health", lambda: wait_healthy(self.root, previous["control_token"]))
        else:
            if "enabling_firewall" in steps:
                attempt("firewall", lambda: platform.firewall({}, self.instance, remove=True))
            if "installing_service" in steps:
                attempt("service_stop", lambda: platform.change_service(self.code, self.instance, "stop"))
                attempt("service_remove", lambda: platform.change_service(self.code, self.instance, "uninstall"))
            if "changing_power" in steps:
                attempt("power", lambda: platform.restore_power(self.journal["power_before"]))
            if "retired_trial" in steps:
                # Never delete either database. Restore the original trial marker
                # only if the LAN change has not reached its commit point.
                attempt("trial_config", lambda: os.replace(self.source / "app/.env.beta.migrated", self.source / "app/.env.beta.local"))
                def marker():
                    previous = read_json(self.source / "installation.json")
                    previous.pop("server", None)
                    atomic_json(self.source / "installation.json", previous)
                attempt("trial_marker", marker)
        self.journal.update(state="blocked" if failures else "rolled_back", recovery_failures=failures)
        if self.root.exists():
            atomic_json(self.root / "operation.json", self.journal)
        return not failures


def execute_job(request_file: Path, digest: str):
    if not platform.is_admin():
        raise SetupError("Windowsの管理者権限が必要です。", "admin_required")
    reject_links(request_file)
    if request_file.name != "request.bin" or sha256(request_file) != digest:
        raise SetupError("確認後に設定依頼が変更されました。", "request_changed")
    request = load_secrets(request_file)
    if request.get("operation") not in {"lan", "public", "stop-public"}:
        raise SetupError("未対応の設定操作です。", "operation_invalid")
    source = Path(request["source"]).resolve()
    expected_parent = source / ".server-setup/jobs"
    if request_file.parent.parent != expected_parent or len(request_file.parent.name) != 32:
        raise SetupError("設定依頼の保存場所が不正です。", "request_invalid")
    if not 0 <= time.time() - request.get("created_at", 0) <= 600:
        raise SetupError("設定依頼の有効期限が切れました。", "request_expired")
    operation = Operation(request, request_file.parent)
    lock = FileLock(source / ".server-setup/operation.lock")
    lock.acquire()
    try:
        if request["operation"] == "lan":
            operation.apply_lan()
        else:
            operation.change_public(disable=request["operation"] == "stop-public")
    except Exception as error:
        # Past the commit point, keep live data and surface the actual state.
        committed = operation.journal.get("state") == "complete"
        recovered = False if committed else operation.rollback()
        atomic_json(request_file.parent / "status.json", {
            "state": "blocked" if not recovered else "cancelled" if getattr(error, "code", "") == "cancelled" else "error",
            "code": getattr(error, "code", "setup_failed"),
            "message": str(error) if isinstance(error, SetupError) else "設定操作を完了できませんでした。",
            "recovered": recovered, "instance": operation.instance,
            "recovery": "既存データを保持して設定を戻しました。" if recovered else "データを保持しています。状態確認と復旧が必要です。",
        })
    finally:
        request_file.unlink(missing_ok=True)
        lock.close()
