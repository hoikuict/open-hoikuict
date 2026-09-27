import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock
import zipfile

from scripts.build_windows_components import acquire


class LockedComponents(unittest.TestCase):
    def test_archive_is_verified_before_executable_is_published(self):
        exe = b'MZ' + b'fictional executable'
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w') as package:
            package.writestr('app/windows_setup/components/caddy.exe', exe)
            package.writestr('../outside.txt', 'never extract')
        archive = data.getvalue()
        entry = dict(sha256=hashlib.sha256(exe).hexdigest(), bytes=len(exe),
                     member='app/windows_setup/components/caddy.exe',
                     archive=dict(url='https://github.com/hoikuict/open-hoikuict/releases/download/v1/test.zip',
                                  sha256=hashlib.sha256(archive).hexdigest(), bytes=len(archive)))
        for corrupt in (True, False):
            with self.subTest(corrupt=corrupt), tempfile.TemporaryDirectory() as directory:
                output = Path(directory)
                opener = MagicMock()
                opener.open.return_value = io.BytesIO(archive)
                record = {**entry, 'archive': {**entry['archive'], 'sha256': '0'*64}} if corrupt else entry
                if corrupt:
                    with self.assertRaises(ValueError):
                        acquire('caddy.exe', record, output, opener)
                    self.assertFalse((output / 'caddy.exe').exists())
                else:
                    result = acquire('caddy.exe', record, output, opener)
                    self.assertEqual(result.read_bytes(), exe)
                    acquire('caddy.exe', record, output, opener)
                    self.assertEqual(opener.open.call_count, 1)
                self.assertEqual(sorted(p.name for p in output.iterdir()), [] if corrupt else ['caddy.exe'])


if __name__ == '__main__':
    unittest.main()
