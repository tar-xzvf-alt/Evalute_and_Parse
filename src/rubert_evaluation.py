"""Frozen-test inference and descriptive agreement metrics (not independent gold)."""
import argparse
from collections import Counter
import gc
import hashlib
import json
from pathlib import Path
import time

from src.rubert_dataset import ASSESSMENTS, read_jsonl, write_json


def classification(truth, predicted, labels):
    if len(truth) != len(predicted):
        raise ValueError('reference/prediction length mismatch')
    if any(x not in labels for x in truth + predicted):
        raise ValueError('unknown class')
    index = {name: i for i, name in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for a, b in zip(truth, predicted):
        matrix[index[a]][index[b]] += 1
    per_class = {}
    for i, name in enumerate(labels):
        tp = matrix[i][i]; support = sum(matrix[i]); called = sum(row[i] for row in matrix)
        precision = tp / called if called else 0.
        recall = tp / support if support else 0.
        per_class[name] = {'precision': precision, 'recall': recall,
                           'f1': 2 * precision * recall / (precision + recall) if precision + recall else 0.,
                           'support': support, 'predicted_count': called}
    return {'n': len(truth), 'labels': labels, 'confusion_matrix': matrix,
            'accuracy': sum(matrix[i][i] for i in range(len(labels))) / len(truth) if truth else None,
            'macro_f1': sum(v['f1'] for v in per_class.values()) / len(labels),
            'per_class': per_class, 'zero_division_policy': 0,
            'absent_reference_classes': [k for k, v in per_class.items() if not v['support']]}


def multilabel(truth, predicted):
    if len(truth) != len(predicted):
        raise ValueError('reference/prediction length mismatch')
    result = {}; totals = Counter()
    for topic in range(1, 9):
        tp = sum(topic in a and topic in b for a, b in zip(truth, predicted))
        fp = sum(topic not in a and topic in b for a, b in zip(truth, predicted))
        fn = sum(topic in a and topic not in b for a, b in zip(truth, predicted))
        totals.update(tp=tp, fp=fp, fn=fn)
        result[str(topic)] = {'precision': tp / (tp + fp) if tp + fp else 0.,
                              'recall': tp / (tp + fn) if tp + fn else 0.,
                              'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.,
                              'support': tp + fn, 'predicted_count': tp + fp}
    denominator = 2 * totals['tp'] + totals['fp'] + totals['fn']
    return {'n': len(truth), 'micro_f1': 2 * totals['tp'] / denominator if denominator else 0.,
            'macro_f1': sum(r['f1'] for r in result.values()) / 8, 'per_topic': result,
            'exact_match_ratio': sum(set(a) == set(b) for a, b in zip(truth, predicted)) / len(truth) if truth else None,
            'thresholds': [.5] * 8, 'zero_division_policy': 0}


def score_predictions(predictions, references):
    p = {r['id']: r for r in predictions}; ref = {r['id']: r for r in references}
    if len(p) != len(predictions) or len(ref) != len(references):
        raise ValueError('duplicate evaluation IDs')
    if not set(ref) <= set(p):
        raise ValueError('reference without prediction')
    ids = sorted(ref)
    included = [i for i in ids if ref[i]['include']]
    def five(r):
        return r['assessment'] if r['include'] else 'excluded'
    a = classification([str(ref[i]['include']) for i in ids], [str(p[i]['include']) for i in ids], ['False', 'True'])
    assessment = classification([ref[i]['assessment'] for i in included], [p[i]['assessment'] for i in included], ASSESSMENTS)
    topics = multilabel([ref[i]['topics'] for i in included], [p[i]['topics'] for i in included])
    cascade = classification([five(ref[i]) for i in ids], [five(p[i]) for i in ids], ['excluded'] + ASSESSMENTS)
    cascade_topics = multilabel([ref[i]['topics'] if ref[i]['include'] else [] for i in ids],
                               [p[i]['topics'] if p[i]['include'] else [] for i in ids])
    return {'reference_rows': len(ids), 'prediction_rows': len(p),
            'reference_coverage': len(ids) / len(p) if p else None,
            'missing_reference_ids': sorted(set(p) - set(ref)), 'reference_included': len(included),
            'A_filter': a, 'B_assessment_on_reference_included': assessment,
            'B_topics_on_reference_included': topics, 'cascade_five_way': cascade,
            'cascade_topics_all_reference_rows': cascade_topics,
            'filter_misses_on_reference_included': sum(not p[i]['include'] for i in included),
            'B_scope': 'diagnostic B applied to every test input; inclusion misses counted separately, not hidden',
            'independent_human_gold': False}


def predict(project, run_dir, output):
    import torch
    from transformers import AutoTokenizer
    from src.rubert_model import PublicationModel
    from src.rubert_training import load_dataset

    project, run_dir, output = Path(project), Path(run_dir), Path(output)
    status = json.loads((run_dir / 'status.json').read_text(encoding='utf-8'))
    if status['status'] != 'completed':
        raise ValueError('training must complete before test inference')
    if output.exists():
        raise ValueError('refuse overwriting a test inference run')
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable')
    manifest, splits = load_dataset(project / 'dataset', 'A')
    rows = splits['test']
    output.mkdir()
    results = {r['id']: {'id': r['id'], 'source_region': r['source_region']} for r in rows}
    report = {'source_commit': status['source_commit'], 'test_rows': len(rows), 'models': {},
              'test_sha256': hashlib.sha256((project / 'dataset/test.jsonl').read_bytes()).hexdigest(),
              'thresholds': [.5] * 8, 'reference_type': 'original provisional machine labels',
              'test_tuning': False, 'independent_human_gold': False}
    for task in ('A', 'B'):
        root = run_dir / ('model_' + task)
        if not (root / 'completed.json').is_file():
            raise ValueError('missing child completion artifact')
        best = json.loads((root / 'best_checkpoint.json').read_text(encoding='utf-8'))
        checkpoint = (root / best['path']).resolve()
        if checkpoint.parent != root.resolve():
            raise ValueError('invalid checkpoint path')
        metadata = json.loads((checkpoint / 'publication_model.json').read_text(encoding='utf-8'))
        length = metadata['metadata']['max_length']
        if metadata['task'] != task or metadata['metadata']['assessments'] != ASSESSMENTS or length != 512:
            raise ValueError('unexpected checkpoint task/classes/length')
        tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True, trust_remote_code=False)
        model = PublicationModel.load(checkpoint).eval().to('cuda')
        started = time.perf_counter()
        with torch.inference_mode():
            for offset in range(0, len(rows), 2):
                batch = rows[offset:offset + 2]
                encoded = tokenizer([r['source_region'] for r in batch], [r['text'] for r in batch],
                                    padding=True, truncation='only_second', max_length=length, return_tensors='pt')
                logits = model(**{k: v.to('cuda') for k, v in encoded.items()})
                if any(not torch.isfinite(v).all() for v in logits.values()):
                    raise ValueError('nonfinite test logits')
                if task == 'A':
                    probs = logits['inclusion'].softmax(-1).cpu().tolist()
                    raw_lengths = tokenizer([r['source_region'] for r in batch], [r['text'] for r in batch],
                                            truncation=False, padding=False, verbose=False)['input_ids']
                    for r, prob, tokens in zip(batch, probs, raw_lengths):
                        results[r['id']].update(include=prob[1] > prob[0], include_probability=prob[1],
                                                 token_length=len(tokens), truncated=len(tokens) > length)
                else:
                    probs = logits['assessment'].softmax(-1).cpu().tolist()
                    topic_probs = logits['topics'].sigmoid().cpu().tolist()
                    for r, prob, topics in zip(batch, probs, topic_probs):
                        results[r['id']].update(assessment=ASSESSMENTS[max(range(4), key=lambda n: prob[n])],
                                                 assessment_probabilities=prob, topic_probabilities=topics,
                                                 topics=[i + 1 for i, v in enumerate(topics) if v >= .5])
        torch.cuda.synchronize()
        report['models'][task] = {'selected_by': 'validation only', 'checkpoint': str(checkpoint),
                                  'best_validation': best, 'inference_seconds': time.perf_counter() - started,
                                  'weights_sha256': hashlib.sha256((checkpoint / 'model.safetensors').read_bytes()).hexdigest()}
        del model; gc.collect(); torch.cuda.empty_cache()
    predictions = [results[r['id']] for r in rows]
    (output / 'predictions.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in predictions), encoding='utf-8')
    write_json(output / 'metrics_original_reference.json', score_predictions(predictions, rows))
    write_json(output / 'inference_manifest.json', report)
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(predict(args.project, args.run_dir, args.output), ensure_ascii=False, indent=2))
