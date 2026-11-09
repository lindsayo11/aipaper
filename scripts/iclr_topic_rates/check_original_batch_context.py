"""Replay only batches needed for mismatched validation papers, without fitting.

The original execution log records 35,992 warmup texts and 1,670 later repaired
abstracts. This experiment checks quantized inference's batch sensitivity.
"""
import collections
import json
import os
import pathlib
import sys

os.environ['ORT_DISABLE_TELEMETRY']='1'
import numpy as np
from tokenizers import Tokenizer

ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from frozen_projection import load_inputs,predict,RESULTS,WORK
from ai_trends.modeling import _token_chunks,masked_mean,safe_onnxruntime,paper_text,prepare_semantic_assets
from ai_trends.common import write_json,write_csv


def main():
    model,config,centers,assignments,originals,public,topics=load_inputs()
    earlier=json.loads((RESULTS/'model_compatibility_validation.json').read_text())
    targets={r['paper_id'] for r in earlier['mismatches']}
    # Add 50 controls, one original representative per topic.
    targets.update(t['representatives'][0]['paper_id'] for t in topics)
    phases=[[],[]]
    for pid in sorted(originals):
        metadata=json.loads(originals[pid]['metadata'])
        phases[int('detail_attempts' in metadata)].append(pid)
    assert [len(p) for p in phases]==[35992,1670]
    assets=prepare_semantic_assets(config,ROOT)
    tokenizer=Tokenizer.from_file(assets['tokenizer']['local_path']);tokenizer.no_truncation();tokenizer.no_padding()
    ort=safe_onnxruntime();opts=ort.SessionOptions();opts.intra_op_num_threads=4;opts.inter_op_num_threads=1;opts.log_severity_level=3
    session=ort.InferenceSession(assets['onnx']['local_path'],sess_options=opts,providers=['CPUExecutionProvider'])
    names={n.name for n in session.get_inputs()}
    sums={};weights=collections.Counter();counts=collections.Counter();batches=0
    def process(batch):
        nonlocal batches
        if not any(pid in targets for pid,chunk,w in batch):return
        width=max(len(chunk) for _,chunk,_ in batch)
        ids=np.zeros((len(batch),width),dtype=np.int64);mask=np.zeros_like(ids)
        for i,(_,chunk,_) in enumerate(batch):ids[i,:len(chunk)]=chunk;mask[i,:len(chunk)]=1
        feed={'input_ids':ids,'attention_mask':mask,'token_type_ids':np.zeros_like(ids)}
        out=session.run(None,{k:v for k,v in feed.items() if k in names})[0]
        pooled=masked_mean(out,mask)
        for i,(pid,chunk,w) in enumerate(batch):
            if pid in targets:
                if pid not in sums:sums[pid]=np.zeros(384,dtype=np.float64)
                sums[pid]+=pooled[i]*w;weights[pid]+=w;counts[pid]+=1
        batches+=1
        if batches%32==0:print(json.dumps({'stage':'original_batch_context','batches_replayed':batches,'targets_seen':len(sums)}),flush=True)
    for phase in phases:
        batch=[]
        for pid in phase:
            for chunk,w in _token_chunks(tokenizer,paper_text(originals[pid]),256):
                batch.append((pid,chunk,w))
                if len(batch)==32:process(batch);batch=[]
        if batch:process(batch)
    rows=[]
    for pid in sorted(targets):
        v=np.asarray(sums[pid]/weights[pid],dtype=np.float32);v/=np.linalg.norm(v)
        labels,sim,margin=predict(v[None,:],centers)
        old=assignments[pid]
        rows.append(dict(paper_id=pid,original_topic_id=old['topic_id'],context_replayed_topic_id=int(labels[0]),
                         label_equal=old['topic_id']==int(labels[0]),original_similarity=old['similarity'],
                         replayed_similarity=float(sim[0]),similarity_error=abs(old['similarity']-float(sim[0])),
                         originally_mismatched=pid in {r['paper_id'] for r in earlier['mismatches']}))
    result=dict(experiment='replay_the_original_two_encoding_phases_for_diagnostic_targets_only',
                expected_phase_papers=[35992,1670],papers_checked=len(rows),batches_replayed=batches,
                label_matches=sum(r['label_equal'] for r in rows),mean_similarity_error=float(np.mean([r['similarity_error'] for r in rows])),
                mismatches=[r for r in rows if not r['label_equal']],model_fit_executed=False)
    write_csv(RESULTS/'original_batch_context_check.csv',rows)
    write_json(RESULTS/'original_batch_context_check.json',result)
    print(json.dumps(result),flush=True)


if __name__=='__main__':main()
