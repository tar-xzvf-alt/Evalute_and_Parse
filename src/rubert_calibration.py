"""Validation-only diagnostic topic thresholds with group-held-out predictions."""
import hashlib

from src.rubert_evaluation import multilabel


GRID = [i / 20 for i in range(1, 20)]


def best_threshold(truth, scores):
    if len(truth) != len(scores) or not truth:
        raise ValueError('nonempty aligned calibration arrays required')
    def score(threshold):
        tp = sum(y and p >= threshold for y, p in zip(truth, scores))
        fp = sum(not y and p >= threshold for y, p in zip(truth, scores))
        fn = sum(y and p < threshold for y, p in zip(truth, scores))
        denom = 2 * tp + fp + fn
        return 2 * tp / denom if denom else 0.
    return max(GRID, key=lambda t: (score(t), -abs(t - .5), t))


def validation_calibration(rows, groups, folds=5, seed=20261111):
    if len({r['id'] for r in rows}) != len(rows):
        raise ValueError('duplicate calibration IDs')
    if any(len(r['probabilities']) != 8 or any(not 0 <= p <= 1 for p in r['probabilities']) for r in rows):
        raise ValueError('eight finite probabilities required')
    group_names = sorted({groups[r['id']] for r in rows},
                         key=lambda g: hashlib.sha256(f'{seed}:{g}'.encode()).hexdigest())
    if not 2 <= folds <= len(group_names):
        raise ValueError('invalid fold count')
    assignment = {g: i % folds for i, g in enumerate(group_names)}
    row_folds = {r['id']: assignment[groups[r['id']]] for r in rows}
    called = {}; thresholds_by_fold = {}
    for fold in range(folds):
        fit = [r for r in rows if row_folds[r['id']] != fold]
        thresholds = [best_threshold([topic in r['topics'] for r in fit],
                                     [r['probabilities'][topic - 1] for r in fit]) for topic in range(1, 9)]
        thresholds_by_fold[str(fold)] = thresholds
        for r in rows:
            if row_folds[r['id']] == fold:
                called[r['id']] = [t for t, p in enumerate(r['probabilities'], 1) if p >= thresholds[t - 1]]
    full = [best_threshold([topic in r['topics'] for r in rows],
                           [r['probabilities'][topic - 1] for r in rows]) for topic in range(1, 9)]
    truth = [r['topics'] for r in rows]
    oof_metrics = multilabel(truth, [called[r['id']] for r in rows])
    oof_metrics.pop('thresholds')
    oof_metrics['decision_rule'] = 'topic-specific thresholds fitted outside the held-out group fold'
    all_topics_metrics = multilabel(truth, [list(range(1, 9)) for r in rows])
    all_topics_metrics.pop('thresholds')
    all_topics_metrics['decision_rule'] = 'always predict all eight topics; no probability threshold'
    return {'rows': len(rows), 'folds': folds, 'seed': seed, 'threshold_grid': GRID,
            'fold_assignment': row_folds, 'thresholds_by_fold': thresholds_by_fold,
            'thresholds_fit_all_validation': full,
            'original_fixed_point5': multilabel(truth, [[t for t, p in enumerate(r['probabilities'], 1) if p >= .5] for r in rows]),
            'out_of_fold_calibrated': oof_metrics,
            'always_all_topics_baseline': all_topics_metrics,
            'test_used': False, 'model_weights_changed': False,
            'scope': 'diagnostic cross-fitted validation; model checkpoint already selected on validation, not an independent test estimate',
            'threshold_file_not_applied_to_test': True}
