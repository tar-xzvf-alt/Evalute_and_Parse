import unittest

from src.rubert_evaluation import classification, multilabel, score_predictions


class EvaluationTests(unittest.TestCase):
    def test_fixed_class_support_and_absent_class_macro(self):
        report = classification(['a', 'b'], ['a', 'a'], ['a', 'b', 'c'])
        self.assertEqual(report['confusion_matrix'], [[1, 0, 0], [1, 0, 0], [0, 0, 0]])
        self.assertAlmostEqual(report['macro_f1'], (2 / 3) / 3)
        self.assertEqual(report['absent_reference_classes'], ['c'])

    def test_topic_micro_and_macro_are_different(self):
        report = multilabel([[1, 2], [1]], [[1], [1]])
        self.assertAlmostEqual(report['micro_f1'], .8)
        self.assertAlmostEqual(report['macro_f1'], 1 / 8)

    def test_b_diagnostic_does_not_hide_filter_false_negatives(self):
        references = [{'id': 'a', 'include': True, 'assessment': 'negative', 'topics': [5]}]
        predictions = [{'id': 'a', 'include': False, 'assessment': 'negative', 'topics': [5]},
                       {'id': 'b', 'include': False, 'assessment': 'positive', 'topics': []}]
        report = score_predictions(predictions, references)
        self.assertEqual(report['filter_misses_on_reference_included'], 1)
        self.assertEqual(report['B_assessment_on_reference_included']['accuracy'], 1.)
        self.assertEqual(report['cascade_five_way']['accuracy'], 0.)
        self.assertEqual(report['cascade_topics_all_reference_rows']['micro_f1'], 0.)
        self.assertEqual(report['reference_coverage'], .5)

    def test_reject_duplicate_ids_and_missing_predictions(self):
        row = {'id': 'a', 'include': False, 'assessment': 'positive', 'topics': []}
        with self.assertRaises(ValueError):
            score_predictions([row, row], [])
        with self.assertRaises(ValueError):
            score_predictions([], [row])


if __name__ == '__main__':
    unittest.main()
