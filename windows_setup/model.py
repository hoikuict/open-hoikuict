"""Bounded, declarative input. Browser values are never commands or templates."""
from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import Path, PureWindowsPath

from beta_setup.core import SetupError, reject_links

SECRET_FIELDS = frozenset({"dnsToken", "smtpPassword", "tunnelToken"})
LAN_FIELDS = frozenset({
    "facility", "adapter", "ip", "subnet", "ipReserved", "tls", "hostname",
    "localHostname", "dnsToken", "dnsReady", "smtpHost", "smtpPort", "smtpUser",
    "smtpPassword", "mailFrom", "testRecipient", "backupPath", "backupTime",
    "retention", "noSleep",
})
CHECK_FIELDS = {
    "pc": {"facility", "adapter"},
    "dns": {"adapter", "ip", "subnet", "ipReserved", "tls", "hostname", "localHostname", "dnsToken", "dnsReady"},
    "mail": {"smtpHost", "smtpPort", "smtpUser", "smtpPassword", "mailFrom", "testRecipient"},
    "backup": {"backupPath"},
    "tunnel": {"publicHostname", "tunnelToken"},
}
PRIVATE_NETWORKS = tuple(ipaddress.IPv4Network(v) for v in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


def text(values: dict, key: str, *, required: bool = True, limit: int = 255) -> str:
    value = values.get(key, "")
    if not isinstance(value, str) or len(value) > limit or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise SetupError("入力の形式・文字数を確認してください。", "invalid_input")
    value = value if key == "smtpPassword" else value.strip()
    if required and not value:
        raise SetupError("必要な項目を入力してください。", "missing_field")
    return value


def flag(values: dict, key: str) -> bool:
    value = values.get(key, False)
    if type(value) is not bool:
        raise SetupError("確認項目の形式が不正です。", "invalid_input")
    return value


def hostname(value: str, *, internal: bool = False) -> str:
    try:
        host = value.strip().encode("idna").decode("ascii").lower()
    except UnicodeError:
        raise SetupError("ホスト名を確認してください。", "hostname_invalid") from None
    labels = host.split(".")
    if (len(host) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", part) for part in labels
    )):
        raise SetupError("ホスト名には https://・ポート・/ を付けないでください。", "hostname_invalid")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise SetupError("IPアドレスではなくホスト名を指定してください。", "hostname_invalid")
    if internal:
        if not host.endswith(".home.arpa"):
            raise SetupError("園内専用の名前は .home.arpa で終わる名前にしてください。", "hostname_invalid")
    elif host.endswith((".home.arpa", ".local", ".localhost", ".example", ".test", ".invalid")):
        raise SetupError("管理している公開ドメインを指定してください。", "hostname_invalid")
    return host


def email(value: str) -> str:
    if not re.fullmatch(r"[^\s@<>,;\"\\]+@[^\s@<>,;\"\\]+\.[^\s@<>,;\"\\]+", value) or len(value) > 254:
        raise SetupError("メールアドレスの形式を確認してください。", "email_invalid")
    return value


def local_directory(value: str) -> str:
    path = PureWindowsPath(value)
    if (not path.is_absolute() or not re.fullmatch(r"[A-Za-z]:", path.drive)
        or len(path.parts) < 2 or ".." in path.parts
        or any(re.search(r'[<>:"|?*]', part) or part.endswith((" ", ".")) for part in path.parts[1:])
        or any(PureWindowsPath(part).is_reserved() for part in path.parts[1:])):
        raise SetupError("ローカルドライブの専用フォルダーを指定してください。", "path_invalid")
    if len(str(path)) > 180:
        raise SetupError("保存先は階層の浅い短いフォルダー名にしてください。", "path_too_long")
    reject_links(Path(str(path)))
    return str(path)


def network(values: dict) -> dict:
    try:
        address = ipaddress.IPv4Address(text(values, "ip"))
        subnet = ipaddress.IPv4Network(text(values, "subnet"), strict=True)
        if not any(subnet.subnet_of(private) for private in PRIVATE_NETWORKS) or address not in subnet:
            raise ValueError
        if subnet.prefixlen < 16 or subnet.prefixlen > 30 or address in {subnet.network_address, subnet.broadcast_address}:
            raise ValueError
    except ValueError:
        raise SetupError("このPCを含む園内のIPv4範囲（/16〜/30）を指定してください。", "network_invalid") from None
    adapter = text(values, "adapter", limit=12)
    if not adapter.isascii() or not adapter.isdigit() or not 1 <= int(adapter) < 2**31:
        raise SetupError("園内につながるネットワークを選択してください。", "network_invalid")
    return {"adapter": adapter, "ip": str(address), "subnet": str(subnet)}


def normalize_mail(values: dict) -> dict:
    host = text(values, "smtpHost")
    if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
        raise SetupError("メールサーバー名を確認してください。", "smtp_invalid")
    port = text(values, "smtpPort", limit=5)
    if not port.isascii() or not port.isdigit() or not 1 <= int(port) <= 65535:
        raise SetupError("SMTPポートを1〜65535で指定してください。", "smtp_invalid")
    result = {"smtpHost": host, "smtpPort": str(int(port)),
              "smtpUser": text(values, "smtpUser", required=False),
              "smtpPassword": text(values, "smtpPassword", required=False, limit=2048),
              "mailFrom": email(text(values, "mailFrom")),
              "testRecipient": email(text(values, "testRecipient"))}
    if bool(result["smtpUser"]) != bool(result["smtpPassword"]):
        raise SetupError("メール認証を使う場合はIDとパスワードの両方を入力してください。", "smtp_invalid")
    return result


def normalize_lan(values: dict) -> dict:
    if not isinstance(values, dict):
        raise SetupError("設定の形式が不正です。", "invalid_input")
    result = {"facility": text(values, "facility", limit=100), **network(values), **normalize_mail(values)}
    result.update({key: flag(values, key) for key in ("ipReserved", "dnsReady", "noSleep")})
    if not result["ipReserved"] or not result["dnsReady"]:
        raise SetupError("固定IPと園内DNSの設定を確認してください。", "network_unconfirmed")
    result["tls"] = text(values, "tls")
    if result["tls"] not in {"domain", "internal"}:
        raise SetupError("HTTPSの用意方法を選んでください。", "tls_invalid")
    key = "hostname" if result["tls"] == "domain" else "localHostname"
    result[key] = hostname(text(values, key), internal=result["tls"] == "internal")
    result["dnsToken"] = text(values, "dnsToken", required=result["tls"] == "domain", limit=2048) if result["tls"] == "domain" else ""
    result["backupPath"] = local_directory(text(values, "backupPath", limit=1024))
    result["backupTime"] = text(values, "backupTime")
    if not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", result["backupTime"]):
        raise SetupError("バックアップ時刻をHH:MMで指定してください。", "schedule_invalid")
    result["retention"] = text(values, "retention")
    if result["retention"] not in {"14", "30", "90"}:
        raise SetupError("保存期間を選択してください。", "schedule_invalid")
    return result


def normalize_public(values: dict, lan: dict) -> dict:
    host = hostname(text(values, "publicHostname"))
    if lan["tls"] == "domain" and host != lan["hostname"]:
        raise SetupError("園内と同じ園用ホスト名を指定してください。", "hostname_changed")
    token = text(values, "tunnelToken", limit=8192)
    if not re.fullmatch(r"[A-Za-z0-9_+/=-]+", token):
        raise SetupError("Tunnelの接続用トークンを確認してください。", "tunnel_invalid")
    return {"publicHostname": host, "tunnelToken": token}


def public_values(values: dict) -> dict:
    return {key: value for key, value in values.items() if key not in SECRET_FIELDS}


def check_revision(kind: str, values: dict) -> str:
    selected = {key: values.get(key) for key in sorted(CHECK_FIELDS[kind])}
    return hashlib.sha256(json.dumps(selected, sort_keys=True, ensure_ascii=True).encode()).hexdigest()


def lan_hostname(lan: dict) -> str:
    return lan["hostname"] if lan["tls"] == "domain" else lan["localHostname"]
