#!/usr/bin/env python3
"""Cache real MiniLM vectors while independent official HTML backfill continues.

This is encoding only: it never emits topic assignments or claims a topic model
has finished. The final model reuses exact text-fingerprint vectors.
"""
import argparse
import json
import os
from pathlib import Path
import sys
import time
os.environ['ORT_DISABLE_TELEMETRY']='1'
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import numpy as np
from ai_trends.common import read_json,read_jsonl,write_json,write_jsonl,sha256,utcnow
from ai_trends.modeling import model_corpus,paper_text,prepare_semantic_assets,_semantic_vectors
from ai_trends.processing import merge_papers,apply_patches


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',default='configs/semantic.json');p.add_argument('--output',default='output');p.add_argument('--with-details',action='store_true');a=p.parse_args()
    config=read_json(a.config);out=Path(a.output);dest=out/('encoding_after_main_repair' if a.with_details else 'encoding_warmup');dest.mkdir(parents=True,exist_ok=True)
    source_papers=read_jsonl(out/'processed/papers.jsonl')
    if a.with_details:
        source_papers,_=merge_papers(source_papers)
        source_papers,_=apply_patches(source_papers,read_jsonl(out/'details/patches.jsonl'))
    papers=model_corpus(source_papers)
    texts=[paper_text(p) for p in papers];hashes=[sha256(t) for t in texts]
    write_jsonl(dest/'corpus_ids.jsonl',[{'paper_id':p['paper_id'],'text_sha256':h} for p,h in zip(papers,hashes)])
    status={'started_at':utcnow(),'stage':'semantic_encoding_only','status':'running','papers':len(papers),'note':'Partial data availability at encoding time; final shared models are fitted after main abstract backfill.'}
    write_json(dest/'manifest.json',status);start=time.monotonic()
    try:
        assets=prepare_semantic_assets(config,out)
        vectors,info=_semantic_vectors(texts,hashes,config,out,dest,assets)
        np.save(dest/'embeddings.npy',vectors)
        status.update(info);status.update(status='encoding_completed_not_topic_model',elapsed_seconds=time.monotonic()-start,finished_at=utcnow(),vector_sha256=sha256(dest/'embeddings.npy'))
        write_json(dest/'manifest.json',status)
        print(json.dumps(status),flush=True)
    except BaseException as e:
        status.update(status='failed',error=repr(e));write_json(dest/'manifest.json',status);raise

if __name__=='__main__':main()
