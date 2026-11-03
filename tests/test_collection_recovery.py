import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from vk_collection import CollectionError, WallPeriod, export_posts, year_period
from test_vk_collection import FakeClient, post


class ChangingWall(FakeClient):
    def __init__(self, items, change='prepend', during='pages'):
        super().__init__(items)
        self.change = change
        self.during = during
        self.changed = False
        self.pages = 0

    def call(self, method, **params):
        if params['count'] > 1 and params['offset'] > 0:
            self.pages += 1
        trigger = ((self.during == 'pages' and self.pages == 2)
                   or (self.during == 'bounds' and self.calls == 2)
                   or (self.during == 'final' and self.pages >= 2
                       and params['offset'] == 0 and params['count'] == 1))
        if trigger and not self.changed:
            self.changed = True
            if self.change == 'prepend':
                self.items.insert(0, post(99999, 20000))
            elif self.change == 'delete':
                self.items.pop()
            elif self.change == 'balanced':
                self.items.insert(0, post(99999, 20000))
                self.items.pop()
        return super().call(method, **params)


class RecoveryTests(unittest.TestCase):
    def items(self):
        return [post(i, 10000-i) for i in range(1000)]

    def test_prepend_during_bounds_restarts_before_yield(self):
        client = ChangingWall(self.items(), during='bounds')
        period = WallPeriod(client, 1, 9200, 9600)
        self.assertEqual({p['id'] for p in period.posts()}, set(range(401, 801)))
        self.assertGreater(period.recovery_count, 0)

    def test_prepend_during_pages_resumes_without_gaps_or_duplicates(self):
        client = ChangingWall(self.items())
        period = WallPeriod(client, 1, 9200, 9600)
        ids = [p['id'] for p in period.posts()]
        self.assertEqual(set(ids), set(range(401, 801)))
        self.assertEqual(len(ids), 400)
        self.assertEqual(period.recovery_count, 1)

    def test_deletion_still_rejects_incomplete_snapshot(self):
        period = WallPeriod(ChangingWall(self.items(), change='delete'), 1, 9200, 9600)
        with self.assertRaises(CollectionError):
            list(period.posts())

    def test_balanced_change_is_not_silently_deduplicated(self):
        period = WallPeriod(ChangingWall(self.items(), change='balanced'), 1, 9200, 9600)
        with self.assertRaises(CollectionError):
            list(period.posts())

    def test_prepend_at_final_check_is_reconciled(self):
        period = WallPeriod(ChangingWall(self.items(), during='final'), 1, 9200, 9600)
        self.assertEqual({p['id'] for p in period.posts()}, set(range(401, 801)))
        self.assertEqual(period.recovery_count, 1)

    def test_continuously_changing_wall_exhausts_bounded_budget(self):
        class Continuous(FakeClient):
            def call(self, method, **params):
                self.items.insert(0, post(10000 + self.calls, 20000 + self.calls))
                return super().call(method, **params)
        client = Continuous(self.items())
        with self.assertRaisesRegex(CollectionError, '3 попытки'):
            WallPeriod(client, 1, 9200, 9600)
        self.assertLess(client.calls, 12)

    def test_resume_reuses_verified_completed_source(self):
        start, _ = year_period(2019)
        with tempfile.TemporaryDirectory() as directory:
            first = export_posts(directory, [{'id':1,'name':'One'}],
                                 FakeClient([post(1,start)]), 2019)
            manifest = json.loads(first.read_text())
            manifest['groups'].append({'id':2,'name':'Two','status':'failed'})
            manifest['planned_group_ids'] = [1, 2]
            manifest['status'] = 'failed'
            first.write_text(json.dumps(manifest))
            client = FakeClient([post(2,start)])
            result = export_posts(directory, [{'id':1,'name':'One'}, {'id':2,'name':'Two'}],
                                  client, 2019, resume_manifest=first)
            data = json.loads(result.read_text())
            self.assertEqual(data['status'], 'complete')
            self.assertTrue(data['groups'][0]['reused'])
            self.assertEqual(data['groups'][0]['file'], manifest['groups'][0]['file'])
            self.assertEqual(data['groups'][1]['available'], 1)

    def test_resume_rejects_corrupted_completed_source_before_api(self):
        start, _ = year_period(2019)
        with tempfile.TemporaryDirectory() as directory:
            first = export_posts(directory, [{'id':1,'name':'One'}],
                                 FakeClient([post(1,start)]), 2019)
            data = json.loads(first.read_text())
            (Path(directory)/data['groups'][0]['raw_file']).write_text('')
            client = FakeClient([])
            with self.assertRaises(CollectionError):
                export_posts(directory, [{'id':1,'name':'One'}],client,2019,resume_manifest=first)
            self.assertEqual(client.calls, 0)

    def test_resume_rejects_parameter_changes_and_bad_excel(self):
        start, _ = year_period(2019)
        with tempfile.TemporaryDirectory() as directory:
            first = export_posts(directory, [{'id':1,'name':'One'}],
                                 FakeClient([post(1,start)]), 2019)
            client = FakeClient([])
            with self.assertRaises(CollectionError):
                export_posts(directory,[{'id':1,'name':'One'}],client,2020,resume_manifest=first)
            data = json.loads(first.read_text())
            (Path(directory)/data['groups'][0]['file']).write_text('not an Excel file')
            with self.assertRaises(CollectionError):
                export_posts(directory,[{'id':1,'name':'One'}],client,2019,resume_manifest=first)
            self.assertEqual(client.calls, 0)


if __name__ == '__main__':
    unittest.main()
