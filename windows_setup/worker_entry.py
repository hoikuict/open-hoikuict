"""Fixed entry point for the bundled Python runtime (also used by WinSW)."""
from __future__ import annotations

import os
from pathlib import Path
import sys


def main() -> int:
    code = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(code))
    os.chdir(code)
    if len(sys.argv) not in {2, 3}:
        return 2
    from windows_setup.storage import load_secrets
    root = Path(sys.argv[1]).resolve()
    settings = load_secrets(root / "config/settings.bin")
    for key in list(os.environ):
        if key.startswith(("HOIKUICT_", "HOIKU_", "PYTHON")) or key == "FORWARDED_ALLOW_IPS":
            os.environ.pop(key, None)
    os.environ.update(settings["environment"])
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    role = sys.argv[2] if len(sys.argv) == 3 else "service"
    if role == "service":
        from windows_setup.worker import run_service
        run_service(root, settings)
    elif role == "gateway":
        from windows_setup.worker import run_gateway
        run_gateway(settings)
    elif role == "backup":
        from scripts.backup_worker import main as backup_main
        sys.argv = [sys.argv[0]]
        return backup_main()
    elif role == "restore":
        from scripts.restore_worker import run
        run()
    elif role == "app":
        from windows_setup.worker import run_application
        run_application(settings["ports"]["app"])
    elif role == "stop":
        (root / "stop-requested").touch()
    else:
        return 2
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        # Configuration and SMTP errors can include credentials. No raw exception.
        print("Windows server component failed: " + type(error).__name__, file=sys.stderr)
        raise SystemExit(1)
