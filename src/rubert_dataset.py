"""Offline preparation of a provisional, group-split publication dataset (stdlib only)."""
import argparse
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from pathlib import Path

ASSESSMENTS = ['positive', 'negative', 'mixed', 'unassessable']
CHECKPOINT = 'DeepPavlov/rubert-base-cased'
REVISION = '4036cab694767a299f2b9e6492909664d9414229'


def digest(value):
    return hashlib.sha256(value.encode('utf-8')).hexdigest()


def read_jsonl(path):
    return [json.loads(line) for line in Path(path).read_text(encoding='utf-8').splitlines() if line.strip()]


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def shingles(text):
    text = re.sub(r'https?://\S+|www\.\S+', ' ', text.casefold())
    words = re.findall(r'[\w]+', text, flags=re.UNICODE)
    # Avoid grouping short generic notices based on a few common words.
    if len(words) < 20:
        return set()
    return {' '.join(words[i:i + 5]) for i in range(len(words) - 4)}


def group_texts(rows, threshold=0.82):
    """Exact families + transitive Jaccard graph, complete prefix-filter candidates.

    Global frequency order makes the prefix-filter lossless for the specified
    shingle/Jaccard definition, not for all semantic paraphrases.
    """
    if not 0 < threshold <= 1:
        raise ValueError('threshold must be in (0, 1]')
    ids = [r['id'] for r in rows]
    if len(set(ids)) != len(ids):
        raise ValueError('duplicate input IDs')
    parent = {i: i for i in ids}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a, b):
        a, b = find(a), find(b)
        if a != b:
            parent[max(a, b)] = min(a, b)

    exact = {}; edges = []; sets = {}
    for r in rows:
        key = ' '.join(r['text'].casefold().split())
        if key in exact:
            union(r['id'], exact[key])
            edges.append({'a': exact[key], 'b': r['id'], 'kind': 'exact', 'score': 1.0})
        else:
            exact[key] = r['id']
        sets[r['id']] = shingles(r['text'])
    freq = Counter(s for values in sets.values() for s in values)
    index = defaultdict(list)
    for i in sorted(ids):
        values = sets[i]
        if not values:
            continue
        ordered = sorted(values, key=lambda s: (freq[s], s))
        prefix = ordered[:len(values) - math.ceil(threshold * len(values)) + 1]
        candidates = {j for s in prefix for j in index[s]}
        for j in sorted(candidates):
            other = sets[j]
            if min(len(values), len(other)) < threshold * max(len(values), len(other)):
                continue
            intersection = len(values & other)
            score = intersection / (len(values) + len(other) - intersection)
            if score >= threshold:
                union(i, j)
                edges.append({'a': j, 'b': i, 'kind': 'word5_jaccard', 'score': round(score, 6)})
        for s in prefix:
            index[s].append(i)
    members = defaultdict(list)
    for i in ids:
        members[find(i)].append(i)
    mapping = {}
    for values in members.values():
        group = 'near:' + digest('\n'.join(sorted(values)))[:24]
        for i in values:
            mapping[i] = group
    return mapping, edges


def features(row):
    values = ['total', 'include:' + str(row['include']), 'region:' + row['source_region'],
              'source:' + str(row['group_id'])]
    if row['include']:
        values += ['assessment:' + row['assessment']]
        values += ['topic:' + str(t) for t in row['topics']]
    return values


def split_groups(rows, seed=20261107, forced_train=()):
    ratios = {'train': .8, 'validation': .1, 'test': .1}
    groups = defaultdict(list)
    for r in rows:
        groups[r['near_group_id']].append(r)
    vectors = {g: Counter(f for r in values for f in features(r)) for g, values in groups.items()}
    totals = Counter(f for r in rows for f in features(r))
    counts = {split: Counter() for split in ratios}
    assignment = {}
    forced = set(forced_train)
    for g in sorted(forced & set(groups)):
        assignment[g] = 'train'; counts['train'].update(vectors[g])
    order = sorted(set(groups) - forced, key=lambda g: (-len(groups[g]), digest(f'{seed}:{g}')))
    for g in order:
        vec = vectors[g]
        def cost(split):
            # Incremental squared deviation; balances labels/topics/geography,
            # while groups, not individual records, remain indivisible.
            return sum(((counts[split][f] + n - totals[f] * ratios[split]) ** 2
                        - (counts[split][f] - totals[f] * ratios[split]) ** 2)
                       / max(totals[f] * ratios[split], 1) for f, n in vec.items())
        split = min(ratios, key=lambda s: (cost(s), s))
        assignment[g] = split; counts[split].update(vec)
    return {r['id']: assignment[r['near_group_id']] for r in rows}


def prepare(base, output, seed=20261107):
    base, output = Path(base), Path(output)
    if output.exists():
        raise ValueError('output already exists; do not overwrite a frozen dataset')
    posts = []; labels = {}; provenance = {}; hashes = {}
    for name, selection in [('starter4000_seed20261106', 'selection4000.jsonl'),
                            ('night6000_seed20261107', 'selection.jsonl')]:
        d = base / name
        paths = [d / selection, d / 'labeling_luna_low_028r2/predictions.jsonl']
        for p in paths:
            hashes[str(p.relative_to(base))] = hashlib.sha256(p.read_bytes()).hexdigest()
        posts.extend(read_jsonl(paths[0]))
        for r in read_jsonl(paths[1]):
            if r['id'] in labels:
                raise ValueError('duplicate label ID')
            batch = r.pop('batch'); labels[r['id']] = r
            provenance[r['id']] = {'run': name, 'batch': batch}
    if len({r['id'] for r in posts}) != len(posts):
        raise ValueError('duplicate post IDs')
    if not set(labels) <= {r['id'] for r in posts}:
        raise ValueError('unknown label IDs')
    # Include earlier Omsk development inputs in the duplicate graph only;
    # never add them to the PFO training labels.
    development = []
    for number, p in enumerate([
        base.parents[1] / 'omsk/pilot2019/annotation-pilot-200.jsonl',
        base.parents[1] / 'omsk/pilot2019/annotation-development/benchmark1000_luna_low_028r2/selection.jsonl',
    ]):
        if not p.exists():
            raise ValueError(f'missing development-overlap input: {p}')
        hashes['development:' + str(number)] = hashlib.sha256(p.read_bytes()).hexdigest()
        development.extend({'id': f'DEV{number}:{i}', 'text': r['text']} for i, r in enumerate(read_jsonl(p)))
    mapping, edges = group_texts(posts + development)
    reviewed_path = base / 'quality_review_20261107/review_inputs.jsonl'
    reviewed = {r['id'] for r in read_jsonl(reviewed_path)}
    hashes[str(reviewed_path.relative_to(base))] = hashlib.sha256(reviewed_path.read_bytes()).hexdigest()
    forced = {mapping[i] for i in reviewed} | {mapping[r['id']] for r in development}
    rows = []
    for p in posts:
        if p['id'] not in labels:
            continue
        r = labels[p['id']]
        if type(r['include']) is not bool:
            raise ValueError('invalid inclusion')
        if r['include'] and (r['assessment'] not in ASSESSMENTS or not r['topics']):
            raise ValueError('invalid included label')
        if not r['include'] and (r['assessment'] is not None or r['topics']):
            raise ValueError('invalid excluded label')
        rows.append({
            'id': p['id'], 'text': p['text'], 'source_region': p['source_region'],
            'group_id': p['group_id'], 'post_id': p['post_id'], 'date': p['date'],
            'exact_family_id': p['exact_family_id'], 'near_group_id': mapping[p['id']],
            'include': r['include'], 'assessment': r['assessment'], 'topics': r['topics'],
            'label_origin': 'original_accepted_machine', 'provenance': provenance[p['id']],
        })
    splits = split_groups(rows, seed, forced)
    for r in rows:
        r['split'] = splits[r['id']]
    output.mkdir(parents=True)
    for split in ('train', 'validation', 'test'):
        subset = [r for r in rows if r['split'] == split]
        (output / (split + '.jsonl')).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in subset), encoding='utf-8')
    write_json(output / 'duplicate_edges.json', edges)
    write_json(output / 'group_membership.json', mapping)
    support = {}
    for split in ('train', 'validation', 'test'):
        subset = [r for r in rows if r['split'] == split]
        support[split] = {
            'A': len(subset), 'B': sum(r['include'] for r in subset),
            'assessment': dict(Counter(r['assessment'] for r in subset if r['include'])),
            'topics': dict(Counter(t for r in subset for t in r['topics'])),
            'regions': dict(Counter(r['source_region'] for r in subset)),
        }
    grouped = defaultdict(list)
    for r in rows:
        grouped[r['near_group_id']].append(r)
    conflicts = [g for g, values in grouped.items() if len({(r['include'], r['assessment'], tuple(sorted(r['topics']))) for r in values}) > 1]
    manifest = {
        'status': 'provisional_machine_labels_not_human_gold', 'seed': seed,
        'checkpoint': CHECKPOINT, 'revision': REVISION, 'assessments': ASSESSMENTS,
        'topics': list(range(1, 9)), 'input_format': 'tokenizer pair: source_region, full publication text',
        'rows': len(rows), 'support': support, 'ratios_target': [.8, .1, .1],
        'reviewed_and_omsk_overlap_groups_train_only': True,
        'forced_train_groups_present': len(forced & set(grouped)),
        'grouping': 'exact normalized + transitive 5-word-shingle Jaccard >=0.82 after URL removal; min20 words',
        'grouping_scope': 'all10000 selected PFO inputs plus previous Omsk development inputs',
        'semantic_paraphrases_not_guaranteed': True,
        'group_count': len(grouped), 'largest_group': max(map(len, grouped.values())),
        'label_conflict_groups': conflicts, 'conflicting_labels_preserved': True,
        'corrections_applied': False, 'recovery_candidates_added': False,
        'input_sha256': hashes,
        'artifact_sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in output.iterdir() if p.is_file()},
    }
    for values in grouped.values():
        assert len({r['split'] for r in values}) == 1
    write_json(output / 'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(prepare(args.base, args.output), ensure_ascii=False, indent=2))
