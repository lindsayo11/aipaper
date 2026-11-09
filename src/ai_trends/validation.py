"""Fresh artifact consistency checks; network completeness remains a separate status."""
from __future__ import annotations
import base64
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from .common import read_json, read_jsonl, sha256, write_json, utcnow
from .modeling import model_corpus, fingerprint, paper_text


def validate(config, output):
    out=Path(output)
    checks=[]
    def check(name, ok, evidence):
        checks.append({'name':name,'status':'passed' if ok else 'failed','evidence':evidence})
    coverage=read_json(out/'source_coverage.json',[])
    expected={(v,y) for v in config['venues'] for y in config['years']}
    seen={(r['venue'],r['year']) for r in coverage if r.get('status') in ('success','partial','blocked','failed')}
    check('nine_explicit_source_states',seen==expected,{'expected':len(expected),'observed':len(seen)})
    errors=[];success=0;failures=0
    for path in sorted((out/'raw/http').glob('*.json')):
        m=read_json(path,{})
        try:
            if m.get('status')=='success':
                b=gzip.decompress((out/m['body_path']).read_bytes())
                success+=1
                if sha256(b)!=m.get('sha256') or len(b)!=m.get('size_bytes'):
                    errors.append(str(path))
                if not b or m.get('http_status')!=200:errors.append(str(path))
            else:
                failures+=1
                if m.get('error_body_path'):
                    b=gzip.decompress((out/m['error_body_path']).read_bytes())
                    if sha256(b)!=m.get('error_body_sha256'):errors.append(str(path))
        except Exception as e:errors.append({'path':str(path),'error':str(e)})
    check('http_snapshot_hashes_read_back',not errors,{'successful_snapshots':success,'failed_or_blocked_requests':failures,'errors':errors})
    papers=read_jsonl(out/'processed/papers.jsonl')
    ids=[p['paper_id'] for p in papers]
    check('paper_ids_unique',len(ids)==len(set(ids)),{'papers':len(papers)})
    scoped_forums=[(p['venue'],p['year'],p['openreview_id']) for p in papers if p.get('openreview_id')]
    check('venue_year_forum_identities_unique',len(scoped_forums)==len(set(scoped_forums)),{'records_with_forum':len(scoped_forums)})
    invalid=[p['paper_id'] for p in papers if p.get('openreview_id') and re.match(r'^\d{4}-(?:Oral|Poster|Spotlight)-',p['openreview_id'],re.I)]
    check('display_ids_not_used_as_forums',not invalid,invalid)
    required={'paper_id','venue','year','title','abstract','authors','keywords','source','source_id','source_url','openreview_id','track','track_evidence','decision','presentation','text_version','collected_at','metadata'}
    bad=[p['paper_id'] for p in papers if not required.issubset(p) or not isinstance(p['keywords'],list)]
    check('paper_schema_and_author_keywords',not bad,{'invalid_rows':bad[:20]})
    eligible=model_corpus(papers)
    eligible_ids={p['paper_id'] for p in eligible}
    corpus_fp=fingerprint([(p['paper_id'],sha256(paper_text(p))) for p in eligible])
    for backend in ('lsa','onnx'):
        root=out/'models'/backend
        rows=read_jsonl(root/'assignments.jsonl');mid=[p['paper_id'] for p in rows]
        manifest=read_json(root/'manifest.json',{})
        check(backend+'_all_eligible_ids_assigned',len(mid)==len(set(mid)) and set(mid)==eligible_ids,{'eligible':len(eligible_ids),'assigned':len(mid)})
        check(backend+'_actually_completed',manifest.get('status')=='completed' and manifest.get('corpus_fingerprint')==corpus_fp,{'status':manifest.get('status'),'corpus_matches':manifest.get('corpus_fingerprint')==corpus_fp})
        topic_sizes=sum(t.get('size',0) for t in read_json(root/'topics.json',[]))
        check(backend+'_topic_totals_match',topic_sizes==len(eligible),{'topic_total':topic_sizes,'input':len(eligible)})
        analysis=read_json(out/'analysis'/backend/'analysis_manifest.json',{})
        check(backend+'_analysis_exists',bool(analysis),{'path':str(out/'analysis'/backend/'analysis_manifest.json')})
    comparison=read_json(out/'model_comparison/comparison.json',{})
    check('both_models_compare_identical_corpus',comparison.get('same_corpus') is True and comparison.get('same_text_fingerprint') is True,comparison)
    reviews=read_jsonl(out/'processed/reviews.jsonl')
    invalid_scores=[r.get('review_id') for r in reviews if r.get('rating') is not None and (r.get('scale_min') is None or r.get('scale_max') is None or not r['scale_min']<=r['rating']<=r['scale_max'])]
    check('only_scale_legal_scores',not invalid_scores,{'reviews':len(reviews),'invalid':invalid_scores})
    # Independent cohort proof must be present to allow a conditional acceptance rate.
    bad_rates=[]
    for backend in ('lsa','onnx'):
        for row in read_json(out/'analysis'/backend/'decision_samples.json',[]):
            if row.get('conditional_acceptance_rate') is not None and not row.get('independent_complete_decision_cohort'):
                bad_rates.append(row)
    check('no_unproved_conditional_acceptance_rates',not bad_rates,{'invalid_rows':bad_rates})
    detail=read_json(out/'details/summary.json',{})
    check('detail_plan_all_terminal',detail.get('remaining')==0 and detail.get('planned')==detail.get('attempted'),detail)
    report=out/'report.html'
    exported=[]
    if report.exists():
        text=report.read_text()
        try:
            match=re.search(r'<script type="application/json" id="exports-data">(.*?)</script>',text,re.S)
            for record in json.loads(match.group(1)):
                body=gzip.decompress(base64.b64decode(record['data']))
                target=out/record['name']
                if sha256(body)!=record['sha256'] or body!=target.read_bytes():
                    raise ValueError('Embedded export mismatches '+record['name'])
                exported.append(record['name'])
            check('report_embedded_exports_exact',True,{'files':len(exported),'names':exported})
        except Exception as e:check('report_embedded_exports_exact',False,{'error':str(e)})
        node=shutil.which('node')
        if node:
            inline=re.search(r'<script>\s*(.*?)</script>',text,re.S)
            with tempfile.TemporaryDirectory() as td:
                target=Path(td)/'inline.js';target.write_text(inline.group(1))
                result=subprocess.run([node,'--check',str(target)],capture_output=True,text=True)
            check('report_javascript_syntax',result.returncode==0,{'exit_code':result.returncode,'stderr':result.stderr})
        else:check('report_javascript_syntax',False,'Node not installed')
        external=re.findall(r'<(?:script|link)[^>]+(?:src|href)=[\"\']https?://',text,re.I)
        check('report_has_no_external_resources',not external,{'external_resource_count':len(external)})
    else:check('report_present',False,'Missing report.html')
    quality=read_json(out/'processed/quality.json',{})
    result={'generated_at':utcnow(),'structural_status':'passed' if all(c['status']=='passed' for c in checks) else 'failed','checks':checks,'data_status':{'official_bulk':{f'{r["venue"]}-{r["year"]}':r['status'] for r in coverage},'openreview':{f'{r["venue"]}-{r["year"]}':r.get('openreview',{}).get('status','unknown') for r in coverage},'details':detail,'main_missing_abstract':quality.get('main_missing_abstract'),'network_completeness':'not_proven; observed lists and explicit track evidence only','review_analysis':'blocked' if any(r.get('openreview',{}).get('status')=='blocked' for r in coverage) else 'public_sample_only'},'limits':'Structural checks and successful endpoint traversal do not prove complete submissions, decisions, or official live program coverage.'}
    write_json(out/'validation.json',result)
    if result['structural_status']!='passed':
        raise RuntimeError('Artifact validation failed: '+', '.join(c['name'] for c in checks if c['status']=='failed'))
    return result
