"""Exercise optional search filters through real routes and a fictional SQLite corpus."""
from contextlib import closing
from html import unescape
import re
import sqlite3
import unittest
from urllib.parse import parse_qs, urlsplit

from sqlmodel import Session
from models import Classroom
import test_plan_docs as plan_fixtures


class DailyExampleSearchTests(unittest.TestCase):
    def setUp(self):
        self.fixture = plan_fixtures.PlanDocsIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.client = self.fixture.client
        self.client.cookies.update(self.fixture.staff_cookies())
        with Session(self.fixture.engine) as session:
            session.add(Classroom(name="りす組（1歳児）", display_order=3))
            session.commit()
        with closing(sqlite3.connect(self.fixture.corpus_path)) as db:
            db.row_factory = sqlite3.Row
            original = dict(db.execute("select * from daily_plan_examples where id='daily-001'").fetchone())
            for age, month in [(3, 9), (1, 8), (1, 9)]:
                record = dict(original, id=f"fiction-{age}-{month}", age_class=age, month=month,
                              source_ref=f"fiction:{age}:{month}", content_hash=f"fiction-{age}-{month}")
                db.execute(f"insert into daily_plan_examples ({','.join(record)}) values ({','.join('?' for _ in record)})", list(record.values()))
            db.commit()

    def search(self, **params):
        response = self.client.get("/plans/daily-plans/new", params={
            "target_date": "2026-09-01", "classroom_ref": "りす組（1歳児）", **params,
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response

    def test_each_combination_filters_real_corpus(self):
        for age, month, expected in [("3歳児", "8", 1), ("3歳児", "", 2), ("", "8", 2), ("", "", 4)]:
            with self.subTest(age=age, month=month):
                response = self.search(age_class=age, month=month)
                examples = response.context["examples"]
                self.assertEqual(len(examples), expected)
                self.assertEqual(response.context["selected_age_class"], age)
                self.assertEqual(response.context["selected_month"], int(month) if month else None)
                self.assertTrue(all(not age or e.age_class == age for e in examples))
                self.assertTrue(all(not month or e.month == int(month) for e in examples))
                self.assertTrue(all(not e.review_pending for e in examples))

    def test_empty_filters_do_not_reapply_calendar_defaults(self):
        default = self.search()
        self.assertEqual(default.context["selected_age_class"], "1歳児")
        self.assertEqual(default.context["selected_month"], 9)
        cleared = self.search(age_class="", month="")
        self.assertEqual(cleared.context["selected_age_class"], "")
        self.assertIsNone(cleared.context["selected_month"])
        self.assertEqual(cleared.context["form_values"]["age_class"], "1歳児")

    def test_keyword_only_search_spans_ages_and_months(self):
        result = self.search(age_class="", month="", q="粘土")
        self.assertEqual({e.age_class for e in result.context["examples"]}, {"1歳児", "3歳児"})
        self.assertEqual({e.month for e in result.context["examples"]}, {8, 9})
        self.assertEqual(self.search(age_class="", month="", q="架空の該当なし").context["examples"], [])

    def test_copy_link_keeps_filters_and_sets_only_draft_age(self):
        result = self.search(age_class="", month="", q="粘土")
        links = re.findall(r'class="button button--secondary daily-example-copy" href="([^"]+)"', result.text)
        selected_link = next(link for link in links if 'example_id=daily-001&' in unescape(link))
        copied = self.client.get(unescape(selected_link))
        query = parse_qs(urlsplit(unescape(selected_link)).query, keep_blank_values=True)
        self.assertEqual(query["age_class"], [""])
        self.assertEqual(query["month"], [""])
        self.assertEqual(query["q"], ["粘土"])
        self.assertEqual(copied.context["selected_age_class"], "")
        self.assertIsNone(copied.context["selected_month"])
        self.assertEqual(copied.context["form_values"]["age_class"], "3歳児")
        self.assertEqual(copied.context["form_values"]["target_date"], "2026-09-01")
        self.assertEqual(copied.context["form_values"]["classroom_ref"], "りす組（1歳児）")

    def test_validation_keeps_search_separate_from_draft(self):
        response = self.client.post("/plans/daily-plans", data={
            "age_class": "1歳児", "target_date": "", "classroom_ref": "りす組（1歳児）",
            "daily_aims": "編集中のねらい", "timeline_time": "10:00", "timeline_children": "架空の様子",
            "search_age_class": "", "search_month": "", "search_query": "粘土",
        })
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["errors"])
        self.assertEqual(response.context["selected_age_class"], "")
        self.assertIsNone(response.context["selected_month"])
        self.assertEqual(response.context["search_query"], "粘土")
        self.assertEqual(response.context["form_values"]["age_class"], "1歳児")
        self.assertEqual(response.context["form_values"]["daily_aims"], "編集中のねらい")

    def test_invalid_month_still_returns_validation_error(self):
        self.assertEqual(self.client.get("/plans/daily-plans/new?month=invalid").status_code, 422)


if __name__ == "__main__":
    unittest.main()
