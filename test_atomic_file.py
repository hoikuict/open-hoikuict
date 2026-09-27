import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from atomic_file import replace_file
from windows_setup.storage import atomic_json as setup_json
from restore_control import atomic_json as control_json


class AtomicReplacementTests(unittest.TestCase):
    def test_permanent_denial_is_bounded_and_retains_original(self):
        with tempfile.TemporaryDirectory() as directory:
            original, staged = Path(directory) / 'state', Path(directory) / 'new'
            original.write_bytes(b'original')
            staged.write_bytes(b'new')
            error = PermissionError('denied')
            error.winerror = 5
            with patch('atomic_file.os.replace', side_effect=error), patch('atomic_file.time.monotonic', side_effect=[0, 3]):
                with self.assertRaises(PermissionError):
                    replace_file(staged, original)
            self.assertEqual(original.read_bytes(), b'original')
            self.assertEqual(staged.read_bytes(), b'new')

    @unittest.skipUnless(os.name == 'nt', 'Real Windows file sharing')
    def test_json_updates_survive_reader_that_disallows_delete_sharing(self):
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                      ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        for write in (setup_json, control_json):
            with self.subTest(writer=write.__module__), tempfile.TemporaryDirectory() as directory:
                target = Path(directory) / 'gateway.json'
                write(target, {'seen': 1})
                handle = kernel.CreateFileW(str(target), 0x80000000, 3, None, 3, 0x80, None)
                self.assertNotEqual(handle, ctypes.c_void_p(-1).value)
                held = threading.Event()
                def release():
                    held.wait(.15)
                    kernel.CloseHandle(handle)
                reader = threading.Thread(target=release)
                reader.start()
                try:
                    staged = Path(directory) / 'without-retry'
                    staged.write_text('{}')
                    with self.assertRaises(PermissionError):
                        os.replace(staged, target)
                    staged.unlink()
                    write(target, {'seen': 2})
                    self.assertEqual(json.loads(target.read_text())['seen'], 2)
                    self.assertEqual([item.name for item in Path(directory).iterdir()], ['gateway.json'])
                finally:
                    held.set()
                    reader.join()


if __name__ == '__main__':
    unittest.main()
