"""Validate browser-provided push destinations before production network I/O."""

import base64
import re
from urllib.parse import urlsplit

from cryptography.hazmat.primitives.asymmetric import ec


def production_push_endpoint_allowed(value: str) -> bool:
    try:
        url = urlsplit(value)
        host = url.hostname or ""
        provider = (
            host in {"fcm.googleapis.com", "updates.push.services.mozilla.com"}
            or host.endswith(".push.apple.com")
            or host.endswith(".notify.windows.com")
        )
        return bool(
            provider
            and url.scheme == "https"
            and url.port in {None, 443}
            and not url.username
            and not url.password
            and not url.fragment
            and (url.path not in {"", "/"} or bool(url.query))
            and "\\" not in value
            and not any(c.isspace() or ord(c) < 32 for c in value)
        )
    except (ValueError, TypeError):
        return False


def validate_production_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    if not production_push_endpoint_allowed(endpoint):
        raise ValueError("この通知サービスの端末登録には対応していません")
    try:

        def decode(value):
            if not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
                raise ValueError("invalid encoding")
            return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

        point = decode(p256dh)
        if len(point) != 65 or point[0] != 4 or len(decode(auth)) != 16:
            raise ValueError("invalid key size")
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), point)
    except (ValueError, TypeError):
        raise ValueError(
            "通知の登録情報を確認できません。端末を登録し直してください"
        ) from None
