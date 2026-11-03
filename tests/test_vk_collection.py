import json
import random
import sys
import tempfile
import threading
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from vk_collection import (Cancelled, CollectionError, VKClient, WallPeriod,
                           export_posts, load_profile, measure, save_profile,
                           select_groups, year_period)


class FakeClient:
    def __init__(self, posts):
        self.items = posts
        self.calls = 0
        self.cancel = threading.Event()

    def call(self, method, **params):
        self.calls += 1
        offset, count = params["offset"], params["count"]
        return {"count": len(self.items), "items": self.items[offset:offset + count]}


def post(pid, date, pinned=False, text="Экономические новости региона"):
    return {"id": pid, "date": date, "is_pinned": int(pinned), "text": text}


class WallTests(unittest.TestCase):
    def test_matches_sequential_with_pinned_and_equal_dates(self):
        cases = [[], [post(1, 2)], [post(1, 100, True)],
                 [post(999, 5, True)] + [post(i, 10 - i // 2) for i in range(20)]]
        for items in cases:
            for start, end in ((0, 20), (3, 7), (5, 6), (10, 11), (20, 30)):
                with self.subTest(length=len(items), start=start, end=end):
                    period = WallPeriod(FakeClient(items), 1, start, end)
                    expected = {p["id"] for p in items if start <= p["date"] < end}
                    self.assertEqual(period.estimate(), len(expected))
                    self.assertEqual({p["id"] for p in period.posts()}, expected)

    def test_does_not_scan_newer_history(self):
        items = [post(i, 100000 - i) for i in range(100000)]
        client = FakeClient(items)
        period = WallPeriod(client, 1, 1000, 1100)
        self.assertEqual(len(list(period.posts())), 100)
        self.assertLess(client.calls, 45)

    def test_monthly_counts(self):
        start, end = year_period(2020)
        period = WallPeriod(FakeClient([post(1, start), post(2, start - 1)]), 1, start, end)
        count, months = measure(period)
        self.assertEqual(count, 1)
        self.assertEqual(months, [1] + [0] * 11)

    def test_random_intervals_match_full_scan(self):
        rng = random.Random(42)
        items = [post(i, date) for i, date in enumerate(
            sorted((rng.randrange(2000) for _ in range(1500)), reverse=True))]
        items.insert(0, post(99999, 777, True))
        for _ in range(30):
            start = rng.randrange(2000)
            end = start + rng.randrange(1, 500)
            period = WallPeriod(FakeClient(items), 1, start, end)
            expected = {p["id"] for p in items if start <= p["date"] < end}
            self.assertEqual(period.estimate(), len(expected))
            self.assertEqual({p["id"] for p in period.posts()}, expected)

    def test_change_before_first_output_relocates_safely(self):
        client = FakeClient([post(i, 1000-i) for i in range(1000)])
        period = WallPeriod(client, 1, 10, 20)
        client.items.append(post(1001, 0))
        # Nothing has been emitted yet: a fresh bounded search is safe.
        self.assertEqual({p['id'] for p in period.posts()}, set(range(981, 991)))
        self.assertEqual(period.recovery_count, 1)

    def test_cancel_before_network(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(Cancelled):
            VKClient("test", event).call("wall.get")

    def test_detects_disordered_first_page(self):
        with self.assertRaises(CollectionError):
            WallPeriod(FakeClient([post(1, 1), post(2, 10)]), 1, 0, 20)


class ProfileTests(unittest.TestCase):
    def test_profile_preserves_selection_without_secret_or_stale_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            save_profile(path, {"year": "2020", "token": "SECRET"},
                         [{"id": 1, "name": "Новости", "selected": True, "count": 100}])
            data = load_profile(path)
            self.assertNotIn("SECRET", path.read_text())
            self.assertTrue(data["groups"][0]["selected"])
            self.assertNotIn("count", data["groups"][0])

    def test_rank_threshold_errors_and_ties(self):
        rows = [{"id": 3, "count": 20}, {"id": 1, "count": 20},
                {"id": 2, "count": 100, "error": "denied"}, {"id": 4, "count": 5}]
        self.assertEqual([r["id"] for r in select_groups(rows, 2, 10)], [1, 3])

    def test_export_text_and_manifest(self):
        from openpyxl import load_workbook
        start, _ = year_period(2020)
        with tempfile.TemporaryDirectory() as directory:
            client = FakeClient([post(1, start, text="=Новости региона")])
            path = export_posts(directory, [{"id": 1, "name": "Новости"}], client, 2020)
            data = json.loads(path.read_text())
            self.assertEqual(data["status"], "complete")
            workbook = load_workbook(Path(directory) / data["groups"][0]["file"])
            self.assertEqual(workbook.active["A1"].value, "text")
            cell = workbook.active["A2"]
            self.assertEqual(cell.value, "=Новости региона")
            self.assertEqual(cell.data_type, "s")
            workbook.close()
            raw = Path(directory) / data["groups"][0]["raw_file"]
            self.assertEqual(json.loads(raw.read_text())["text"], "=Новости региона")

    def test_raw_archive_includes_filtered_out_text(self):
        start, _ = year_period(2020)
        with tempfile.TemporaryDirectory() as directory:
            path = export_posts(directory, [{"id": 1, "name": "Новости"}],
                                FakeClient([post(1, start)]), 2020, keywords="отсутствует")
            data = json.loads(path.read_text())
            self.assertEqual(data["groups"][0]["retained"], 0)
            raw = Path(directory) / data["groups"][0]["raw_file"]
            self.assertEqual(len(raw.read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
