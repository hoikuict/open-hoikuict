"""Update only unsent authentication links when the server origin changes."""
from contextlib import closing
from pathlib import Path
import re
import sqlite3


def update_pending_links(settings):
    origins = settings.get('mail_origins', [])
    target = settings['environment']['HOIKUICT_PARENT_REGISTRATION_BASE_URL'].rstrip('/')
    old = [value.rstrip('/') for value in origins if value.rstrip('/') != target]
    if not old:
        return 0
    patterns = [re.compile(re.escape(value) + r'(?=/|[\s?#]|$)') for value in old]
    count = 0
    with closing(sqlite3.connect(Path(settings['root']) / 'data/hoikuict.db', timeout=30)) as db, db:
        for table in ('parent_mail_deliveries', 'staff_mail_deliveries'):
            where = "status IN ('pending','processing')"
            if table == 'parent_mail_deliveries':
                where += " AND message_type != 'attendance_confirmation'"
            for identifier, body in db.execute(f'SELECT id,body FROM {table} WHERE {where}').fetchall():
                updated = body
                for pattern in patterns:
                    updated = pattern.sub(lambda _: target, updated)
                if updated != body:
                    db.execute(f'UPDATE {table} SET body=? WHERE id=?', (updated, identifier))
                    count += 1
    return count
