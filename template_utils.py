from fastapi.templating import Jinja2Templates

from time_utils import format_jst_datetime, format_local_datetime
from security_config import is_public_demo, parent_auth_mode


def create_templates(directory: str = "templates") -> Jinja2Templates:
    """Create the shared Jinja environment with explicit datetime filters."""
    templates = Jinja2Templates(directory=directory)
    templates.env.filters["jst_datetime"] = format_jst_datetime
    templates.env.filters["local_datetime"] = format_local_datetime
    templates.env.globals["parent_enrollment_enabled"] = lambda: parent_auth_mode() == "local_password"
    templates.env.globals["is_public_demo"] = is_public_demo
    return templates
