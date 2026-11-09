import argparse
import json
from pathlib import Path
from .common import read_json, write_json, utcnow, sha256


def main():
    p = argparse.ArgumentParser(description='Auditable ICLR/ICML/NeurIPS 2024-2026 pipeline')
    p.add_argument('--config', default='configs/latest.json')
    p.add_argument('--output', default='output')
    sub = p.add_subparsers(dest='stage', required=True)
    for name in ['collect','prepare','backfill','model','analyze','report','validate']:
        q = sub.add_parser(name)
        if name in ['model','analyze','report']:
            q.add_argument('--backend', choices=['lsa','onnx'], default='lsa')
        if name == 'prepare':
            q.add_argument('--with-details', action='store_true')
        if name == 'backfill':
            q.add_argument('--retry-failed', action='store_true', help='Retry failed requests or missing abstracts; preserve blocked and identity-conflict states')
    args = p.parse_args()
    config = read_json(args.config)
    out = Path(args.output); out.mkdir(parents=True, exist_ok=True)
    existing_scope=read_json(out/'collection_scope.json')
    requested_scope={k:config[k] for k in ('venues','years','http')}
    if existing_scope and existing_scope['sha256']!=sha256(json.dumps(requested_scope,sort_keys=True)):
        raise RuntimeError('Different collection scope/config requires another output directory for every stage')
    stamp = utcnow().replace(':','').replace('.','')
    manifest = {'started_at': utcnow(), 'config': config, 'config_sha256': sha256(Path(args.config)), 'stage': args.stage, 'status': 'running'}
    runfile = out / 'runs' / f'{stamp}-{args.stage}.json'
    write_json(runfile, manifest)
    try:
        if args.stage == 'collect':
            from .collectors import collect
            result = collect(config, out)
        elif args.stage == 'prepare':
            from .processing import prepare
            result = prepare(config, out, args.with_details)
        elif args.stage == 'backfill':
            from .details import backfill
            result = backfill(config, out, args.retry_failed)
        elif args.stage == 'model':
            from .modeling import run_model
            result = run_model(config, out, args.backend)
        elif args.stage == 'analyze':
            from .analysis import analyze
            result = analyze(config, out, args.backend)
        elif args.stage == 'report':
            from .report import build_report
            result = build_report(config, out, args.backend)
        elif args.stage == 'validate':
            from .validation import validate
            result = validate(config, out)
        else:
            raise RuntimeError('Unknown stage')
        status='completed'
        if args.stage=='collect' and any(s in ('blocked','failed') for s in result.get('openreview_statuses',[])):
            status='completed_with_blocked_channels'
        if args.stage=='backfill' and result.get('failed',0):
            status='completed_with_failures'
        manifest.update(status=status, result=result)
    except BaseException as e:
        manifest.update(status='failed', error=repr(e))
        raise
    finally:
        manifest['finished_at'] = utcnow()
        write_json(runfile, manifest)
