"""Atomic replacement that tolerates brief Windows reader sharing locks."""
from __future__ import annotations

import os
import time


def replace_file(source, destination) -> None:
    # Windows readers can temporarily prevent delete/rename sharing. Keep the
    # old complete file in place and bound the wait; actual ACL errors still
    # propagate instead of silently dropping a state/heartbeat update.
    deadline = time.monotonic() + 2
    while True:
        try:
            os.replace(source, destination)
            return
        except PermissionError as error:
            if os.name != "nt" or getattr(error, "winerror", None) not in {5, 32, 33} or time.monotonic() >= deadline:
                raise
            time.sleep(.02)
