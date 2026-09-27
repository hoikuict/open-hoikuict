from fastapi.templating import Jinja2Templates
from hashlib import sha256
from pathlib import Path

from time_utils import format_jst_datetime, format_local_datetime
from security_config import is_public_demo, parent_auth_mode

_STATIC_ROOT = Path(__file__).resolve().parent / "static"


def static_asset_url(asset: str) -> str:
    """Change the cache key whenever an asset changes, including during development."""
    path = (_STATIC_ROOT / asset).resolve()
    if not path.is_relative_to(_STATIC_ROOT.resolve()):
        raise ValueError("Asset must be inside the static directory")
    version = sha256(path.read_bytes()).hexdigest()[:16]
    return f"/static/{asset}?v={version}"


def create_templates(directory: str = "templates") -> Jinja2Templates:
    """Create the shared Jinja environment with explicit datetime filters."""
    templates = Jinja2Templates(directory=directory)
    templates.env.filters["jst_datetime"] = format_jst_datetime
    templates.env.filters["local_datetime"] = format_local_datetime
    templates.env.globals["parent_enrollment_enabled"] = lambda: parent_auth_mode() == "local_password"
    templates.env.globals["is_public_demo"] = is_public_demo
    templates.env.globals["static_asset_url"] = static_asset_url
    return templates
