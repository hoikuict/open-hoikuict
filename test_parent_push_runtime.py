import os
import unittest
from unittest.mock import patch

from parent_push_runtime import parent_push_worker_enabled


class ParentPushRuntimeTests(unittest.TestCase):
    def test_capture_worker_runs_only_in_development(self):
        with patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "development",
                "HOIKUICT_PUSH_TRANSPORT": "capture",
            },
            clear=True,
        ):
            self.assertTrue(parent_push_worker_enabled())

        for environment in ("test", "production"):
            with self.subTest(environment=environment):
                with patch.dict(
                    os.environ,
                    {
                        "HOIKUICT_ENV": environment,
                        "HOIKUICT_PUSH_TRANSPORT": "capture",
                    },
                    clear=True,
                ):
                    self.assertFalse(parent_push_worker_enabled())

    def test_disabled_transport_never_starts_worker(self):
        with patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "development",
                "HOIKUICT_PUSH_TRANSPORT": "disabled",
            },
            clear=True,
        ):
            self.assertFalse(parent_push_worker_enabled())

    def test_webpush_worker_runs_only_in_development(self):
        with patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "development",
                "HOIKUICT_PUSH_TRANSPORT": "webpush",
            },
            clear=True,
        ):
            self.assertTrue(parent_push_worker_enabled())

        with patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "production",
                "HOIKUICT_PUSH_TRANSPORT": "webpush",
            },
            clear=True,
        ):
            self.assertFalse(parent_push_worker_enabled())


if __name__ == "__main__":
    unittest.main()
