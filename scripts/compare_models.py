#!/usr/bin/env python3
"""Compare cluster partitions on exact paper-ID intersection, not topic numbers."""
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from sklearn.metrics import adjusted_mutual_info_score, adjusted_rand_score
from ai_trends.common import read_json, read_jsonl, utcnow, write_csv, write_json


def compare(output):
    output = Path(output)
    a = {p['paper_id']: p['topic_id'] for p in read_jsonl(output / 'models/lsa/assignments.jsonl')}
    b = {p['paper_id']: p['topic_id'] for p in read_jsonl(output / 'models/onnx/assignments.jsonl')}
    common = sorted(a.keys() & b.keys())
    if not common:
        raise ValueError('No intersecting paper IDs; comparison cannot run')
    labels_a, labels_b = [a[i] for i in common], [b[i] for i in common]
    ma = read_json(output / 'models/lsa/manifest.json', {})
    mb = read_json(output / 'models/onnx/manifest.json', {})
    if ma.get('status') != 'completed' or mb.get('status') != 'completed':
        raise ValueError('Both actual model runs must have completed')
    result = {'created_at': utcnow(), 'lsa_papers': len(a), 'onnx_papers': len(b),
              'intersection_papers': len(common), 'lsa_only': len(a.keys()-b.keys()),
              'onnx_only': len(b.keys()-a.keys()), 'same_corpus': a.keys() == b.keys(),
              'same_text_fingerprint': ma.get('corpus_fingerprint') == mb.get('corpus_fingerprint'),
              'ari': float(adjusted_rand_score(labels_a, labels_b)),
              'ami': float(adjusted_mutual_info_score(labels_a, labels_b)),
              'interpretation': 'Partition agreement on identical paper IDs. Not topic quality, accuracy, or evidence of optimal K.'}
    root = output / 'model_comparison'
    root.mkdir(parents=True, exist_ok=True)
    write_json(root / 'comparison.json', result)
    write_csv(root / 'comparison.csv', [result])
    write_csv(root / 'paper_intersection.csv', [{'paper_id': i, 'lsa_topic_id': a[i], 'onnx_topic_id': b[i]} for i in common])
    # Contingency table provides an auditable many-to-many topic correspondence.
    from collections import Counter
    counts = Counter(zip(labels_a, labels_b))
    write_csv(root / 'topic_contingency.csv', [{'lsa_topic_id': x, 'onnx_topic_id': y, 'papers': n}
                                               for (x,y),n in sorted(counts.items())])
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='output')
    args = parser.parse_args()
    print(compare(args.output))
