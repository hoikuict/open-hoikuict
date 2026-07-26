from fastapi.templating import Jinja2Templates

from time_utils import format_jst_datetime, format_local_datetime


def create_templates(directory: str = "templates") -> Jinja2Templates:
    """Create the shared Jinja environment with explicit datetime filters."""
    templates = Jinja2Templates(directory=directory)
    templates.env.filters["jst_datetime"] = format_jst_datetime
    templates.env.filters["local_datetime"] = format_local_datetime
    return templates
