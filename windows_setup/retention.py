"""Remove only expired, verified sets belonging to this installation."""
from datetime import datetime, timezone
from pathlib import Path
import re
import shutil
import time

from beta_setup.core import reject_links
from windows_setup.storage import read_json


def prune_backups(settings, *, now=None):
    from restore_control import active_job, exclusive_lock, maintenance, RestoreError
    from scripts.backup_runtime import verify_backup_set
    try:
        with exclusive_lock():
            if maintenance() or active_job():
                return []
            root = Path(settings['lan']['backupPath']).resolve()
            reject_links(root)
            if root.name != 'open-hoikuict-' + settings['instance']:
                return []
            candidates = []
            for folder in root.iterdir():
                match = re.fullmatch(r'open-hoikuict_(\d{8}T\d{6}Z)_[0-9a-f]{12}', folder.name)
                if not match or not folder.is_dir():
                    continue
                reject_links(folder)
                manifest = read_json(folder / 'manifest.json')
                if manifest.get('facility_ref') != settings['instance']:
                    continue
                stamp = datetime.strptime(match[1], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc).timestamp()
                candidates.append((stamp, folder))
            candidates.sort(reverse=True)
            cutoff = (time.time() if now is None else now) - int(settings['lan']['retention']) * 86400
            removed = []
            # Keep at least the two newest valid sets, even if both have expired.
            verified = 0
            for stamp, folder in candidates:
                verify_backup_set(folder)
                verified += 1
                if verified <= 2 or stamp >= cutoff:
                    continue
                for item in folder.rglob('*'):
                    reject_links(item)
                if folder.resolve().parent != root:
                    raise ValueError('backup outside installation')
                shutil.rmtree(folder)
                removed.append(folder.name)
            return removed
    except Exception:
        # Retain all remaining data when verification/locking fails.
        return []
