"""Two actually executed shared-space models over the identical eligible corpus.

No year, decision, review score, venue, author name or keyword enters a vector.
The semantic backend deliberately imports ONNX Runtime only inside a guarded
function after disabling telemetry. It never silently substitutes another model.
"""
from __future__ import annotations

import importlib.metadata
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import time
from urllib.request import Request, urlopen

import numpy as np
from sklearn.cluster import KMeans, MiniBatchKMeans
from sklearn.decomposition import TruncatedSVD
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS, TfidfVectorizer
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import normalize
from threadpoolctl import threadpool_limits

from .common import (atomic_write, read_json, read_jsonl, sha256, utcnow,
                     write_csv, write_json, write_jsonl)


def model_corpus(papers):
    """The declared accepted-main, real-title-and-abstract research population."""
    selected = [p for p in papers if p.get('track') == 'main'
                and p.get('decision') == 'accepted'
                and str(p.get('title') or '').strip()
                and str(p.get('abstract') or '').strip()]
    selected.sort(key=lambda p: p['paper_id'])
    ids = [p['paper_id'] for p in selected]
    if len(set(ids)) != len(ids):
        raise ValueError('Duplicate paper IDs in model corpus')
    return selected


def paper_text(paper):
    return paper['title'].strip() + '\n' + paper['abstract'].strip()


def fingerprint(value):
    return sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                             separators=(',', ':')))


def _versions():
    versions = {}
    for name in ['numpy', 'scipy', 'scikit-learn', 'onnxruntime', 'tokenizers']:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def safe_onnxruntime():
    """Fail closed if the import's initialization history cannot be established."""
    previous = sys.modules.get('onnxruntime')
    if previous is not None and not getattr(previous, '_ai_trends_safe_import', False):
        raise RuntimeError('ONNX Runtime was already initialized without this telemetry guard; start a new process with ORT_DISABLE_TELEMETRY=1')
    os.environ['ORT_DISABLE_TELEMETRY'] = '1'
    import onnxruntime as ort
    ort._ai_trends_safe_import = True
    ort.disable_telemetry_events()
    return ort


def prepare_semantic_assets(config, output):
    cfg = config.get('semantic', {})
    revision = cfg.get('revision', '')
    if not re.fullmatch(r'[0-9a-f]{40}', revision):
        raise ValueError('Semantic model requires an exact 40-character commit revision')
    model_id = cfg.get('model_id', 'sentence-transformers/all-MiniLM-L6-v2')
    root = Path(output) / 'model_assets' / revision
    root.mkdir(parents=True, exist_ok=True)
    assets = {}
    for role, remote in [('tokenizer', cfg.get('tokenizer_file', 'tokenizer.json')),
                         ('onnx', cfg.get('onnx_file', 'onnx/model_quint8_avx2.onnx'))]:
        if '..' in Path(remote).parts or Path(remote).is_absolute():
            raise ValueError('Invalid model asset path')
        local = root / Path(remote).name
        mp = local.with_suffix(local.suffix + '.metadata.json')
        url = f'https://huggingface.co/{model_id}/resolve/{revision}/{remote}'
        meta = read_json(mp, {})
        if local.exists():
            if meta.get('url') != url or sha256(local) != meta.get('sha256'):
                raise ValueError('Existing semantic asset lacks a matching audited hash: ' + str(local))
        else:
            started = utcnow()
            req = Request(url, headers={'User-Agent': 'AuditableAITrends/1.0'})
            with urlopen(req, timeout=120) as response:
                body = response.read()
                if not body or response.status != 200:
                    raise RuntimeError('Semantic model download failed')
                # Signed redirect parameters are deliberately never persisted.
                meta = {'url': url, 'collected_at': started, 'size_bytes': len(body),
                        'sha256': sha256(body), 'model_id': model_id,
                        'revision': revision, 'file': remote}
            atomic_write(local, body)
            write_json(mp, meta)
        assets[role] = {**meta, 'local_path': str(local)}
    write_json(root / 'assets_manifest.json', assets)
    return assets


def _token_chunks(tokenizer, text, max_tokens):
    """No title/abstract truncation: all content tokens occur in exactly one chunk."""
    if max_tokens < 4 or max_tokens > 512:
        raise ValueError('MiniLM chunk max_tokens must be in [4, 512]')
    ids = tokenizer.encode(text, add_special_tokens=False).ids
    cls, sep = tokenizer.token_to_id('[CLS]'), tokenizer.token_to_id('[SEP]')
    if cls is None or sep is None:
        raise ValueError('Tokenizer does not expose expected BERT special tokens')
    width = max_tokens - 2
    if not ids:
        return [([cls, sep], 1)]
    return [([cls] + ids[i:i+width] + [sep], len(ids[i:i+width]))
            for i in range(0, len(ids), width)]


def masked_mean(token_embeddings, attention_mask):
    weights = np.asarray(attention_mask, dtype=np.float32)[..., None]
    return ((np.asarray(token_embeddings, dtype=np.float32) * weights).sum(axis=1)
            / np.maximum(weights.sum(axis=1), 1))


def _semantic_vectors(texts, text_hashes, config, output, model_dir, assets):
    from tokenizers import Tokenizer
    cfg = config.get('semantic', {})
    ort = safe_onnxruntime()
    tokenizer = Tokenizer.from_file(assets['tokenizer']['local_path'])
    tokenizer.no_truncation()
    tokenizer.no_padding()
    threads = int(cfg.get('threads', 4))
    options = ort.SessionOptions()
    options.intra_op_num_threads = threads
    options.inter_op_num_threads = 1
    options.log_severity_level = 3
    session = ort.InferenceSession(assets['onnx']['local_path'], sess_options=options,
                                   providers=['CPUExecutionProvider'])
    input_names = {x.name for x in session.get_inputs()}
    encoder = {'model_id': cfg.get('model_id'), 'revision': cfg.get('revision'),
               'weight_sha256': assets['onnx']['sha256'],
               'tokenizer_sha256': assets['tokenizer']['sha256'],
               'max_tokens': int(cfg.get('max_tokens', 256)),
               'pooling': 'attention-mask mean including special tokens; content-token-weighted chunk average then L2',
               'implementation': 'all-content-nonoverlap-chunks-v1'}
    enc_hash = fingerprint(encoder)
    cache_root = Path(output) / 'cache'
    cache_root.mkdir(parents=True, exist_ok=True)
    db_path = cache_root / ('minilm-' + enc_hash[:20] + '.sqlite')
    conn = sqlite3.connect(db_path)
    conn.execute('CREATE TABLE IF NOT EXISTS embeddings (fingerprint TEXT PRIMARY KEY, dim INTEGER NOT NULL, vector BLOB NOT NULL)')
    vectors = [None] * len(texts)
    remaining, sums, weights, tasks = {}, {}, {}, []
    hits = 0
    for i, (text, text_hash) in enumerate(zip(texts, text_hashes)):
        row = conn.execute('SELECT dim,vector FROM embeddings WHERE fingerprint=?', (text_hash,)).fetchone()
        if row:
            v = np.frombuffer(row[1], dtype=np.float32).copy()
            if len(v) != row[0] or not np.isfinite(v).all():
                raise ValueError('Embedding cache corruption')
            vectors[i] = v
            hits += 1
        else:
            chunks = _token_chunks(tokenizer, text, encoder['max_tokens'])
            remaining[i] = len(chunks)
            weights[i] = 0
            for chunk, weight in chunks:
                tasks.append((i, chunk, weight))
    batch_size = max(1, int(cfg.get('batch_size', 32)))
    pad = tokenizer.token_to_id('[PAD]') or 0
    started, done, total_chunks = time.monotonic(), hits, len(tasks)
    checkpoint = {'started_at': utcnow(), 'papers_total': len(texts), 'papers_completed': hits,
                  'cache_hits': hits, 'chunks_total': total_chunks, 'chunks_completed': 0,
                  'encoder_fingerprint': enc_hash, 'status': 'running'}
    write_json(model_dir / 'encoding_checkpoint.json', checkpoint)
    try:
        for start in range(0, total_chunks, batch_size):
            batch = tasks[start:start+batch_size]
            width = max(len(task[1]) for task in batch)
            ids = np.full((len(batch), width), pad, dtype=np.int64)
            mask = np.zeros_like(ids)
            for j, (_, chunk, _) in enumerate(batch):
                ids[j, :len(chunk)] = chunk
                mask[j, :len(chunk)] = 1
            feed = {'input_ids': ids, 'attention_mask': mask}
            if 'token_type_ids' in input_names:
                feed['token_type_ids'] = np.zeros_like(ids)
            outputs = session.run(None, {k: v for k, v in feed.items() if k in input_names})
            token_output = outputs[0]
            if token_output.ndim != 3:
                raise RuntimeError('Expected token-level MiniLM output for explicit mask pooling')
            pooled = masked_mean(token_output, mask)
            for j, (i, _, weight) in enumerate(batch):
                if i not in sums:
                    sums[i] = np.zeros(pooled.shape[1], dtype=np.float64)
                sums[i] += pooled[j] * weight
                weights[i] += weight
                remaining[i] -= 1
                if remaining[i] == 0:
                    v = np.asarray(sums.pop(i) / weights.pop(i), dtype=np.float32)
                    norm = np.linalg.norm(v)
                    if not np.isfinite(v).all() or norm < 1e-12:
                        raise ValueError('Invalid semantic vector')
                    v /= norm
                    vectors[i] = v
                    conn.execute('INSERT OR REPLACE INTO embeddings VALUES (?,?,?)',
                                 (text_hashes[i], len(v), v.tobytes()))
                    done += 1
            # Every inference batch is durable; progress logging is less frequent.
            conn.commit()
            checkpoint.update(papers_completed=done, chunks_completed=min(start+batch_size, total_chunks),
                              elapsed_seconds=round(time.monotonic()-started, 3))
            write_json(model_dir / 'encoding_checkpoint.json', checkpoint)
            if start % (batch_size * 8) == 0 or start + batch_size >= total_chunks:
                print(json.dumps({'stage': 'semantic_encoding', **checkpoint}), flush=True)
        conn.commit()
        result = np.vstack(vectors).astype(np.float32)
        checkpoint.update(status='completed', papers_completed=len(texts))
        write_json(model_dir / 'encoding_checkpoint.json', checkpoint)
    except BaseException as exc:
        conn.commit()
        checkpoint.update(status='failed', error=repr(exc))
        write_json(model_dir / 'encoding_checkpoint.json', checkpoint)
        raise
    finally:
        conn.close()
    return result, {'encoder': encoder, 'encoder_fingerprint': enc_hash,
                    'cache_hits': hits, 'cache_misses': len(texts)-hits,
                    'cache_path': str(db_path), 'chunks_encoded': total_chunks,
                    'telemetry': {'environment_before_import': 'ORT_DISABLE_TELEMETRY=1',
                                  'api_disable_called': True}}


def _topic_outputs(corpus, labels, similarities, outliers, tfidf, terms, k):
    topics = []
    for topic_id in range(k):
        members = np.where(labels == topic_id)[0]
        if not len(members):
            topics.append({'topic_id': topic_id, 'size': 0, 'keywords': [], 'representatives': []})
            continue
        # Mean per-paper TF-IDF highlights words/phrases prevalent in this cluster.
        average = np.asarray(tfidf[members].mean(axis=0)).ravel()
        order = average.argsort()[::-1]
        words = [str(terms[j]) for j in order if average[j] > 0][:12]
        top = sorted(members, key=lambda j: (-similarities[j], corpus[j]['paper_id']))[:5]
        representatives = [{'paper_id': corpus[j]['paper_id'], 'title': corpus[j]['title'],
                            'source_url': corpus[j].get('source_url', ''),
                            'similarity': float(similarities[j]),
                            'abstract': corpus[j]['abstract']}
                           for j in top]
        topics.append({'topic_id': topic_id, 'size': int(len(members)), 'keywords': words,
                       'outliers': int(outliers[members].sum()),
                       'representatives': representatives,
                       'label_status': 'automatic_keywords_need_human_review'})
    return topics


def _plot_topics(topics, target):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    topics = sorted(topics, key=lambda x: x['size'], reverse=True)
    fig, ax = plt.subplots(figsize=(13, 7))
    labels = [str(x['topic_id']) + ': ' + ', '.join(x['keywords'][:2]) for x in topics]
    ax.bar(range(len(topics)), [x['size'] for x in topics], color='#256d85')
    ax.set_xticks(range(len(topics)), labels, rotation=75, ha='right', fontsize=7)
    ax.set_ylabel('Observed accepted main-track papers with abstracts')
    ax.set_title('Shared topic model: all selected venues and years')
    fig.tight_layout()
    fig.savefig(target, dpi=150)
    plt.close(fig)


def run_model(config, output, backend='lsa'):
    """Fit one shared model, emit assignments, vectors, interpretable evidence."""
    if backend not in ('lsa', 'onnx'):
        raise ValueError('Actual implemented backends are lsa and onnx; BERTopic/HDBSCAN is not executed')
    output = Path(output)
    model_dir = output / 'models' / backend
    model_dir.mkdir(parents=True, exist_ok=True)
    paper_path = output / 'processed/papers.jsonl'
    papers = read_jsonl(paper_path)
    corpus = model_corpus(papers)
    if len(corpus) < 3:
        raise ValueError('At least three eligible papers required')
    cfg = config.get('model', {})
    k = int(cfg.get('topics', 50))
    if k < 2 or k >= len(corpus):
        raise ValueError('topics must be >=2 and smaller than eligible corpus size')
    seed = int(cfg.get('seed', 42))
    texts = [paper_text(p) for p in corpus]
    text_hashes = [sha256(t) for t in texts]
    ids = [p['paper_id'] for p in corpus]
    input_fingerprint = fingerprint(list(zip(ids, text_hashes)))
    configuration_fingerprint = fingerprint({'backend': backend, 'model': cfg,
                                             'semantic': config.get('semantic', {}) if backend == 'onnx' else {}})
    started = time.monotonic()
    manifest = {'status': 'running', 'started_at': utcnow(), 'backend': backend,
                'actual_backend': 'TFIDF-SVD-L2-MiniBatchKMeans' if backend == 'lsa' else 'MiniLM-quantized-ONNX-mask-pooling-chunked-L2-KMeans',
                'optional_backends': {'BERTopic': 'not_executed', 'HDBSCAN': 'not_executed'},
                'shared_space': True, 'text_fields': ['title', 'abstract'],
                'corpus_filter': {'track': 'main', 'decision': 'accepted', 'title': 'nonempty', 'abstract': 'nonempty'},
                'input_papers': len(corpus), 'processed_input_sha256': sha256(paper_path),
                'corpus_fingerprint': input_fingerprint, 'paper_id_fingerprint': fingerprint(ids),
                'configuration_fingerprint': configuration_fingerprint,
                'model_parameters': cfg, 'seed': seed, 'versions': _versions(),
                'automatic_labels_need_human_review': True}
    prior = read_json(model_dir / 'manifest.json', {})
    if prior.get('status') == 'completed' and prior.get('corpus_fingerprint') != input_fingerprint:
        raise ValueError('Corpus changed: use a fresh output directory to preserve prior model evidence')
    if prior.get('status') == 'completed' and prior.get('configuration_fingerprint') != configuration_fingerprint:
        raise ValueError('Model configuration changed: use a fresh output directory to preserve prior model evidence')
    write_json(model_dir / 'manifest.json', manifest)
    try:
        write_jsonl(model_dir / 'corpus.jsonl', corpus)
        write_json(model_dir / 'corpus_fingerprints.json', [{'paper_id': i, 'text_sha256': h}
                                                          for i, h in zip(ids, text_hashes)])
        stop = sorted(set(ENGLISH_STOP_WORDS) | {'paper', 'propose', 'proposed', 'approach', 'method',
                                                'methods', 'results', 'model', 'models', 'learning'})
        vectorizer = TfidfVectorizer(ngram_range=(1, 2), min_df=int(cfg.get('min_df', 4)),
                                     max_df=.98, max_features=int(cfg.get('max_features', 60000)),
                                     stop_words=stop, dtype=np.float32,
                                     strip_accents='unicode', sublinear_tf=True)
        tfidf = vectorizer.fit_transform(texts)
        terms = vectorizer.get_feature_names_out()
        write_json(model_dir / 'tfidf_vocabulary.json', {word: int(index) for word, index in vectorizer.vocabulary_.items()})
        np.save(model_dir / 'tfidf_idf.npy', vectorizer.idf_)
        info = {}
        with threadpool_limits(limits=int(config.get('semantic', {}).get('threads', 4))):
            if backend == 'lsa':
                components = min(int(cfg.get('svd_components', 128)), tfidf.shape[1]-1, tfidf.shape[0]-1)
                if components < 2:
                    raise ValueError('Insufficient TF-IDF features for SVD')
                svd = TruncatedSVD(n_components=components, random_state=seed, n_iter=7)
                vectors = normalize(svd.fit_transform(tfidf)).astype(np.float32)
                np.savez_compressed(model_dir / 'svd.npz', components=svd.components_,
                                    explained_variance_ratio=svd.explained_variance_ratio_)
                estimator = MiniBatchKMeans(n_clusters=k, random_state=seed, n_init=10,
                                            batch_size=1024, max_iter=200, reassignment_ratio=.01)
                info = {'encoder': 'word-and-bigram-TFIDF-SVD-L2',
                        'encoder_fingerprint': fingerprint({'corpus': input_fingerprint, 'vocabulary': terms.tolist(), 'parameters': cfg}),
                        'svd_components': components, 'explained_variance_ratio_sum': float(svd.explained_variance_ratio_.sum()),
                        'cache_hits': 0, 'cache_misses': len(corpus),
                        'cache_note': 'LSA basis is corpus-dependent and refitted jointly; semantic vectors have incremental text cache'}
            else:
                assets = prepare_semantic_assets(config, output)
                vectors, info = _semantic_vectors(texts, text_hashes, config, output, model_dir, assets)
                estimator = KMeans(n_clusters=k, random_state=seed, n_init=5, max_iter=200, algorithm='lloyd')
                info['assets'] = assets
            labels = estimator.fit_predict(vectors)
            centers = normalize(estimator.cluster_centers_)
            similarities = np.einsum('ij,ij->i', vectors, centers[labels])
            threshold = float(np.quantile(similarities, float(cfg.get('outlier_quantile', .05))))
            outliers = similarities < threshold
            # Sample silhouette is a diagnostic, never a correctness/quality score.
            if len(corpus) > k + 2 and len(np.unique(labels)) > 1:
                sil = float(silhouette_score(vectors, labels, sample_size=min(3000, len(corpus)), random_state=seed, metric='cosine'))
            else:
                sil = None
        rows = [{'paper_id': p['paper_id'], 'topic_id': int(labels[i]),
                 'similarity': float(similarities[i]), 'outlier': bool(outliers[i])}
                for i, p in enumerate(corpus)]
        if set(ids) != {r['paper_id'] for r in rows} or not np.isfinite(vectors).all():
            raise ValueError('Model input/output identity or finite-vector invariant failed')
        topics = _topic_outputs(corpus, labels, similarities, outliers, tfidf, terms, k)
        write_jsonl(model_dir / 'assignments.jsonl', rows)
        write_csv(model_dir / 'assignments.csv', rows, ['paper_id', 'topic_id', 'similarity', 'outlier'])
        write_json(model_dir / 'topics.json', topics)
        write_csv(model_dir / 'topic_review.csv', [{'topic_id': t['topic_id'], 'size': t['size'],
                  'automatic_keywords': '; '.join(t['keywords']), 'human_name': '',
                  'task': '', 'method': '', 'data_modality': '', 'bottleneck': '',
                  'review_status': 'pending',
                  'representative_paper_ids': '; '.join(r['paper_id'] for r in t['representatives'])}
                  for t in topics])
        np.save(model_dir / 'embeddings.npy', vectors)
        np.save(model_dir / 'centroids.npy', estimator.cluster_centers_)
        _plot_topics(topics, model_dir / 'topic_sizes.png')
        manifest.update(info)
        manifest.update(status='completed', finished_at=utcnow(),
                        elapsed_seconds=round(time.monotonic()-started, 3),
                        feature_count=int(tfidf.shape[1]), embedding_dimension=int(vectors.shape[1]),
                        topics=k, realized_topics=int(len(np.unique(labels))),
                        outlier_rule='cosine similarity to assigned normalized centroid below corpus quantile; assignments retained',
                        outlier_threshold=threshold, outlier_count=int(outliers.sum()),
                        outlier_fraction=float(outliers.mean()), silhouette_cosine_sample=sil,
                        silhouette_caution='sampled internal clustering diagnostic, not topic correctness or optimal K',
                        assignments_sha256=sha256(model_dir / 'assignments.jsonl'),
                        vectors_sha256=sha256(model_dir / 'embeddings.npy'))
        write_json(model_dir / 'manifest.json', manifest)
        print(json.dumps({'stage': 'model_completed', 'backend': backend, 'papers': len(corpus),
                          'topics': k, 'elapsed_seconds': manifest['elapsed_seconds']}), flush=True)
        return manifest
    except BaseException as exc:
        manifest.update(status='failed', error=repr(exc), finished_at=utcnow())
        write_json(model_dir / 'manifest.json', manifest)
        raise
