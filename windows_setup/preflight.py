"""Read-only connection checks, except an explicitly requested test email/probe."""
from __future__ import annotations

from email.message import EmailMessage
import ipaddress
import json
import os
from pathlib import Path
import shutil
import smtplib
import socket
import ssl
import tempfile
from urllib.parse import urlencode
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from beta_setup.core import SetupError, installation, reject_links
from windows_setup import platform
from windows_setup.model import email, hostname, local_directory, network, normalize_mail, text


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise SetupError("接続先が変更されたため中止しました。", "redirect_rejected")


def cloudflare(path: str, token: str) -> dict:
    request = Request("https://api.cloudflare.com/client/v4/" + path,
                      headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect()).open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError
        result = json.loads(raw)
        if not result.get("success"):
            raise ValueError
        return result
    except Exception:
        raise SetupError("Cloudflareの接続権限を確認できませんでした。対象ドメインのDNS編集・Zone読取権限を確認してください。", "dns_permission_failed") from None


def check_pc(root: Path, values: dict) -> dict:
    previous = installation(root)
    if not previous:
        raise SetupError("このPCへの導入を先に完了してください。", "not_installed")
    text(values, "facility", limit=100)
    adapter = text(values, "adapter")
    matching = [item for item in platform.network_adapters() if item["id"] == adapter and item["private"]]
    if not matching:
        raise SetupError("園内ネットワークをプライベートに設定してから再確認してください。", "network_public")
    if shutil.disk_usage(root).free < 2 * 1024**3:
        raise SetupError("このPCの空き容量が不足しています。2 GB以上を確保してください。", "space_insufficient")
    return {"message": "導入済み環境・ネットワーク・空き容量を確認しました。", "adapters": matching}


def check_network_address(values: dict) -> None:
    configured = network(values)
    if values.get("ipReserved") is not True:
        raise SetupError("ルーターのIP予約を確認してください。", "network_unconfirmed")
    matches = [item for item in platform.network_adapters()
               if item["id"] == configured["adapter"] and item["ip"] == configured["ip"] and item["private"]]
    if not matches:
        raise SetupError("選択したネットワークに、このIPアドレスが設定されていません。", "ip_mismatch")


def check_name_resolution(values: dict) -> None:
    configured = network(values)
    if values.get("dnsReady") is not True:
        raise SetupError("園内DNSの設定を確認してください。", "network_unconfirmed")
    internal = values.get("tls") == "internal"
    host = hostname(text(values, "localHostname" if internal else "hostname"), internal=internal)
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(host, 443, family=socket.AF_INET, type=socket.SOCK_STREAM)}
    except OSError:
        raise SetupError("園内DNSからホスト名を確認できませんでした。", "dns_unresolved") from None
    if addresses != {configured["ip"]}:
        raise SetupError("園内DNSの接続先が、このPCのIPアドレスと一致しません。", "dns_mismatch")


def check_certificate_preparation(values: dict) -> None:
    mode = text(values, "tls")
    if mode not in {"domain", "internal"}:
        raise SetupError("暗号化の方式を選んでください。", "tls_invalid")
    internal = mode == "internal"
    host = hostname(text(values, "localHostname" if internal else "hostname"), internal=internal)
    if not internal:
        token = text(values, "dnsToken", limit=2048)
        cloudflare("user/tokens/verify", token)
        labels = host.split(".")
        found = False
        for offset in range(len(labels) - 1):
            zone = ".".join(labels[offset:])
            result = cloudflare("zones?" + urlencode({"name": zone, "status": "active"}), token)
            if any(item.get("name") == zone for item in result.get("result", [])):
                found = True
                break
        if not found:
            raise SetupError("このホスト名のドメインを管理する権限を確認できませんでした。", "dns_zone_missing")


def check_dns(values: dict) -> dict:
    check_network_address(values)
    check_name_resolution(values)
    check_certificate_preparation(values)
    return {"message": "園内DNSと証明書設定の事前確認ができました。証明書の発行は適用時に行います。"}


def inspect_connection(values: dict) -> dict:
    """Return independent readiness results; this never issues a certificate."""
    results = {}
    for key, check in (("ip", check_network_address), ("dns", check_name_resolution),
                       ("tls", check_certificate_preparation)):
        try:
            if key == "tls" and values.get("tls") == "internal" and values.get("trustPlan") is not True:
                raise SetupError("各端末に証明書を登録する担当者を確認してください。", "trust_unconfirmed")
            check(values)
            results[key] = {"passed": True}
        except SetupError as error:
            results[key] = {"passed": False, "message": str(error), "code": error.code}
    complete = all(item["passed"] for item in results.values())
    return {"complete": complete, "results": results,
            "message": "接続の準備を確認しました。実際のHTTPS接続は適用後に確認します。" if complete
            else "要確認の項目があります。表示された作業へ戻って確認してください。"}


def check_mail(values: dict) -> dict:
    settings = normalize_mail(values)
    message = EmailMessage()
    message["From"] = settings["mailFrom"]
    message["To"] = settings["testRecipient"]
    message["Subject"] = "オープン保育ICT：導入時の確認メール"
    message.set_content("導入アプリからの確認メールです。画面に戻り、受信できたことを確認してください。\n")
    try:
        with smtplib.SMTP(settings["smtpHost"], int(settings["smtpPort"]), timeout=20) as smtp:
            smtp.starttls(context=ssl.create_default_context())
            if settings["smtpUser"]:
                smtp.login(settings["smtpUser"], settings["smtpPassword"])
            smtp.send_message(message)
    except smtplib.SMTPAuthenticationError:
        raise SetupError("メールの認証が認められませんでした。送信元と接続用パスワードを確認してください。", "smtp_auth_failed") from None
    except smtplib.SMTPRecipientsRefused:
        raise SetupError("確認メールの宛先が受け付けられませんでした。送信先を確認してください。", "smtp_recipient_failed") from None
    except (OSError, smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected):
        raise SetupError("メールサーバーへ接続できませんでした。接続先・ポートとネットワークを確認してください。", "smtp_connection_failed") from None
    except Exception:
        raise SetupError("確認メールを送信できませんでした。サーバー名・ポート・認証情報を確認してください。", "smtp_failed") from None
    return {"message": "確認メールを送信しました。指定した宛先で受信を確認してください。"}


def check_backup(root: Path, values: dict) -> dict:
    destination = Path(local_directory(text(values, "backupPath", limit=1024)))
    if destination == root or destination.is_relative_to(root) or root.is_relative_to(destination):
        raise SetupError("バックアップ先をアプリの保存場所から分離してください。", "backup_overlaps")
    reject_links(destination)
    if os.name == "nt":
        import ctypes
        kind = ctypes.windll.kernel32.GetDriveTypeW(str(destination.anchor))
        if kind not in {2, 3}:
            raise SetupError("サービスが利用できるローカルドライブを指定してください。共有・割当ドライブは未対応です。", "backup_drive_unsupported")
    try:
        destination.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(destination).free < 2 * 1024**3:
            raise SetupError("バックアップ先に2 GB以上の空き容量を確保してください。", "space_insufficient")
        with tempfile.TemporaryFile(dir=destination) as stream:
            stream.write(b"OpenHoikuICT setup write check")
            stream.flush()
            os.fsync(stream.fileno())
    except OSError:
        raise SetupError("バックアップ先に書き込めません。保存場所と権限を確認してください。", "backup_unwritable") from None
    return {"message": "保存先と空き容量を確認しました。サービスの保存権限は適用時にも確認します。"}


def check_tunnel(values: dict, lan: dict) -> dict:
    from windows_setup.model import normalize_public
    settings = normalize_public(values, lan)
    import base64
    try:
        decoded = json.loads(base64.b64decode(settings["tunnelToken"], validate=True))
        if not isinstance(decoded, dict) or not all(isinstance(decoded.get(key), str) and decoded[key] for key in ("a", "t", "s")):
            raise ValueError
        import uuid
        uuid.UUID(decoded["t"])
    except (ValueError, TypeError):
        raise SetupError("Cloudflare Tunnelの接続用トークン形式を確認してください。", "tunnel_invalid") from None
    return {"message": "トークンの形式を確認しました。認証と公開URLは開始時に検査します。"}


def external_health(host: str, instance: str) -> bool:
    request = Request("https://" + hostname(host) + "/healthz")
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=15) as response:
            return response.status == 200 and response.headers.get("X-HoikuICT-Instance") == instance
    except Exception:
        return False


def lan_https_health(lan: dict, root: Path, instance: str) -> bool:
    from urllib.request import HTTPSHandler
    from windows_setup.model import lan_hostname
    context = ssl.create_default_context()
    if lan["tls"] == "internal":
        certificate = root / "tls/pki/authorities/local/root.crt"
        if not certificate.is_file():
            return False
        context.load_verify_locations(cafile=str(certificate))
    request = Request("https://" + lan_hostname(lan) + "/healthz")
    try:
        with build_opener(ProxyHandler({}), NoRedirect(), HTTPSHandler(context=context)).open(request, timeout=5) as response:
            return response.status == 200 and response.headers.get("X-HoikuICT-Instance") == instance
    except Exception:
        return False
