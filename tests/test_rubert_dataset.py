import itertools
import json
import random
import tempfile
import unittest
from pathlib import Path

from src.rubert_dataset import group_texts, shingles, split_groups
from src.rubert_training import load_dataset, training_topic_weights


class DuplicateTests(unittest.TestCase):
    def test_exact_unicode_whitespace_and_short_distinction(self):
        rows = [{'id': 'a', 'text': 'Привет  МИР'}, {'id': 'b', 'text': 'привет\nмир'},
                {'id': 'c', 'text': 'привет другой мир'}]
        mapping, edges = group_texts(rows)
        self.assertEqual(mapping['a'], mapping['b'])
        self.assertNotEqual(mapping['a'], mapping['c'])
        self.assertEqual(edges[0]['kind'], 'exact')

    def test_prefix_join_matches_exhaustive_pair_scores(self):
        rng = random.Random(7)
        base = ['слово' + str(i) for i in range(100)]
        rows = []
        for i in range(40):
            words = base.copy()
            for _ in range(rng.randrange(1, 12)):
                words[rng.randrange(100)] = 'замена' + str(rng.randrange(20))
            rows.append({'id': str(i), 'text': ' '.join(words)})
        _, edges = group_texts(rows)
        observed = {frozenset([e['a'], e['b']]) for e in edges if e['kind'] == 'word5_jaccard'}
        expected = set()
        for a, b in itertools.combinations(rows, 2):
            x, y = shingles(a['text']), shingles(b['text'])
            if len(x & y) / len(x | y) >= .82:
                expected.add(frozenset([a['id'], b['id']]))
        self.assertEqual(observed, expected)

    def test_urls_removed_from_near_match(self):
        text = ' '.join('термин' + str(i) for i in range(30))
        mapping, _ = group_texts([{'id': 'a', 'text': text + ' https://example.org/a'},
                                  {'id': 'b', 'text': text + ' https://example.org/b'}])
        self.assertEqual(mapping['a'], mapping['b'])

    def test_split_groups_are_indivisible_and_reviewed_train_only(self):
        rows = [{'id': str(i), 'near_group_id': 'g' + str(i // 2),
                 'include': bool(i % 2), 'assessment': 'negative' if i % 2 else None,
                 'topics': [5] if i % 2 else [], 'source_region': 'Регион', 'group_id': 1}
                for i in range(100)]
        result = split_groups(rows, forced_train=['g0'])
        self.assertEqual(result, split_groups(rows, forced_train=['g0']))
        self.assertEqual(result['0'], 'train')
        self.assertEqual(set(result.values()), {'train', 'validation', 'test'})
        for i in range(0, 100, 2):
            self.assertEqual(result[str(i)], result[str(i + 1)])

    def test_invalid_threshold_and_duplicate_id(self):
        with self.assertRaises(ValueError):
            group_texts([], 0)
        with self.assertRaises(ValueError):
            group_texts([{'id': 'a', 'text': 'x'}, {'id': 'a', 'text': 'y'}])

    def test_loader_rejects_cross_split_group_leakage(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'manifest.json').write_text(json.dumps({'artifact_sha256': {}}))
            for i, split in enumerate(['train', 'validation', 'test']):
                row = {'id': str(i), 'split': split, 'near_group_id': 'same', 'include': True}
                (folder / (split + '.jsonl')).write_text(json.dumps(row) + '\n')
            with self.assertRaisesRegex(ValueError, 'leaks'):
                load_dataset(folder, 'A')

    def test_loader_detects_changed_artifact(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            (folder / 'manifest.json').write_text(json.dumps({'artifact_sha256': {'train.jsonl': 'bad'}}))
            (folder / 'train.jsonl').write_text('{}\n')
            with self.assertRaisesRegex(ValueError, 'changed'):
                load_dataset(folder, 'A')

    def test_positive_weights_are_training_only_and_match_class_counts(self):
        rows = [{'split': 'train', 'include': True, 'topics': [2 * i + 1, 2 * i + 2]} for i in range(4)]
        positive, weights = training_topic_weights(rows)
        self.assertEqual(positive, [1] * 8)
        self.assertEqual(weights, [3.] * 8)
        with self.assertRaises(ValueError):
            training_topic_weights([{**rows[0], 'split': 'validation'}] + rows[1:])
        with self.assertRaises(ValueError):
            training_topic_weights(rows[:3])


if __name__ == '__main__':
    unittest.main()
