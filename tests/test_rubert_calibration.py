import unittest

from src.rubert_calibration import best_threshold, validation_calibration


class CalibrationTests(unittest.TestCase):
    def test_default_preferred_when_equally_good(self):
        self.assertEqual(best_threshold([True, False], [.9, .1]), .5)

    def test_can_recover_a_low_probability_separating_threshold(self):
        self.assertEqual(best_threshold([True, False], [.25, .1]), .25)

    def rows(self):
        return [{'id': str(i), 'topics': [1] if i % 2 else [2],
                 'probabilities': [.2 + .1 * (i % 2), .3 - .1 * (i % 2)] + [.1] * 6} for i in range(30)]

    def test_group_members_never_split_and_own_fold_labels_cannot_fit_threshold(self):
        rows = self.rows(); groups = {r['id']: 'g' + str(int(r['id']) // 2) for r in rows}
        result = validation_calibration(rows, groups)
        self.assertEqual(result['fold_assignment']['0'], result['fold_assignment']['1'])
        fold = result['fold_assignment']['0']
        changed = [{**r, 'topics': [8]} if result['fold_assignment'][r['id']] == fold else r for r in rows]
        other = validation_calibration(changed, groups)
        self.assertEqual(result['thresholds_by_fold'][str(fold)], other['thresholds_by_fold'][str(fold)])
        self.assertFalse(result['test_used'])
        self.assertNotIn('thresholds', result['out_of_fold_calibrated'])
        self.assertNotIn('thresholds', result['always_all_topics_baseline'])
        self.assertEqual(result['original_fixed_point5']['thresholds'], [.5] * 8)

    def test_invalid_probabilities_rejected(self):
        rows = self.rows(); rows[0]['probabilities'][0] = float('nan')
        with self.assertRaises(ValueError):
            validation_calibration(rows, {r['id']: r['id'] for r in rows})


if __name__ == '__main__':
    unittest.main()
