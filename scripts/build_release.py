#!/usr/bin/env python3
"""Build auditable source/data archives, verify ZIP CRC and every member SHA256."""
from pathlib import Path
import argparse
import json
import sys
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from ai_trends.common import sha256,write_json,atomic_write,read_json,utcnow

PROJECT=Path(__file__).resolve().parents[1]


def permitted(path):
    return not any(p.startswith('.') or p in ('__pycache__','build','auditable_ai_trends.egg-info') for p in path.parts) and not path.name.endswith(('.tmp','.pyc'))


def archive(target, items):
    target=Path(target);target.parent.mkdir(parents=True,exist_ok=True)
    manifest={}
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as z:
        for name,path in sorted(items):
            if name in manifest:raise ValueError('Duplicate ZIP member '+name)
            manifest[name]={'size_bytes':path.stat().st_size,'sha256':sha256(path)}
            z.write(path,name)
        z.writestr('MANIFEST.sha256.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    with zipfile.ZipFile(target) as z:
        bad=z.testzip()
        if bad:raise ValueError('ZIP CRC failed '+bad)
        for name,info in manifest.items():
            # Stream verification avoids loading the full data set twice.
            import hashlib
            h=hashlib.sha256();size=0
            with z.open(name) as f:
                for block in iter(lambda:f.read(1024*1024),b''):
                    h.update(block);size+=len(block)
            if h.hexdigest()!=info['sha256'] or size!=info['size_bytes']:raise ValueError('ZIP SHA256 failed '+name)
    return {'file':target.name,'size_bytes':target.stat().st_size,'sha256':sha256(target),'members':len(manifest),'zip_crc':'passed','member_sha256':'passed'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',default='output');parser.add_argument('--dist',default='dist')
    parser.add_argument('--allow-partial',action='store_true',help='Package an explicitly partial collection, preserving validation state')
    args=parser.parse_args();out=Path(args.output);dist=Path(args.dist);dist.mkdir(parents=True,exist_ok=True)
    validation=read_json(out/'validation.json',{})
    if validation.get('structural_status')!='passed' and not args.allow_partial:
        raise RuntimeError('Fresh structural validation must pass before final release')
    source=[]
    for top in ['src','scripts','tests','configs','docs']:
        source += [(str(p.relative_to(PROJECT)),p) for p in (PROJECT/top).rglob('*') if p.is_file() and permitted(p.relative_to(PROJECT))]
    for name in ['README.md','pyproject.toml','LICENSE']:
        if (PROJECT/name).exists():source.append((name,PROJECT/name))
    reading='# 全部源码阅读版\n\n生成时间：'+utcnow()+'\n\n'
    for name,path in sorted(source):
        reading+='\n## '+name+'\n\n```'+('python' if path.suffix=='.py' else '')+'\n'+path.read_text()+'\n```\n'
    atomic_write(dist/'SOURCE_READING.md',reading)
    source.append(('SOURCE_READING.md',dist/'SOURCE_READING.md'))
    if (out/'RUN_RESULTS.md').exists():source.append(('RUN_RESULTS.md',out/'RUN_RESULTS.md'))
    records=[archive(dist/'source_complete.zip',source)]
    data=[]
    for p in out.rglob('*'):
        rel=p.relative_to(out)
        if not p.is_file() or not permitted(rel) or 'probe' in rel.parts:continue
        # Standalone report and encoding checkpoint are separate deliverables.
        if rel.parts[0]=='cache' or str(rel)=='report.html':continue
        if rel.parts[0] in ('encoding_warmup','encoding_after_main_repair') and p.suffix=='.npy':continue
        if 'model_assets' in rel.parts and not p.name.endswith('.json'):continue
        data.append((str(rel),p))
    records.append(archive(dist/'data_and_results.zip',data))
    for name in ['report.html','RUN_RESULTS.md']:
        if (out/name).exists():
            import shutil
            shutil.copyfile(out/name,dist/name)
            records.append({'file':name,'size_bytes':(dist/name).stat().st_size,'sha256':sha256(dist/name)})
    for p in sorted(dist.glob('*.zip')):
        if p.name not in {r['file'] for r in records}:
            records.append({'file':p.name,'size_bytes':p.stat().st_size,'sha256':sha256(p),'role':'earlier_stage_checkpoint'})
    release={'generated_at':utcnow(),'artifacts':records,'validation':validation,'pretrained_weights':'Excluded; exact revision, URLs and SHA256 remain in model manifests. See docs/REPRODUCE.md.','offline_tests':read_json(out/'test_results.json',{}),'build':read_json(out/'build_results.json',{})}
    release['browser_check']=read_json(out/'browser_check.json',{})
    release['separate_deliverables']=['report.html','semantic_encoding_checkpoint.zip']
    release['deduplication_note']='Dense semantic cache and equivalent warm-up matrices are delivered in the encoding checkpoint; final per-paper vectors remain under models/onnx. The standalone report is supplied separately.'
    write_json(dist/'release_manifest.json',release)
    print(json.dumps({'artifacts':records,'validation':validation.get('structural_status')},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
