"""Carry a server-signed arrival draft without writing attendance before confirmation."""
import base64
import hashlib
import hmac
import json
import time
from datetime import datetime

from fastapi import HTTPException

from csrf import _secret_key
from kiosk_security import KIOSK_DEVICE_COOKIE


def _signature(payload: str) -> str:
    return hmac.new(_secret_key(), ("guardian-arrival-v1:" + payload).encode(), hashlib.sha256).hexdigest()


def _device(request) -> str:
    return hashlib.sha256(request.cookies.get(KIOSK_DEVICE_COOKIE, "").encode()).hexdigest()


def issue_arrival_draft(request, child, day, captured_at, revision) -> str:
    data = dict(child=child.id, classroom=child.classroom_id, day=day.isoformat(),
                captured=captured_at.isoformat(), revision=revision, issued=time.time(), device=_device(request))
    payload = base64.urlsafe_b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    return payload + "." + _signature(payload)


def read_arrival_draft(token, request, child, day):
    try:
        if not token or len(token) > 4096:
            raise ValueError
        payload, signature = token.split(".")
        if not hmac.compare_digest(signature, _signature(payload)):
            raise ValueError
        data = json.loads(base64.urlsafe_b64decode(payload))
        if (data["child"] != child.id or data["classroom"] != child.classroom_id
                or data["day"] != day.isoformat() or data["device"] != _device(request)
                or not 0 <= time.time() - data["issued"] <= 600):
            raise ValueError
        captured = datetime.fromisoformat(data["captured"])
        if captured.tzinfo is not None:
            raise ValueError
        return captured, data["revision"]
    except (ValueError, TypeError, KeyError, UnicodeError) as exc:
        raise HTTPException(409, "登園の確認が無効か期限切れです。最初の画面からやり直してください。") from exc
