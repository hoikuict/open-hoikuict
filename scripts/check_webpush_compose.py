"""Check resolved Compose JSON without printing SMTP or authentication secrets."""
from __future__ import annotations

import json
import sys


PUSH_FIELDS = (
    "HOIKUICT_PUSH_TRANSPORT",
    "HOIKUICT_PUBLIC_ORIGIN",
    "HOIKUICT_PUSH_VAPID_PUBLIC_KEY",
    "HOIKUICT_PUSH_VAPID_PRIVATE_KEY",
    "HOIKUICT_PUSH_VAPID_SUBJECT",
)
PRIVATE_KEY_PATH = "/run/secrets/parent-push-vapid.pem"


def check_config(config: dict) -> dict:
    app = config["services"]["app"]
    environment = app["environment"]
    selected = {key: environment[key] for key in PUSH_FIELDS}
    if any(not isinstance(value, str) or not value.strip() for value in selected.values()):
        raise ValueError("Missing Web Push environment values")
    if selected["HOIKUICT_PUSH_TRANSPORT"] != "webpush":
        raise ValueError("Web Push overlay is not enabled")
    if selected["HOIKUICT_PUSH_VAPID_PRIVATE_KEY"] != PRIVATE_KEY_PATH:
        raise ValueError("Unexpected private key mount path")
    for target in ("/data", "/app/storage", "/run/secrets/password-blocklist.txt", PRIVATE_KEY_PATH):
        matches = [volume for volume in app["volumes"] if volume["target"] == target]
        if len(matches) != 1 or matches[0]["type"] != "bind" or not matches[0].get("source"):
            raise ValueError("Required application bind mount is missing or duplicated")
        if target.startswith("/run/secrets/") and matches[0].get("read_only") is not True:
            raise ValueError("Secret bind mounts must be read-only")
    mounts = [v for v in app["volumes"] if v["target"] == PRIVATE_KEY_PATH]
    return {"environment": selected, "vapid_mount": mounts[0]}


def main() -> int:
    try:
        result = check_config(json.load(sys.stdin))
    except (ValueError, KeyError, TypeError):
        print("Web Push configuration check failed. Check the overlay and .env locally.", file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=True, indent=2))
    print("Web Push environment and bind mounts: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
