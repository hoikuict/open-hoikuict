"""Presentation data for the one-time staff code response; no persisted handout."""

import base64
import os

import qrcode
from qrcode.exceptions import DataOverflowError
from qrcode.image.svg import SvgPathFillImage
from sqlmodel import Session

from local_auth import _token_hash
from models import CredentialActionToken, PasswordCredential
from security_config import staff_recovery_base_url
from time_utils import ensure_utc, utc_now


def prepare_staff_code_handout(action: str) -> dict[str, str]:
    """Validate configuration and generate the URL-only QR before issuing a code."""
    destination = {"activate": "/staff/activate", "reset_password": "/staff/reset-password"}[action]
    if not (
        os.getenv("HOIKUICT_STAFF_RECOVERY_BASE_URL")
        or os.getenv("HOIKUICT_PARENT_REGISTRATION_BASE_URL")
    ):
        raise ValueError("案内に使う施設URLが未設定です。運用担当者がURLを設定してから発行してください。")
    try:
        origin = staff_recovery_base_url()
    except RuntimeError:
        raise ValueError("案内に使う施設URLが正しくありません。運用担当者に設定の確認を依頼してください。") from None
    destination_url = origin + destination
    try:
        qr = qrcode.make(destination_url, image_factory=SvgPathFillImage, border=4)
    except DataOverflowError:
        raise ValueError("施設URLが長すぎるためQRコードを作れません。運用担当者に設定の確認を依頼してください。") from None
    return {
        "destination_url": destination_url,
        "login_url": origin + "/staff/login",
        "qr_data_uri": "data:image/svg+xml;base64," + base64.b64encode(qr.to_string()).decode("ascii"),
        "facility_name": (os.getenv("HOIKUICT_FACILITY_NAME") or "").strip() or "open-hoikuict",
    }


def staff_code_handout_details(session: Session, action_code: str) -> dict:
    """Use the exact committed token, never a fresh print-time TTL or latest-token query."""
    token = session.get(CredentialActionToken, _token_hash(action_code))
    if token is None:
        raise RuntimeError("Issued staff code record is missing")
    credential = session.get(PasswordCredential, token.credential_id)
    if credential is None or credential.principal_type != "staff":
        raise RuntimeError("Issued staff credential is missing")
    now = utc_now()
    expired = bool(token.revoked_at or token.consumed_at or ensure_utc(token.expires_at) <= now)
    return {
        "login_id": credential.login_id,
        "issued_at": token.created_at,
        "expires_at": token.expires_at,
        "remaining_ms": 0 if expired else max(0, int((ensure_utc(token.expires_at) - now).total_seconds() * 1000)),
        "code_unavailable": expired,
    }
