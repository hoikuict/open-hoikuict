"""Give the documentation stylesheet a new URL whenever its content changes."""

import hashlib
import re

from mkdocs.config.defaults import MkDocsConfig
from mkdocs.exceptions import PluginError
from mkdocs.structure.files import File, Files


def on_files(files: Files, config: MkDocsConfig, **kwargs) -> Files:
    source = files.get_file_from_path("stylesheets/extra.css")
    if source is None:
        raise PluginError("Documentation stylesheet stylesheets/extra.css is missing")

    content = source.content_bytes
    digest = hashlib.sha256(content).hexdigest()[:12]
    versioned_path = f"stylesheets/extra.{digest}.css"
    files.append(File.generated(config, versioned_path, content=content))

    # Also replace the previous build's URL when mkdocs serve reuses the config.
    config.extra_css = [
        versioned_path
        if re.fullmatch(r"stylesheets/extra(?:\.[0-9a-f]{12})?\.css", path)
        else path
        for path in config.extra_css
    ]
    return files
