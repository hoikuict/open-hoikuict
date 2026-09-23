"""Generate structured service configuration from validated settings."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from windows_setup.model import lan_hostname


def service_name(instance: str) -> str:
    import re
    if not re.fullmatch(r"[0-9a-f]{32}", instance):
        raise ValueError("invalid instance")
    return "OpenHoikuICT-" + instance


def ports(instance: str) -> dict:
    # A stable per-instance range; the installer checks exclusive availability.
    first = 20000 + (int(instance[:8], 16) % 1000) * 4
    return {"app": first, "gateway": first + 1, "tunnel": first + 2, "control": first + 3}


def production_environment(lan: dict, root: Path, code: Path, legacy: dict, instance: str,
                           source_commit: str, public: dict | None = None, *, suspended: bool = False) -> dict:
    host = lan_hostname(lan)
    public_host = public["publicHostname"] if public else host
    environment = {
        "HOIKUICT_ENV": "production", "HOIKUICT_ENABLE_MOCK_AUTH": "0",
        "HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE": "0", "HOIKUICT_STAFF_AUTH_MODE": "local_password",
        "HOIKUICT_PARENT_AUTH_MODE": "local_password", "HOIKUICT_CSRF_ENFORCE": "1", "HOIKUICT_COOKIE_SECURE": "1",
        "HOIKUICT_SECRET_KEY": legacy["HOIKUICT_SECRET_KEY"],
        "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY": legacy["HOIKUICT_LOGIN_THROTTLE_HMAC_KEY"],
        "HOIKUICT_DATABASE_URL": "sqlite:///" + (root / "data/hoikuict.db").as_posix(),
        "HOIKU_FACILITY_BUNREI_DB_PATH": str(root / "data/facility.sqlite"),
        "HOIKU_NURSERY_REF": instance,
        "HOIKUICT_STORAGE_ROOT": str(root / "storage"),
        "HOIKUICT_PREVIEW_DIR": str(root / "data/data-transfer-previews"),
        "HOIKUICT_ALLOWED_ORIGINS": ",".join(dict.fromkeys(["https://" + host, "https://" + public_host])),
        "FORWARDED_ALLOW_IPS": "127.0.0.1", "HOIKUICT_KIOSK_ACCESS_MODE": "disabled",
        "HOIKUICT_PUSH_TRANSPORT": "disabled", "HOIKUICT_PARENT_MAIL_TRANSPORT": "smtp",
        "HOIKUICT_PARENT_REGISTRATION_BASE_URL": "https://" + public_host,
        "HOIKUICT_STAFF_RECOVERY_BASE_URL": "https://" + public_host,
        "HOIKUICT_SMTP_HOST": lan["smtpHost"], "HOIKUICT_SMTP_PORT": lan["smtpPort"],
        "HOIKUICT_SMTP_STARTTLS": "1", "HOIKUICT_SMTP_USERNAME": lan["smtpUser"],
        "HOIKUICT_SMTP_PASSWORD": lan["smtpPassword"], "HOIKUICT_PARENT_MAIL_FROM": lan["mailFrom"],
        "HOIKUICT_PASSWORD_BLOCKLIST_PATH": str(code / "app/assets/password-blocklist.txt"),
        "HOIKUICT_BACKUP_CONTROL_DIR": str(root / "data/backup-control"),
        "HOIKUICT_BACKUP_OUTPUT_ROOT": lan["backupPath"],
        "HOIKUICT_BACKUP_GIT_SHA": source_commit,
        "HOIKUICT_BACKUP_APP_IMAGE": "windows:" + source_commit,
        "HOIKUICT_BACKUP_COMPOSE_SHA256": hashlib.sha256(instance.encode()).hexdigest(),
        "HOIKUICT_BACKUP_CLOUDFLARED_IMAGE": "windows-managed",
        "HOIKUICT_RESTORE_ENABLED": "1",
        "HOIKUICT_RESTORE_CONTROL_DIR": str(root / "restore-control"),
        "HOIKUICT_RESTORE_BACKUP_ROOT": lan["backupPath"],
        "HOIKUICT_RESTORE_STAGING_ROOT": str(root / "restore-staging"),
        "HOIKUICT_RESTORE_SIGNING_KEY_FILE": str(root / "config/restore-signing-key"),
        "HOIKUICT_RESTORE_COMPATIBLE_GIT_SHAS": source_commit,
        "HOIKUICT_GATEWAY_APP_PORT": str(ports(instance)["app"]),
        "HOIKUICT_ACTION_MAIL_SUSPENDED": "1" if suspended else "0",
    }
    return environment


def caddy_config(lan: dict, root: Path, instance: str, public: dict | None = None) -> dict:
    host = lan_hostname(lan)
    public_host = public["publicHostname"] if public else host
    endpoints = ports(instance)
    def route(names):
        return {"match": [{"host": names}], "handle": [
            {"handler": "headers", "response": {"set": {"X-HoikuICT-Instance": [instance]}}},
            {"handler": "reverse_proxy", "upstreams": [{"dial": "127.0.0.1:" + str(endpoints["gateway"])}],
             "headers": {"request": {"set": {"X-Forwarded-Proto": ["https"]}}}},
        ], "terminal": True}
    issuer = ({"module": "acme", "email": lan["mailFrom"], "challenges": {
        "http": {"disabled": True}, "tls-alpn": {"disabled": True},
        "dns": {"provider": {"name": "cloudflare", "api_token": "{env.CLOUDFLARE_API_TOKEN}"}}}}
        if lan["tls"] == "domain" else {"module": "internal"})
    return {
        "admin": {"disabled": True},
        "storage": {"module": "file_system", "root": str(root / "tls")},
        "apps": {
            "pki": {"certificate_authorities": {"local": {"install_trust": False}}},
            "tls": {"automation": {"policies": [{"subjects": [host], "issuers": [issuer]}]}},
            "http": {"servers": {
                "lan": {"listen": [lan["ip"] + ":443"], "routes": [route([host])],
                        "tls_connection_policies": [{}], "automatic_https": {"disable_redirects": True}},
                "tunnel": {"listen": ["127.0.0.1:" + str(endpoints["tunnel"])],
                           "routes": [route(list(dict.fromkeys([host, public_host])))],
                           "automatic_https": {"disable": True}},
            }},
        },
        "logging": {"logs": {"default": {"level": "WARN", "writer": {"output": "stderr"}}}},
    }


def service_xml(code: Path, root: Path, instance: str) -> str:
    document = ET.Element("service")
    values = {
        "id": service_name(instance), "name": "OpenHoikuICT " + instance[:8],
        "description": "保育ICTの園内サーバー・HTTPS・バックアップ",
        "executable": str(code / "runtime/python.exe"),
        "arguments": '-I -B "' + str(code / "app/windows_setup/worker_entry.py") + '" "' + str(root) + '"',
        "workingdirectory": str(code / "app"), "startmode": "Automatic",
        "stoptimeout": "45 sec", "logpath": str(root / "logs"),
        "stopexecutable": str(code / "runtime/python.exe"),
        "stoparguments": '-I -B "' + str(code / "app/windows_setup/worker_entry.py") + '" "' + str(root) + '" stop',
    }
    for key, value in values.items():
        ET.SubElement(document, key).text = value
    ET.SubElement(document, "onfailure", action="restart", delay="10 sec")
    ET.SubElement(document, "resetfailure").text = "1 hour"
    ET.SubElement(document, "log", mode="roll-by-size")
    return ET.tostring(document, encoding="unicode")


def configuration_fingerprint(lan: dict) -> str:
    return hashlib.sha256(json.dumps(lan, sort_keys=True, ensure_ascii=True).encode()).hexdigest()
