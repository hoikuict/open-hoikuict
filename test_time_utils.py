import unittest
from datetime import datetime, timezone

from time_utils import format_jst_datetime


class TimeUtilsTests(unittest.TestCase):
    def test_format_jst_datetime_treats_naive_database_value_as_utc(self):
        value = datetime(2026, 7, 25, 23, 22)

        self.assertEqual(format_jst_datetime(value), "2026-07-26 08:22")

    def test_format_jst_datetime_converts_aware_utc_value(self):
        value = datetime(2026, 7, 25, 23, 22, tzinfo=timezone.utc)

        self.assertEqual(format_jst_datetime(value), "2026-07-26 08:22")


if __name__ == "__main__":
    unittest.main()
