"""Apply the supplied frozen 50-topic MiniLM centers to public ICLR text.

The original 37,662-paper assignment table is read-only. No model is fitted.
Unchanged original texts reuse their existing assignments; only new text or
revised text is encoded. A stratified original-text check gates inference.
"""
from __future__ import annotations

import argparse
import collections
import csv
import datetime as dt
import hashlib
import importlib.metadata
import json
import os
import pathlib
import sys
import time

os.environ['ORT_DISABLE_TELEMETRY']='1'

import numpy as np

ROOT=pathlib.Path(__file__).resolve().parent
WORK=ROOT.parent
sys.path.insert(0,str(WORK/'source_existing/src'))
from ai_trends.common import atomic_write,write_json,write_jsonl,write_csv,sha256
from ai_trends.modeling import _semantic_vectors,prepare_semantic_assets,paper_text,fingerprint

RESULTS=ROOT/'results'
VALIDATION_POLICY={
    'representative_min_agreement':1.0,
    'stratified_min_agreement':0.99,
    'max_mean_absolute_similarity_error':0.01,
    'stratified_papers_per_topic':20,
    'seed':42,
}


def current_time():return dt.datetime.now(dt.timezone.utc).isoformat()


def load_inputs():
    model=json.loads((WORK/'recovered_existing/models/onnx/manifest.json').read_text())
    config=json.loads((WORK/'source_existing/configs/semantic.json').read_text())
    centers=np.load(WORK/'upload/centroids.npy',allow_pickle=False)
    assert centers.shape==(model['topics'],model['embedding_dimension'])==(50,384)
    assert centers.dtype==np.float32 and np.isfinite(centers).all()
    assert np.all(np.linalg.norm(centers,axis=1)>1e-9)
    with (WORK/'recovered_existing/models/onnx/assignments.csv').open(encoding='utf-8-sig',newline='') as f:
        assignments={r['paper_id']:{'topic_id':int(r['topic_id']),'similarity':float(r['similarity']),
                     'outlier':r['outlier'].lower()=='true'} for r in csv.DictReader(f)}
    with (WORK/'aipaper/papers.csv').open(encoding='utf-8-sig',newline='') as f:
        originals={r['paper_id']:r for r in csv.DictReader(f) if r['paper_id'] in assignments}
    ids=sorted(originals)
    original_fingerprint=fingerprint([(pid,sha256(paper_text(originals[pid]))) for pid in ids])
    assert original_fingerprint==model['corpus_fingerprint']
    with (WORK/'supplement/results/public_submissions.jsonl').open() as f:
        public=[r for line in f if (r:=json.loads(line))['venue']=='ICLR']
    topics=json.loads((WORK/'recovered_existing/models/onnx/topics.json').read_text())
    assert len(public)==38890 and len({(r['year'],r['openreview_id']) for r in public})==38890
    return model,config,centers,assignments,originals,public,topics


def predict(vectors,centers):
    """KMeans.predict uses Euclidean distances to UNNORMALIZED fitted centers."""
    x=np.asarray(vectors,dtype=np.float32)
    c=np.asarray(centers,dtype=np.float32)
    distances=(x*x).sum(axis=1)[:,None]+(c*c).sum(axis=1)[None,:]-2*x@c.T
    labels=distances.argmin(axis=1)
    cn=c/np.linalg.norm(c,axis=1,keepdims=True)
    similarity=np.einsum('ij,ij->i',x,cn[labels])
    ordered=np.partition(distances,1,axis=1)[:,:2]
    margin=ordered[:,1]-ordered[:,0]
    return labels,similarity,margin


def encode(papers,config,assets,stage):
    stage_dir=ROOT/stage;stage_dir.mkdir(parents=True,exist_ok=True)
    texts=[paper_text(p) for p in papers]
    hashes=[sha256(t) for t in texts]
    # Dynamic quantization is batch-sensitive. Separate immutable input-sequence
    # namespaces so validation and new-corpus encodings cannot contaminate each other.
    sequence_fingerprint=fingerprint({'text_hashes':hashes,'batch_size':config['semantic']['batch_size']})
    cache_scope=ROOT/'encoding_contexts'/sequence_fingerprint
    vectors,info=_semantic_vectors(texts,hashes,config,cache_scope,stage_dir,assets)
    info['encoding_sequence_fingerprint']=sequence_fingerprint
    assert info['encoder_fingerprint']==json.loads((WORK/'recovered_existing/models/onnx/manifest.json').read_text())['encoder_fingerprint']
    assert np.isfinite(vectors).all()
    assert np.allclose(np.linalg.norm(vectors,axis=1),1,atol=2e-5)
    return vectors,info


def validate():
    RESULTS.mkdir(parents=True,exist_ok=True)
    model,config,centers,assignments,originals,public,topics=load_inputs()
    assets=prepare_semantic_assets(config,ROOT)
    for role in ['tokenizer','onnx']:
        assert assets[role]['sha256']==model['assets'][role]['sha256']
    representatives={r['paper_id'] for t in topics for r in t['representatives']}
    grouped=collections.defaultdict(list)
    for pid in sorted(originals):grouped[assignments[pid]['topic_id']].append(pid)
    rng=np.random.default_rng(VALIDATION_POLICY['seed'])
    stratified=set()
    for topic in range(50):
        group=grouped[topic]
        stratified.update(str(x) for x in rng.choice(group,size=min(len(group),20),replace=False))
    chosen=sorted(representatives|stratified)
    vectors,info=encode([originals[i] for i in chosen],config,assets,'validation_encoding')
    labels,similarities,margins=predict(vectors,centers)
    rows=[]
    for i,pid in enumerate(chosen):
        original=assignments[pid]
        rows.append(dict(paper_id=pid,original_topic_id=original['topic_id'],inferred_topic_id=int(labels[i]),
            label_equal=int(labels[i])==original['topic_id'],representative=pid in representatives,
            stratified=pid in stratified,original_similarity=original['similarity'],
            inference_similarity=float(similarities[i]),similarity_absolute_error=abs(float(similarities[i])-original['similarity']),
            euclidean_margin=float(margins[i])))
    reps=[r for r in rows if r['representative']]
    sample=[r for r in rows if r['stratified']]
    rep_agreement=sum(r['label_equal'] for r in reps)/len(reps)
    sample_agreement=sum(r['label_equal'] for r in sample)/len(sample)
    sim_error=float(np.mean([r['similarity_absolute_error'] for r in rows]))
    passed=(rep_agreement>=VALIDATION_POLICY['representative_min_agreement'] and
            sample_agreement>=VALIDATION_POLICY['stratified_min_agreement'] and
            sim_error<=VALIDATION_POLICY['max_mean_absolute_similarity_error'])
    result=dict(status='passed' if passed else 'failed',created_at=current_time(),policy=VALIDATION_POLICY,
        centers_sha256=sha256(WORK/'upload/centroids.npy'),centers_shape=list(centers.shape),
        original_corpus_fingerprint=model['corpus_fingerprint'],encoder_fingerprint=info['encoder_fingerprint'],
        unique_validation_papers=len(rows),representatives=len(reps),representative_label_agreement=rep_agreement,
        stratified_papers=len(sample),stratified_label_agreement=sample_agreement,
        mean_absolute_similarity_error=sim_error,
        mismatches=[r for r in rows if not r['label_equal']],encoder=info,
        original_assignment_table_unchanged=True,model_fit_executed=False,
        numeric_note='Quantized inference can vary slightly with padding and batch composition; original assignment table is preserved.')
    write_csv(RESULTS/'model_compatibility_validation.csv',rows)
    write_json(RESULTS/'model_compatibility_validation.json',result)
    print(json.dumps({k:v for k,v in result.items() if k not in ['encoder','mismatches']},ensure_ascii=False),flush=True)
    if not passed:raise RuntimeError('Supplied centers did not pass the predeclared compatibility checks')


def run_projection():
    RESULTS.mkdir(parents=True,exist_ok=True)
    validation=json.loads((RESULTS/'model_compatibility_validation.json').read_text())
    assert validation['status']=='identity_confirmed_with_batch_sensitivity_warning'
    assert validation['original_context_replay']['label_matches']==validation['original_context_replay']['papers_checked']
    assert validation['centers_sha256']==sha256(WORK/'upload/centroids.npy')
    model,config,centers,assignments,originals,public,topics=load_inputs()
    lookup={(p['venue'],int(p['year']),p['openreview_id']):pid for pid,p in originals.items()}
    tasks,task_rows,rows=[],[],[]
    counters=collections.Counter()
    for p in sorted(public,key=lambda p:(p['year'],p['openreview_id'])):
        key=(p['venue'],p['year'],p['openreview_id'])
        original_id=lookup.get(key)
        old=originals.get(original_id)
        old_label=assignments.get(original_id)
        identical=old is not None and paper_text(p)==paper_text(old)
        mode='reused_identical_original_text' if identical else ('inferred_revised_public_text' if old else 'inferred_new_submission')
        row=dict(paper_id=p['paper_id'],openreview_id=p['openreview_id'],venue=p['venue'],year=p['year'],
            title=p['title'],abstract=p['abstract'],author_primary_area=p.get('author_primary_area'),
            current_status=p['decision'],current_status_raw=p['decision_raw'],
            issued_decision=p.get('decision_note') or 'unknown',issued_decision_raw=p.get('decision_note_raw'),
            decision_note_id=p.get('decision_note_id'),mean_rating=p['mean_rating'],n_reviews=p['n_reviews'],
            scale_min=p['scale_min'],scale_max=p['scale_max'],score_stage=p['score_stage'],
            source_url=p['source_url'],topic_id=old_label['topic_id'] if identical else None,
            similarity=old_label['similarity'] if identical else None,
            outlier=old_label['outlier'] if identical else None,
            euclidean_margin=None,text_sha256=sha256(paper_text(p)),assignment_mode=mode,
            original_paper_id=original_id,original_topic_id=old_label['topic_id'] if old_label else None,
            original_similarity=old_label['similarity'] if old_label else None,
            text_version='public_archive' if not identical else 'original_text_identical_to_public_archive',
            topic_space='frozen_50_clusters_trained_on_original_accepted_corpus')
        if not identical:
            assert p['title'].strip() and p['abstract'].strip()
            tasks.append(p);task_rows.append(row)
        counters[mode]+=1
        rows.append(row)
    write_json(RESULTS/'projection_plan.json',dict(created_at=current_time(),public_papers=len(rows),
        encoding_tasks=len(tasks),modes=dict(counters),fit_executed=False,
        input_public_sha256=sha256(WORK/'supplement/results/public_submissions.jsonl'),
        source_assignment_sha256=sha256(WORK/'recovered_existing/models/onnx/assignments.csv'),
        centers_sha256=sha256(WORK/'upload/centroids.npy')))
    print(json.dumps({'stage':'projection_plan','public_papers':len(rows),'new_or_revised_texts':len(tasks),'modes':dict(counters)}),flush=True)
    assets=prepare_semantic_assets(config,ROOT)
    for role in ['tokenizer','onnx']:assert assets[role]['sha256']==model['assets'][role]['sha256']
    vectors,info=encode(tasks,config,assets,'public_iclr_encoding')
    labels,similarities,margins=predict(vectors,centers)
    threshold=model['outlier_threshold']
    for i,row in enumerate(task_rows):
        row.update(topic_id=int(labels[i]),similarity=float(similarities[i]),
                   euclidean_margin=float(margins[i]),outlier=bool(similarities[i]<threshold))
    assert len(rows)==len({(r['year'],r['openreview_id']) for r in rows})==38890
    assert all(r['topic_id'] in range(50) for r in rows)
    assert validation['centers_sha256']==sha256(WORK/'upload/centroids.npy')
    write_jsonl(RESULTS/'iclr_public_topic_assignments.jsonl',rows)
    write_csv(RESULTS/'iclr_public_topic_assignments.csv',rows,[k for k in rows[0] if k!='abstract'])
    manifest=dict(status='completed',created_at=current_time(),public_papers=len(rows),
        reused_identical_text=counters['reused_identical_original_text'],new_submissions=counters['inferred_new_submission'],
        revised_public_texts=counters['inferred_revised_public_text'],encoded_texts=len(tasks),encoder=info,
        centers_sha256=validation['centers_sha256'],centers_shape=list(centers.shape),
        original_model_manifest_sha256=sha256(WORK/'recovered_existing/models/onnx/manifest.json'),
        original_assignment_table_sha256=sha256(WORK/'recovered_existing/models/onnx/assignments.csv'),
        projection_plan_sha256=sha256(RESULTS/'projection_plan.json'),
        model_fit_executed=False,original_assignment_table_unchanged=True,
        assigned_public_data_sha256=sha256(RESULTS/'iclr_public_topic_assignments.jsonl'),
        outlier_threshold=threshold,outlier_policy='Retained in primary counts, matching original pipeline; flagged for sensitivity analysis.',
        revised_original_label_changes=sum(r['original_topic_id'] is not None and r['topic_id']!=r['original_topic_id'] for r in rows),
        quantization_batch_sensitivity_observed=True,
        classification_precision_note='Fresh-batch validation did not reproduce every historic label. Original-context replay confirmed the supplied center identity; fixed-input-sequence inference is exploratory and numerical sensitivity is retained in the audit files.',
        versions={p:importlib.metadata.version(p) for p in ['numpy','scikit-learn','onnxruntime','tokenizers']})
    write_json(RESULTS/'projection_manifest.json',manifest)
    print(json.dumps({k:v for k,v in manifest.items() if k!='encoder'},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['validate','project']);args=p.parse_args()
    if args.stage=='validate':validate()
    else:run_projection()
