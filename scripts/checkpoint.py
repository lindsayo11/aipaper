#!/usr/bin/env python3
"""Package consistent stage evidence without altering immutable HTTP snapshots."""
from pathlib import Path
import argparse
import gzip
import json
import sys
import time
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ai_trends.common import read_json,sha256,utcnow
from build_release import permitted

ROOT=Path(__file__).resolve().parents[1]


def package(stage, output, target):
    output=Path(output);target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    paths=[]
    roots={'processed':['processed'], 'lsa':['models/lsa'], 'semantic':['models/onnx','model_comparison'], 'analysis':['analysis','source_evidence'], 'details':['details'], 'source':['src','scripts','tests','configs','docs']}
    if stage not in roots:raise ValueError(stage)
    base=ROOT if stage=='source' else output
    for top in roots[stage]:
        paths += [p for p in (base/top).rglob('*') if p.is_file() and permitted(p.relative_to(base))]
    if stage=='source':paths += [ROOT/'README.md',ROOT/'pyproject.toml',ROOT/'LICENSE']
    if stage=='details':
        for p in (output/'raw/http').glob('*.json'):
            m=read_json(p,{})
            if m.get('status')=='success' and ('/poster/' in m.get('url','') or 'papers.html' in m.get('url','')):
                paths += [p,output/m['body_path']]
    # Small mutable manifests/JSONL are captured together under the summary commit marker.
    frozen={}
    for attempt in range(5):
        before=(output/'details/summary.json').read_bytes() if stage=='details' else None
        frozen={str(p.relative_to(base)):p.read_bytes() for p in paths if 'raw/http' not in str(p)}
        after=(output/'details/summary.json').read_bytes() if stage=='details' else None
        coherent=before==after
        if stage=='details' and coherent:
            summary=json.loads(before)
            attempts=[json.loads(x) for x in frozen.get('details/attempts.jsonl',b'').decode().split('\n') if x]
            patches=[json.loads(x) for x in frozen.get('details/patches.jsonl',b'').decode().split('\n') if x]
            attempt_ids={r['paper_id'] for r in attempts}
            coherent=(len(attempt_ids)==summary.get('attempted') and sum(r['status']=='success' for r in attempts)==summary.get('successful') and {r['paper_id'] for r in patches}.issubset(attempt_ids))
        if coherent:break
        time.sleep(.05)
    else:raise RuntimeError('Could not capture a stable stage checkpoint')
    records={}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=4,allowZip64=True) as z:
        for p in sorted(set(paths)):
            name=str(p.relative_to(base))
            if name in frozen:
                body=frozen[name];z.writestr(name,body);records[name]={'size_bytes':len(body),'sha256':sha256(body)}
            else:
                z.write(p,name);records[name]={'size_bytes':p.stat().st_size,'sha256':sha256(p)}
        z.writestr('MANIFEST.sha256.json',json.dumps({'created_at':utcnow(),'stage':stage,'files':records},ensure_ascii=False,indent=2))
    with zipfile.ZipFile(target) as z:
        if z.testzip():raise RuntimeError('ZIP CRC failed')
        for name,info in records.items():
            if sha256(z.read(name))!=info['sha256']:raise RuntimeError('ZIP member hash failed '+name)
    result={'stage':stage,'path':str(target.resolve()),'sha256':sha256(target),'size_bytes':target.stat().st_size,'files':len(records),'zip_crc':'passed','member_sha256':'passed'}
    print(json.dumps(result),flush=True)
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=['source','details','processed','lsa','semantic','analysis'])
    p.add_argument('--output',default='output');p.add_argument('--target',required=True)
    a=p.parse_args();package(a.stage,a.output,a.target)
