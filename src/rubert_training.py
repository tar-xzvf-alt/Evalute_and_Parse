"""Explicit GPU-only benchmark/train commands for the provisional A/B baseline."""
import argparse
import gc
import hashlib
import json
import math
import random
import statistics
import time
from pathlib import Path

from src.rubert_dataset import ASSESSMENTS, read_jsonl, write_json


def load_dataset(path, task):
    path = Path(path)
    manifest = json.loads((path / 'manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['artifact_sha256'].items():
        if hashlib.sha256((path / name).read_bytes()).hexdigest() != expected:
            raise ValueError('dataset artifact changed: ' + name)
    result = {s: read_jsonl(path / (s + '.jsonl')) for s in ('train', 'validation', 'test')}
    seen = set(); groups = {}
    for split, rows in result.items():
        for r in rows:
            if r['id'] in seen or r['split'] != split:
                raise ValueError('duplicate or incorrectly assigned row')
            seen.add(r['id'])
            g = r['near_group_id']
            if g in groups and groups[g] != split:
                raise ValueError('duplicate family leaks across splits')
            groups[g] = split
    if task == 'B':
        result = {s: [r for r in rows if r['include']] for s, rows in result.items()}
    if any(not rows for rows in result.values()):
        raise ValueError('empty task split')
    return manifest, result


def encode_rows(tokenizer, rows, length):
    encoded = tokenizer([r['source_region'] for r in rows], [r['text'] for r in rows],
                        truncation='only_second', max_length=length, padding=False)
    return [{k: v[i] for k, v in encoded.items()} for i in range(len(rows))]


def pack(tokenizer, encodings, rows, indices, device, length, fixed=False):
    import torch
    inputs = tokenizer.pad([encodings[i] for i in indices], padding='max_length' if fixed else True,
                           max_length=length if fixed else None, return_tensors='pt')
    inputs = {k: v.to(device) for k, v in inputs.items()}
    chosen = [rows[i] for i in indices]
    inclusion = torch.tensor([int(r['include']) for r in chosen], device=device)
    assessment = torch.tensor([ASSESSMENTS.index(r['assessment']) if r['include'] else 0 for r in chosen], device=device)
    topics = torch.tensor([[float(t in r['topics']) for t in range(1, 9)] for r in chosen], device=device)
    return inputs, (inclusion, assessment, topics)


def evaluate(model, tokenizer, encodings, rows, batch_size, device, length):
    import numpy as np
    import torch
    from sklearn.metrics import classification_report, confusion_matrix, f1_score
    model.eval(); predictions = []; topic_predictions = []
    start = time.perf_counter()
    with torch.inference_mode():
        for offset in range(0, len(rows), batch_size):
            indices = list(range(offset, min(offset + batch_size, len(rows))))
            inputs, _ = pack(tokenizer, encodings, rows, indices, device, length)
            logits = model(**inputs)
            key = 'inclusion' if model.task == 'A' else 'assessment'
            predictions.extend(logits[key].argmax(-1).cpu().tolist())
            if model.task == 'B':
                topic_predictions.extend((logits['topics'].sigmoid() >= .5).cpu().int().tolist())
    torch.cuda.synchronize()
    truth = [int(r['include']) if model.task == 'A' else ASSESSMENTS.index(r['assessment']) for r in rows]
    labels = [0, 1] if model.task == 'A' else list(range(4))
    names = ['exclude', 'include'] if model.task == 'A' else ASSESSMENTS
    macro = f1_score(truth, predictions, labels=labels, average='macro', zero_division=0)
    metrics = {'rows': len(rows), 'seconds': time.perf_counter() - start, 'macro_f1': macro,
               'classification': classification_report(truth, predictions, labels=labels, target_names=names, output_dict=True, zero_division=0),
               'confusion_matrix': confusion_matrix(truth, predictions, labels=labels).tolist()}
    score = macro
    if model.task == 'B':
        topic_truth = np.array([[int(t in r['topics']) for t in range(1, 9)] for r in rows])
        metrics['topics'] = classification_report(topic_truth, topic_predictions, target_names=[str(t) for t in range(1, 9)], output_dict=True, zero_division=0)
        metrics['topic_thresholds'] = [.5] * 8
        score = (macro + f1_score(topic_truth, topic_predictions, average='macro', zero_division=0)) / 2
    metrics['selection_score'] = score
    return metrics


def run(args):
    import numpy as np
    import torch
    from transformers import AutoTokenizer
    from src.rubert_model import PublicationModel

    if not torch.cuda.is_available():
        raise RuntimeError('CUDA unavailable; refusing CPU fallback')
    random.seed(args.seed); np.random.seed(args.seed); torch.manual_seed(args.seed)
    output = Path(args.output)
    if output.exists():
        raise ValueError('output exists; refuse overwriting a run')
    manifest, splits = load_dataset(args.dataset, args.task)
    output.mkdir(parents=True)
    config = vars(args).copy()
    config.update({'checkpoint': manifest['checkpoint'], 'revision': manifest['revision'],
                   'precision': 'fp32', 'topic_thresholds': [.5] * 8,
                   'region_encoding': 'text pair, region first, publication second',
                   'assessments': ASSESSMENTS, 'topic_ids': list(range(1, 9)),
                   'dataset_manifest_sha256': hashlib.sha256((Path(args.dataset) / 'manifest.json').read_bytes()).hexdigest(),
                   'label_status': manifest['status'], 'task_counts': {s: len(r) for s, r in splits.items()}})
    write_json(output / 'run_config.json', config)
    started = time.perf_counter()
    tokenizer = AutoTokenizer.from_pretrained(manifest['checkpoint'], revision=manifest['revision'], trust_remote_code=False)
    model = PublicationModel.pretrained(manifest['checkpoint'], manifest['revision'], args.task).to('cuda')
    model.encoder.gradient_checkpointing_enable(gradient_checkpointing_kwargs={'use_reentrant': False})
    device = torch.device('cuda')
    optimizer = torch.optim.AdamW(model.parameters(), lr=args.learning_rate, weight_decay=.01, foreach=False)
    train = splits['train']; encoded = encode_rows(tokenizer, train, args.max_length)
    loaded_seconds = time.perf_counter() - started
    # Length statistics include input texts only, not test outcomes or tuning.
    lengths = tokenizer([r['source_region'] for r in train], [r['text'] for r in train], truncation=False, padding=False, verbose=False)['input_ids']
    stats = {'train_rows': len(train), 'over_limit_rows': sum(len(v) > args.max_length for v in lengths),
             'p50_tokens': float(np.percentile([len(v) for v in lengths], 50)),
             'p95_tokens': float(np.percentile([len(v) for v in lengths], 95)),
             'max_tokens': max(map(len, lengths)), 'policy': 'truncate publication tail only; do not silently call full-text coverage'}
    write_json(output / 'length_stats.json', stats)
    del lengths

    def update(batches, fixed=False):
        model.train(); optimizer.zero_grad(set_to_none=True)
        count = sum(map(len, batches)); losses = []
        for indices in batches:
            inputs, targets = pack(tokenizer, encoded, train, indices, device, args.max_length, fixed)
            logits = model(**inputs)
            loss = model.loss(logits, *targets)
            if not torch.isfinite(loss):
                raise RuntimeError('nonfinite loss')
            (loss * len(indices) / count).backward()
            losses.append(float(loss.detach()))
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0, error_if_nonfinite=True)
        optimizer.step()
        return statistics.mean(losses)

    if args.command == 'benchmark':
        rng = random.Random(args.seed)
        batches = [[rng.randrange(len(train)) for _ in range(args.batch_size)] for _ in range(args.accumulation)]
        update(batches, fixed=True)  # warmup includes allocation of Adam moments
        torch.cuda.synchronize(); torch.cuda.reset_peak_memory_stats()
        timings = []; losses = []
        for _ in range(args.updates):
            torch.cuda.synchronize(); t = time.perf_counter()
            losses.append(update(batches, fixed=True))
            torch.cuda.synchronize(); timings.append(time.perf_counter() - t)
        model.eval()
        with torch.inference_mode():
            inputs, _ = pack(tokenizer, encoded, train, batches[0], device, args.max_length, True)
            expected = {k: v.cpu() for k, v in model(**inputs).items()}
        model.save(output / 'roundtrip', tokenizer, config)
        # Reload on CPU to avoid holding two full-size networks in 6 GB VRAM.
        restored = PublicationModel.load(output / 'roundtrip').eval()
        with torch.inference_mode():
            actual = restored(**{k: v.cpu() for k, v in inputs.items()})
        # CPU/CUDA numeric differences need a tolerance, not byte equality.
        for key in expected:
            torch.testing.assert_close(expected[key], actual[key], rtol=1e-3, atol=1e-3)
        del restored; gc.collect()
        with torch.inference_mode():
            torch.cuda.synchronize(); t = time.perf_counter()
            for _ in range(args.updates):
                model(**inputs)
            torch.cuda.synchronize(); inference_seconds = (time.perf_counter() - t) / (args.updates * args.batch_size)
        effective = args.batch_size * args.accumulation
        updates_epoch = math.ceil(len(train) / effective)
        epoch_seconds = statistics.mean(timings) * updates_epoch + inference_seconds * len(splits['validation'])
        result = {'status': 'passed', 'task': args.task, 'gpu': torch.cuda.get_device_name(0),
                  'parameter_count': sum(p.numel() for p in model.parameters()),
                  'max_length': args.max_length, 'microbatch': args.batch_size, 'accumulation': args.accumulation,
                  'padding': 'fixed maximum length (conservative vs dynamic training padding)',
                  'gradient_checkpointing': True, 'precision': 'fp32', 'optimizer_updates_measured': args.updates,
                  'seconds_per_update': timings, 'mean_seconds_per_update': statistics.mean(timings),
                  'seconds_per_example_inference': inference_seconds,
                  'peak_allocated_mib': round(torch.cuda.max_memory_allocated() / 2**20, 2),
                  'peak_reserved_mib': round(torch.cuda.max_memory_reserved() / 2**20, 2),
                  'losses': losses, 'roundtrip_passed': True, 'load_and_tokenize_seconds': loaded_seconds,
                  'estimated_seconds_per_epoch_with_validation': epoch_seconds,
                  'estimated_seconds_three_epochs': epoch_seconds * 3,
                  'estimate_excludes_checkpoint_io_and_first_download': True,
                  'test_metrics_computed': False, 'full_training_started': False}
        write_json(output / 'benchmark.json', result)
        print(json.dumps(result, ensure_ascii=False, indent=2), flush=True)
        return

    validation = splits['validation']
    val_encoded = encode_rows(tokenizer, validation, args.max_length)
    updates_epoch = math.ceil(len(train) / (args.batch_size * args.accumulation))
    total_updates = args.epochs * updates_epoch; completed = 0; best = -1
    for epoch in range(1, args.epochs + 1):
        indices = list(range(len(train))); random.Random(args.seed + epoch).shuffle(indices)
        microbatches = [indices[i:i + args.batch_size] for i in range(0, len(indices), args.batch_size)]
        t = time.perf_counter(); losses = []
        for offset in range(0, len(microbatches), args.accumulation):
            warmup = max(1, round(.1 * total_updates))
            factor = min((completed + 1) / warmup, max(0., (total_updates - completed) / max(total_updates - warmup, 1)))
            for group in optimizer.param_groups:
                group['lr'] = args.learning_rate * factor
            losses.append(update(microbatches[offset:offset + args.accumulation]))
            completed += 1
            if completed % 10 == 0:
                print(json.dumps({'epoch': epoch, 'update': completed, 'total_updates': total_updates, 'loss': losses[-1]}), flush=True)
        torch.cuda.synchronize()
        metrics = evaluate(model, tokenizer, val_encoded, validation, args.batch_size, device, args.max_length)
        metrics.update({'epoch': epoch, 'train_loss': statistics.mean(losses), 'epoch_seconds': time.perf_counter() - t})
        write_json(output / f'validation_epoch_{epoch}.json', metrics)
        if metrics['selection_score'] > best:
            best = metrics['selection_score']
            model.save(output / f'checkpoint_epoch_{epoch}', tokenizer, {**config, 'epoch': epoch, 'validation': metrics})
            write_json(output / 'best_checkpoint.json', {'path': f'checkpoint_epoch_{epoch}', 'score': best, 'epoch': epoch})
        print(json.dumps(metrics, ensure_ascii=False), flush=True)
    write_json(output / 'completed.json', {'epochs': args.epochs, 'optimizer_updates': completed, 'test_metrics_computed': False})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['benchmark', 'train'])
    parser.add_argument('--dataset', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--task', choices=['A', 'B'], required=True)
    parser.add_argument('--max-length', type=int, choices=[128, 256, 512], default=256)
    parser.add_argument('--batch-size', type=int, default=2)
    parser.add_argument('--accumulation', type=int, default=8)
    parser.add_argument('--epochs', type=int, default=3)
    parser.add_argument('--updates', type=int, default=3)
    parser.add_argument('--learning-rate', type=float, default=2e-5)
    parser.add_argument('--seed', type=int, default=20261107)
    args = parser.parse_args()
    if min(args.batch_size, args.accumulation, args.epochs, args.updates) < 1 or not math.isfinite(args.learning_rate) or args.learning_rate <= 0:
        parser.error('sizes/epochs/updates/learning-rate must be positive and finite')
    run(args)


if __name__ == '__main__':
    main()
