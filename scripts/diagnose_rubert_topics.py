"""Reproduce topic-head collapse on validation; never read or tune on test."""
import argparse
import hashlib
import json
from pathlib import Path
import random
import sys


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project', required=True)
    parser.add_argument('--training-run', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--assert-noncollapsed', action='store_true')
    args = parser.parse_args()
    project, run, output = Path(args.project), Path(args.training_run), Path(args.output)
    sys.path.insert(0, str(project))
    import numpy as np
    import torch
    from sklearn.metrics import average_precision_score, f1_score, roc_auc_score
    from transformers import AutoTokenizer
    from src.rubert_model import PublicationModel

    if not torch.cuda.is_available():
        raise RuntimeError('GPU required for reproducible local inference')
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((project / 'dataset/manifest.json').read_text(encoding='utf-8'))
    datasets = {}
    for split in ('train', 'validation'):
        path = project / 'dataset' / (split + '.jsonl')
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest['artifact_sha256'][path.name]:
            raise ValueError('changed ' + split)
        rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        datasets[split] = [r for r in rows if r['include']]
    rng = random.Random(20261110)
    datasets['train'] = rng.sample(datasets['train'], min(512, len(datasets['train'])))
    best = json.loads((run / 'model_B/best_checkpoint.json').read_text(encoding='utf-8'))
    checkpoint = run / 'model_B' / best['path']
    weight_hash = hashlib.sha256((checkpoint / 'model.safetensors').read_bytes()).hexdigest()
    cache = output / 'train_validation_scores.json'
    if cache.exists():
        scores = json.loads(cache.read_text(encoding='utf-8'))
        if scores['weight_sha256'] != weight_hash or scores['dataset_hashes'] != manifest['artifact_sha256']:
            raise ValueError('stale diagnostic cache')
    else:
        model = PublicationModel.load(checkpoint).eval().to('cuda')
        tokenizer = AutoTokenizer.from_pretrained(checkpoint, local_files_only=True)
        scores = {'weight_sha256': weight_hash, 'dataset_hashes': manifest['artifact_sha256'],
                  'test_read_or_predicted': False, 'splits': {}}
        with torch.inference_mode():
            for split, rows in datasets.items():
                values = []
                for start in range(0, len(rows), 2):
                    batch = rows[start:start + 2]
                    inputs = tokenizer([r['source_region'] for r in batch], [r['text'] for r in batch],
                                       padding=True, truncation='only_second', max_length=512, return_tensors='pt')
                    logits = model(**{k: v.to('cuda') for k, v in inputs.items()})
                    probs = logits['topics'].sigmoid().cpu().tolist()
                    for row, prob in zip(batch, probs):
                        values.append({'id': row['id'], 'topics': row['topics'], 'probabilities': prob})
                scores['splits'][split] = values
        cache.write_text(json.dumps(scores, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    report = {'checkpoint': str(checkpoint), 'test_used': False, 'split_metrics': {}}
    for split, rows in scores['splits'].items():
        y = np.array([[int(t in r['topics']) for t in range(1, 9)] for r in rows])
        p = np.array([r['probabilities'] for r in rows])
        per_topic = []
        for column in range(8):
            positives = y[:, column] == 1
            per_topic.append({'topic': column + 1, 'support': int(positives.sum()),
                              'prevalence': float(positives.mean()),
                              'predicted_at_point5': int((p[:, column] >= .5).sum()),
                              'mean_positive_probability': float(p[positives, column].mean()),
                              'mean_negative_probability': float(p[~positives, column].mean()),
                              'average_precision': float(average_precision_score(y[:, column], p[:, column])),
                              'roc_auc': float(roc_auc_score(y[:, column], p[:, column])),
                              'f1_at_point5': float(f1_score(y[:, column], p[:, column] >= .5, zero_division=0))})
        report['split_metrics'][split] = {'n': len(rows), 'per_topic': per_topic,
                                         'macro_f1_at_point5': float(f1_score(y, p >= .5, average='macro', zero_division=0)),
                                         'micro_f1_at_point5': float(f1_score(y, p >= .5, average='micro', zero_division=0))}
    validation = report['split_metrics']['validation']
    report['collapse_reproduced'] = any(t['support'] >= 20 and t['predicted_at_point5'] == 0 for t in validation['per_topic'])
    (output / 'diagnosis.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.assert_noncollapsed and report['collapse_reproduced']:
        raise SystemExit('FAIL: validation-supported themes receive zero predictions at fixed0.5')


if __name__ == '__main__':
    main()
