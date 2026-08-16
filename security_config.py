import os
from importlib.util import find_spec
from urllib.parse import urlsplit

from starlette.websockets import WebSocket


def deployment_environment() -> str:
    return (os.getenv("HOIKUICT_ENV") or "production").strip().lower()


def is_production() -> bool:
    return deployment_environment() == "production"


def staff_auth_mode() -> str:
    raw = (os.getenv("HOIKUICT_STAFF_AUTH_MODE") or "").strip().lower()
    if not raw:
        if not is_production() and os.getenv("HOIKUICT_ENABLE_MOCK_AUTH") == "1":
            return "mock"
        return "disabled"
    if raw not in {"mock", "local_password", "disabled"}:
        raise RuntimeError(
            "HOIKUICT_STAFF_AUTH_MODE は mock / local_password / disabled のいずれかです"
        )
    return raw


def parent_push_transport() -> str:
    default = "disabled" if is_production() else "capture"
    return (os.getenv("HOIKUICT_PUSH_TRANSPORT") or default).strip().lower()


def parent_push_vapid_public_key() -> str:
    return (os.getenv("HOIKUICT_PUSH_VAPID_PUBLIC_KEY") or "").strip()


def parent_push_vapid_private_key() -> str:
    return (os.getenv("HOIKUICT_PUSH_VAPID_PRIVATE_KEY") or "").strip()


def parent_push_vapid_subject() -> str:
    return (os.getenv("HOIKUICT_PUSH_VAPID_SUBJECT") or "").strip()


def public_origin() -> str:
    return (os.getenv("HOIKUICT_PUBLIC_ORIGIN") or "").strip().rstrip("/")


def _boolean_setting(name: str, *, production_default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return production_default if is_production() else False
    return raw == "1"


def secure_cookie_enabled() -> bool:
    return _boolean_setting("HOIKUICT_COOKIE_SECURE", production_default=True)


def csrf_enforced() -> bool:
    return _boolean_setting("HOIKUICT_CSRF_ENFORCE", production_default=True)


def allowed_origins() -> set[str]:
    raw = os.getenv("HOIKUICT_ALLOWED_ORIGINS", "")
    return {item.strip().rstrip("/") for item in raw.split(",") if item.strip()}


def websocket_origin_allowed(websocket: WebSocket) -> bool:
    origin = (websocket.headers.get("origin") or "").strip().rstrip("/")
    configured = allowed_origins()
    if configured:
        return origin in configured
    if not origin:
        return not is_production()
    parsed = urlsplit(origin)
    return bool(parsed.scheme in {"http", "https"} and parsed.netloc == websocket.headers.get("host"))


def kiosk_access_mode() -> str:
    return (os.getenv("HOIKUICT_KIOSK_ACCESS_MODE") or "disabled").strip().lower()


def websocket_runtime_available() -> bool:
    return find_spec("websockets") is not None or find_spec("wsproto") is not None


def validate_runtime_security() -> None:
    environment = deployment_environment()
    if environment not in {"development", "production", "test"}:
        raise RuntimeError("HOIKUICT_ENV は development / production / test のいずれかです")
    if not websocket_runtime_available():
        raise RuntimeError(
            "WebSocketドライバーがありません。プロジェクトの仮想環境で "
            "pip install -r requirements.txt を実行してください"
        )
    mode = kiosk_access_mode()
    if mode not in {"disabled", "token", "open"}:
        raise RuntimeError("HOIKUICT_KIOSK_ACCESS_MODE が不正です")
    if mode == "token" and not os.getenv("HOIKUICT_KIOSK_TOKEN"):
        raise RuntimeError("tokenモードでは HOIKUICT_KIOSK_TOKEN が必要です")
    auth_mode = staff_auth_mode()
    if auth_mode == "local_password":
        throttle_key = os.getenv("HOIKUICT_LOGIN_THROTTLE_HMAC_KEY", "")
        if len(throttle_key.encode("utf-8")) < 32:
            raise RuntimeError(
                "local_password認証には32バイト以上の "
                "HOIKUICT_LOGIN_THROTTLE_HMAC_KEY が必要です"
            )
    push_transport = parent_push_transport()
    if push_transport not in {"disabled", "capture", "webpush"}:
        raise RuntimeError("HOIKUICT_PUSH_TRANSPORT は disabled / capture / webpush のいずれかです")
    if not is_production():
        if push_transport == "webpush":
            _validate_development_webpush_configuration()
        return

    errors: list[str] = []
    if os.getenv("HOIKUICT_ENABLE_MOCK_AUTH") == "1":
        errors.append("モック認証を無効にしてください")
    if os.getenv("HOIKUICT_ENABLE_MOCK_ROLE_OVERRIDE") == "1":
        errors.append("モックrole上書きを無効にしてください")
    if not secure_cookie_enabled():
        errors.append("HOIKUICT_COOKIE_SECURE=1 が必要です")
    if not csrf_enforced():
        errors.append("HOIKUICT_CSRF_ENFORCE=1 が必要です")
    if len(os.getenv("HOIKUICT_SECRET_KEY", "")) < 32:
        errors.append("32文字以上の HOIKUICT_SECRET_KEY が必要です")
    if auth_mode != "local_password":
        errors.append("HOIKUICT_STAFF_AUTH_MODE=local_password が必要です")
    blocklist_path = os.getenv("HOIKUICT_PASSWORD_BLOCKLIST_PATH", "").strip()
    if not blocklist_path or not os.path.isfile(blocklist_path):
        errors.append("読取可能な HOIKUICT_PASSWORD_BLOCKLIST_PATH が必要です")
    if mode == "open":
        errors.append("productionではguardian openモードを使用できません")
    if push_transport != "disabled":
        errors.append("productionでは保護者プッシュ通知transportを有効化できません")
    if errors:
        raise RuntimeError("productionセキュリティ設定が不正です: " + "; ".join(errors))


def _validate_development_webpush_configuration() -> None:
    required = {
        "HOIKUICT_PUSH_VAPID_PUBLIC_KEY": parent_push_vapid_public_key(),
        "HOIKUICT_PUSH_VAPID_PRIVATE_KEY": parent_push_vapid_private_key(),
        "HOIKUICT_PUSH_VAPID_SUBJECT": parent_push_vapid_subject(),
        "HOIKUICT_PUBLIC_ORIGIN": public_origin(),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise RuntimeError(
            "developmentのwebpushには次の設定が必要です: " + ", ".join(missing)
        )

    subject = urlsplit(parent_push_vapid_subject())
    if subject.scheme not in {"mailto", "https"}:
        raise RuntimeError("HOIKUICT_PUSH_VAPID_SUBJECT は mailto: または https:// で指定してください")

    origin = urlsplit(public_origin())
    is_local_http = origin.scheme == "http" and origin.hostname in {
        "localhost",
        "127.0.0.1",
        "::1",
    }
    if (
        not origin.netloc
        or (origin.scheme != "https" and not is_local_http)
        or origin.path not in {"", "/"}
        or origin.query
        or origin.fragment
    ):
        raise RuntimeError(
            "HOIKUICT_PUBLIC_ORIGIN はHTTPS origin（localhostのみHTTP可）で指定してください"
        )
