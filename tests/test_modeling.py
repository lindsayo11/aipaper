import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from ai_trends.common import read_json, read_jsonl, write_jsonl
from ai_trends.modeling import (masked_mean, model_corpus, paper_text,
                                run_model, _token_chunks)


class FakeTokenizer:
    def encode(self, text, add_special_tokens=False):
        class Enc: pass
        obj = Enc()
        obj.ids = list(range(1, int(text)+1))
        return obj
    def token_to_id(self, token):
        return {'[CLS]': 101, '[SEP]': 102}[token]


class ModelContractTests(unittest.TestCase):
    def test_research_population_excludes_unknown_and_missing(self):
        good = {'paper_id': 'b', 'track': 'main', 'decision': 'accepted',
                'title': 'Title', 'abstract': 'Real abstract', 'year': 2026}
        self.assertEqual([p['paper_id'] for p in model_corpus([
            good, {**good, 'paper_id': 'u', 'decision': 'unknown'},
            {**good, 'paper_id': 'w', 'track': 'workshop'},
            {**good, 'paper_id': 'n', 'abstract': ''}])], ['b'])
        self.assertEqual(paper_text(good), 'Title\nReal abstract')
        self.assertNotIn('2026', paper_text(good))

    def test_long_document_content_never_truncated(self):
        chunks = _token_chunks(FakeTokenizer(), '11', 6)
        self.assertEqual([t for chunk,_ in chunks for t in chunk[1:-1]], list(range(1,12)))
        self.assertEqual([weight for _,weight in chunks], [4,4,3])

    def test_padding_is_excluded_from_pooling(self):
        tokens = np.array([[[1.,3.], [3.,5.], [999.,999.]]])
        result = masked_mean(tokens, [[1,1,0]])
        np.testing.assert_allclose(result, [[2.,4.]])

    def test_already_initialized_ort_fails_closed(self):
        code = '''import sys,types
sys.modules['onnxruntime']=types.ModuleType('onnxruntime')
from ai_trends.modeling import safe_onnxruntime
try: safe_onnxruntime()
except RuntimeError as e:
 assert 'new process' in str(e)
else: raise AssertionError('unsafe existing import was accepted')
'''
        p = subprocess.run([sys.executable, '-c', code], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)

    def test_real_lsa_assigns_each_eligible_id_exactly_once(self):
        domains = [('graph', 'nodes edges networks message passing graph neural network topology'),
                   ('diffusion', 'image denoising diffusion generation visual synthesis noise pixels'),
                   ('language', 'language reasoning token text decoder prompt instruction transformer')]
        rows = []
        for topic, words in domains:
            for j in range(6):
                rows.append({'paper_id': f'{topic}-{j}', 'track': 'main', 'decision': 'accepted',
                             'title': f'{topic} study {j}', 'abstract': words + ' ' + words,
                             'source_url': 'https://example.org/paper'})
        rows.append({**rows[0], 'paper_id': 'unknown', 'track': 'unknown'})
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            write_jsonl(root / 'processed/papers.jsonl', rows)
            cfg = {'model': {'topics': 3, 'min_df': 2, 'svd_components': 8, 'seed': 42,
                             'max_features': 300, 'outlier_quantile': .05}}
            manifest = run_model(cfg, root, 'lsa')
            assigned = read_jsonl(root / 'models/lsa/assignments.jsonl')
            self.assertEqual(manifest['status'], 'completed')
            self.assertEqual({r['paper_id'] for r in assigned}, {r['paper_id'] for r in rows[:-1]})
            self.assertEqual(len(assigned),18)
            self.assertEqual(sum(t['size'] for t in read_json(root / 'models/lsa/topics.json')),18)
            self.assertTrue(np.isfinite(np.load(root / 'models/lsa/embeddings.npy')).all())
            self.assertTrue(all(isinstance(i, int) for i in read_json(root / 'models/lsa/tfidf_vocabulary.json').values()))
            # An immutable completed run cannot be silently replaced by new parameters.
            before = (root / 'models/lsa/manifest.json').read_bytes()
            changed = {**cfg, 'model': {**cfg['model'], 'seed': 7}}
            with self.assertRaisesRegex(ValueError, 'configuration changed'):
                run_model(changed, root, 'lsa')
            self.assertEqual((root / 'models/lsa/manifest.json').read_bytes(), before)


if __name__ == '__main__':
    unittest.main()
