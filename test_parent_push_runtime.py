import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from sqlmodel import create_engine

from parent_push_runtime import parent_push_worker_enabled, run_parent_push_worker_once


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

    def test_public_demo_webpush_starts_worker_in_production(self):
        with patch.dict(
            os.environ,
            {
                "HOIKUICT_ENV": "production",
                "PUBLIC_DEMO_MODE": "1",
                "HOIKUICT_PUSH_TRANSPORT": "webpush",
            },
            clear=True,
        ):
            self.assertTrue(parent_push_worker_enabled())

    def test_public_demo_worker_processes_each_session_engine(self):
        first_engine = create_engine("sqlite://")
        second_engine = create_engine("sqlite://")
        manager = SimpleNamespace(
            active_session_engines=lambda: (
                ("a" * 32, first_engine),
                ("b" * 32, second_engine),
            )
        )
        try:
            with (
                patch.dict(
                    os.environ,
                    {
                        "HOIKUICT_ENV": "production",
                        "PUBLIC_DEMO_MODE": "1",
                        "HOIKUICT_PUSH_TRANSPORT": "capture",
                    },
                    clear=True,
                ),
                patch(
                    "parent_push_runtime.get_demo_session_manager",
                    return_value=manager,
                ),
                patch(
                    "parent_push_runtime.create_parent_push_transport",
                    return_value=object(),
                ),
                patch(
                    "parent_push_runtime.run_parent_push_worker_cycle",
                    return_value=1,
                ) as worker_cycle,
            ):
                self.assertEqual(run_parent_push_worker_once(), 2)

            self.assertEqual(worker_cycle.call_count, 2)
            self.assertIs(worker_cycle.call_args_list[0].args[0].get_bind(), first_engine)
            self.assertIs(worker_cycle.call_args_list[1].args[0].get_bind(), second_engine)
            self.assertEqual(
                worker_cycle.call_args_list[0].kwargs["environment"], "production"
            )
        finally:
            first_engine.dispose()
            second_engine.dispose()


if __name__ == "__main__":
    unittest.main()
