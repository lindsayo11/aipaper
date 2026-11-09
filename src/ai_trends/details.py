"""Finite, resumable HTML backfill and official live-directory reconciliation."""
from __future__ import annotations
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import json
import re
from urllib.parse import urljoin, urlparse
from lxml import html
from .common import HttpClient, read_json, read_jsonl, write_json, write_jsonl, write_csv, utcnow, sha256
from .processing import clean, title_key, forum_id, event_to_paper, merge_papers


def canonical_detail(url):
    p=urlparse(url)
    path=re.sub(r'(/virtual/\d{4})/loc/[^/]+/',r'\1/',p.path)
    return f'https://{p.hostname}{path}'.rstrip('/')


def directory_items(body, page_url, year):
    doc=html.fromstring(body)
    items={}
    for a in doc.xpath('//a[@href]'):
        url=urljoin(page_url,a.get('href').strip())
        p=urlparse(url)
        m=re.fullmatch(r'/virtual/'+str(year)+r'(?:/loc/[^/]+)?/(poster|oral|spotlight)/(\d+)/?',p.path)
        if p.hostname==urlparse(page_url).hostname and m:
            key=m[2]
            title=clean(a.text_content())
            if title and title.casefold() not in ('login','poster','oral','spotlight'):
                items[key]={'event_id':int(key),'title':title,'source_url':canonical_detail(url),'presentation':m[1]}
    locations=[]
    for a in doc.xpath('//a[@href]'):
        u=urljoin(page_url,a.get('href').strip()).split('#',1)[0];p=urlparse(u)
        if p.hostname==urlparse(page_url).hostname and re.fullmatch(r'/virtual/'+str(year)+r'/loc/[^/]+/papers.html',p.path):
            locations.append(u)
    return list(items.values()),list(dict.fromkeys(locations))


def parse_detail(body, url):
    doc=html.fromstring(body)
    works=[]
    for script in doc.xpath('//script[@type="application/ld+json"]/text()'):
        try:
            value=json.loads(script)
            candidates=value if isinstance(value,list) else value.get('@graph',[value])
            works += [x for x in candidates if isinstance(x,dict) and x.get('@type') in ('CreativeWork','ScholarlyArticle','Article')]
        except (ValueError,TypeError):
            continue
    work=works[0] if works else {}
    title=clean(work.get('name') or work.get('headline'))
    if not title:
        hs=[clean(x.text_content()) for x in doc.xpath('//h1|//h2')]
        hs=[x for x in hs if x and x.casefold() not in ('main navigation','navigation')]
        title=hs[-1] if hs else ''
    author=work.get('author') or []
    if isinstance(author,(str,dict)):author=[author]
    authors=[clean(a.get('name')) if isinstance(a,dict) else clean(a) for a in author]
    abs_nodes=doc.xpath('//*[@id="abstractText"]//*[contains(concat(" ",normalize-space(@class)," ")," abstract-text-inner ")] | //*[@id="abstractText" and not(.//*[contains(@class,"abstract-text-inner")])]')
    if not abs_nodes:abs_nodes=doc.xpath('//*[contains(concat(" ",normalize-space(@class)," ")," abstract-text-inner ")]')
    if not abs_nodes:abs_nodes=doc.xpath('//*[@id="abstract"]')
    abstract=clean(abs_nodes[0].text_content()) if abs_nodes else clean(work.get('abstract') or work.get('description'))
    forum=next((forum_id(a.get('href')) for a in doc.xpath('//a[@href]') if forum_id(a.get('href'))),'')
    result={'title':title,'authors':authors,'abstract':abstract,'openreview_id':forum or None,'source_url':url,'track':'unknown','decision':'unknown','parser':'jsonld-and-dedicated-abstract-v1'}
    # Restrict track evidence to explicit document/paper attributes. Navigation is never evidence.
    for element in doc.xpath('//meta[@name="paper-track"] | //article[@data-track] | //*[@itemscope and contains(@itemtype,"schema.org/ScholarlyArticle") and @data-track]'):
        label=element.get('data-track') or element.get('content') or ''
        mapping={'main':'main','main track':'main','position':'position','position paper track':'position','datasets and benchmarks':'datasets_benchmarks','evaluations and datasets':'datasets_benchmarks','workshop':'workshop'}
        if label.casefold() in mapping:
            result.update(track=mapping[label.casefold()],track_evidence={'source_url':url,'attribute':'data-track/paper-track','value':label})
    return result


def _checkpoint(out, plan, attempts, patches, directory_papers, reconciliation):
    d=out/'details'
    write_jsonl(d/'attempts.jsonl',attempts)
    write_jsonl(d/'patches.jsonl',patches)
    write_jsonl(d/'directory_papers.jsonl',directory_papers)
    write_csv(d/'reconciliation.csv',reconciliation)
    done={r['paper_id'] for r in attempts}
    good={r['paper_id'] for r in attempts if r['status']=='success'}
    failed=[r for r in attempts if r['status']!='success']
    write_csv(d/'failed_urls.csv',failed, ['paper_id','source_url','status','error','attempted_at'])
    main_ids={r['paper_id'] for r in plan if r['reason']=='main_missing_abstract'}
    repaired={p['paper_id'] for p in patches if p.get('abstract') and p.get('title_match') and p['paper_id'] in main_ids}
    summary={'updated_at':utcnow(),'status':'completed' if len(done)==len(plan) else 'running','planned':len(plan),'attempted':len(done),'successful':len(good),'failed':len(failed),'remaining':len(plan)-len(done),'main_missing_planned':len(main_ids),'main_repaired':len(repaired),'main_abstract_repair_rate':len(repaired)/len(main_ids) if main_ids else None,'directory_new_papers':len(directory_papers),'plan_sha256':sha256(d/'plan.jsonl'),'counts_by_reason':dict(Counter(r['reason'] for r in plan)),'failure_note':'Every failed URL retained; terminal attempts do not imply successful coverage. No OpenReview requests made.'}
    write_json(d/'summary.json',summary)
    return summary


def backfill(config, output, retry_failed=False):
    out=Path(output);d=out/'details';d.mkdir(parents=True,exist_ok=True)
    http_config=dict(config.get('http',{}))
    try:
        import requests
        http_config['connection_pool']=True
    except ImportError:
        pass
    client=HttpClient(out,http_config)
    base=read_jsonl(out/'processed/papers.jsonl')
    if not base:raise RuntimeError('Run prepare before backfill')
    bulk_base=read_jsonl(out/'bulk/papers.jsonl') or base
    scope=read_json(out/'collection_scope.json',{}).get('sha256')
    previous_scope=read_json(d/'scope.json',{}).get('collection_scope_sha256')
    if previous_scope is not None and previous_scope!=scope:
        raise RuntimeError('Different collection scope requires a new details output directory')
    write_json(d/'scope.json',{'collection_scope_sha256':scope})
    lookup={p['paper_id']:p for p in base}
    plan=[];reconciliation=[];directory_papers=[];raw_items=[]
    known_ids={(p['venue'],p['year'],str(eid)) for p in bulk_base for eid in p['metadata'].get('event_ids',[])}
    for p in base:
        if p['track']=='main' and p['decision']=='accepted' and not p['abstract']:
            plan.append({'paper_id':p['paper_id'],'source_url':canonical_detail(p['source_url']),'title':p['title'],'venue':p['venue'],'year':p['year'],'reason':'main_missing_abstract'})
    for venue in config['venues']:
        for year in config['years']:
            root=f'https://{venue.lower()}.cc/virtual/{year}/papers.html'
            queue=[root];seen=set();all_items={};page_meta=[];errors=[]
            while queue:
                url=queue.pop(0)
                if url in seen:continue
                seen.add(url)
                try:
                    body,meta=client.fetch(url)
                    items,locations=directory_items(body,url,year)
                    page_meta.append(meta)
                    for item in items:
                        item.update(venue=venue,year=year,directory_url=url,directory_snapshot_sha256=meta['sha256'])
                        all_items[str(item['event_id'])]=item
                    queue.extend(u for u in locations if u not in seen)
                except Exception as e:errors.append({'url':url,'error':str(e)})
            known=[p for p in bulk_base if p['venue']==venue and p['year']==year]
            known_titles={title_key(p['title']) for p in known}
            missing=[r for eid,r in all_items.items() if (venue,year,eid) not in known_ids]
            for r in missing:
                p=event_to_paper({'id':r['event_id'],'name':r['title'],'authors':[],'virtualsite_url':r['source_url'],'eventtype':r['presentation']},venue,year)
                p['paper_id']=f'{venue}-{year}-directory-{r["event_id"]}'
                p['source']='official_live_directory'
                p['track']='unknown';p['decision']='unknown'
                p['metadata'].update(directory_snapshot_sha256=r['directory_snapshot_sha256'],directory_url=r['directory_url'],collection_stage='directory',same_title_seen_in_bulk=title_key(p['title']) in known_titles)
                directory_papers.append(p);lookup[p['paper_id']]=p
                plan.append({'paper_id':p['paper_id'],'source_url':r['source_url'],'title':r['title'],'venue':venue,'year':year,'reason':'directory_missing_from_bulk'})
            raw_items+=list(all_items.values())
            directory_titles={title_key(r['title']) for r in all_items.values()}
            reconciliation.append({'venue':venue,'year':year,'directory_events':len(all_items),'bulk_events':sum(len(p['metadata']['event_ids']) for p in known),'directory_absent_from_bulk_events':len(missing),'bulk_title_not_in_directory':sum(title_key(p['title']) not in directory_titles for p in known),'new_titles_vs_bulk':sum(title_key(r['title']) not in known_titles for r in missing),'pages':list(seen),'page_snapshot_hashes':[m['sha256'] for m in page_meta],'errors':errors,'status':'success' if not errors else 'partial'})
    # No duplicate-location URLs; different paper identities remain separate unless title+authors later agree.
    # Preserve prior tasks after prepare has filled their abstracts. Rebuilding
    # from only the remaining holes would delete the evidence needed to rebuild.
    previous_plan=read_jsonl(d/'plan.jsonl')
    tasks={r['paper_id']:r for r in previous_plan}
    for task in plan:
        if task['paper_id'] not in tasks:tasks[task['paper_id']]=task
    plan=list(tasks.values())
    write_jsonl(d/'plan.jsonl',plan);write_jsonl(d/'directory_items.jsonl',raw_items)
    old_attempts=read_jsonl(d/'attempts.jsonl');old_patches=read_jsonl(d/'patches.jsonl')
    # A completed attempt is resumable including explicit terminal missing/failed states.
    planned_ids={r['paper_id'] for r in plan}
    attempts=[r for r in old_attempts if r['paper_id'] in planned_ids]
    patches=[r for r in old_patches if r['paper_id'] in planned_ids]
    if retry_failed:
        retry_ids={r['paper_id'] for r in attempts if r['status'] in ('failed','missing_abstract')}
        history=read_jsonl(d/'attempts_history.jsonl')
        history += [r for r in attempts if r['paper_id'] in retry_ids]
        write_jsonl(d/'attempts_history.jsonl',history)
        attempts=[r for r in attempts if r['paper_id'] not in retry_ids]
        patches=[r for r in patches if r['paper_id'] not in retry_ids]
    done={r['paper_id'] for r in attempts}
    def one(task):
        attempt={**task,'attempted_at':utcnow()}
        try:
            body,meta=client.fetch(task['source_url'])
            patch=parse_detail(body,task['source_url']);patch.update(paper_id=task['paper_id'],snapshot_sha256=meta['sha256'],snapshot_body_path=meta['body_path'],collected_at=meta['collected_at'])
            patch['title_match']=bool(patch['title']) and title_key(patch['title'])==title_key(task['title'])
            if not patch['title_match']:
                attempt.update(status='title_conflict',error='Detail title does not match requested paper',found_title=patch['title'])
            elif not patch['abstract']:
                attempt.update(status='missing_abstract',error='No dedicated abstract node or JSON-LD abstract')
            else:
                attempt.update(status='success',abstract_chars=len(patch['abstract']),snapshot_sha256=meta['sha256'])
            return attempt,patch
        except Exception as e:
            attempt.update(status='blocked' if getattr(e,'challenge',False) else 'failed',error=str(e))
            return attempt,None
    remaining=[r for r in plan if r['paper_id'] not in done]
    directory_index={p['paper_id']:p for p in directory_papers}
    for patch in patches:
        if patch.get('title_match') and patch['paper_id'] in directory_index:
            paper=directory_index[patch['paper_id']]
            paper['authors']=patch.get('authors',[])
            paper['openreview_id']=patch.get('openreview_id')
            paper['abstract']=patch.get('abstract','')
            paper['metadata']['detail_snapshot_sha256']=patch.get('snapshot_sha256')
            if patch.get('track_evidence'):
                paper['track']=patch['track'];paper['track_evidence']=patch['track_evidence']
    summary=_checkpoint(out,plan,attempts,patches,directory_papers,reconciliation)
    print(json.dumps(summary,ensure_ascii=False),flush=True)
    def accept(attempt,patch):
        attempts.append(attempt)
        if patch:
            patches.append(patch)
            if patch.get('title_match') and patch['paper_id'] in directory_index:
                p=directory_index[patch['paper_id']]
                p['authors']=patch['authors'];p['openreview_id']=patch.get('openreview_id')
                # Preserve directory identity until ordinary conservative prepare merge.
                if patch.get('abstract'):p['abstract']=patch['abstract']
                if patch.get('track_evidence'):p['track']=patch['track'];p['track_evidence']=patch['track_evidence']
                p['metadata']['detail_snapshot_sha256']=patch['snapshot_sha256']
    # Bound requests in batches, prioritize main holes before unknown directory additions.
    workers=int(config.get('http',{}).get('workers',3))
    for start in range(0,len(remaining),75):
        batch=remaining[start:start+75]
        with ThreadPoolExecutor(max_workers=workers) as executor:
            for fut in as_completed([executor.submit(one,t) for t in batch]):
                accept(*fut.result())
                if len(attempts)%25==0:
                    summary=_checkpoint(out,plan,attempts,patches,directory_papers,reconciliation)
                    print(json.dumps(summary,ensure_ascii=False),flush=True)
        summary=_checkpoint(out,plan,attempts,patches,directory_papers,reconciliation)
    return summary
