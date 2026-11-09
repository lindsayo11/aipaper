"""Normalize only supported facts; isolate identity conflicts before enrichment."""
from __future__ import annotations
from collections import Counter, defaultdict
import html
from pathlib import Path
import re
import unicodedata
from urllib.parse import parse_qs, urlparse, urljoin
from .common import read_json, read_jsonl, write_json, write_jsonl, write_csv, sha256, utcnow


def clean(value):
    if value is None:
        return ''
    text = html.unescape(str(value))
    text = re.sub(r'</?(?:p|div|span|br|strong|em|sup|sub|a|i|b|ul|li|ol|h[1-6])(?:\s[^>]*|\s*)/?>', ' ', text, flags=re.I)
    return re.sub(r'\s+', ' ', text).strip()


def title_key(text):
    return re.sub(r'[^\w]', '', unicodedata.normalize('NFKC', clean(text)).casefold())


def forum_id(url):
    p = urlparse(url or '')
    if p.hostname in ('openreview.net', 'www.openreview.net') and p.path in ('/forum', '/pdf'):
        value=parse_qs(p.query).get('id', [''])[0]
        if re.match(r'^\d{4}-(?:Oral|Poster|Spotlight)-',value,re.I):
            return ''
        return value
    return ''


def track_from_event(event, venue, year):
    group = parse_qs(urlparse(event.get('sourceurl') or '').query).get('id', [''])[0]
    label = ' '.join(str(event.get(k) or '') for k in ('track', 'track_name', 'sourceurl'))
    low = label.casefold()
    evidence = {'field': 'sourceurl', 'value': event.get('sourceurl'), 'rule': 'exact source group'}
    if 'workshop' in low or '/workshop' in group.casefold():
        return 'workshop', evidence
    if 'position' in low or re.match(r'^Position\s*:', clean(event.get('name')), re.I):
        return 'position', {'field': 'sourceurl/title', 'value': event.get('sourceurl'), 'title': event.get('name'), 'rule': 'explicit Position track or official Position: title marker'}
    if any(x in low for x in ('datasets_and_benchmarks','datasets and benchmarks','datasets_benchmarks','evaluations_and_datasets')):
        return 'datasets_benchmarks', evidence
    expected = f'{venue}.cc/{year}/Conference'
    if group.casefold() == expected.casefold():
        return 'main', evidence
    if str(event.get('track', '')).casefold() in ('main','main track'):
        return 'main', {'field':'track','value':event['track'],'rule':'explicit per-paper track'}
    return 'unknown', {'field': 'sourceurl', 'value': event.get('sourceurl'), 'rule': 'insufficient per-paper track evidence'}


def decision_from_text(value):
    t = clean(value).casefold()
    if 'desk' in t and 'reject' in t:
        return 'desk_rejected'
    if 'withdraw' in t:
        return 'withdrawn'
    if re.search(r'\breject(?:ed)?\b', t):
        return 'rejected'
    if re.search(r'\bnot\s+accept(?:ed)?\b', t):
        return 'rejected'
    if re.search(r'\baccept(?:ed)?\b', t):
        return 'accepted'
    if 'under review' in t or 'submission' in t:
        return 'under_review'
    return 'unknown'


def event_to_paper(event, venue, year, snapshot=None):
    authors = [clean(a.get('fullname') or a.get('name')) if isinstance(a, dict) else clean(a) for a in event.get('authors', [])]
    authors = [a for a in authors if a]
    title = clean(event.get('name') or event.get('title'))
    links = [event.get('paper_url'), event.get('url')] + [m.get('uri') for m in event.get('eventmedia', [])]
    forum = next((forum_id(u) for u in links if forum_id(u)), '')
    track, evidence = track_from_event(event, venue, year)
    group = event.get('sourceurl') or ''
    if forum:
        identity = 'or-' + forum
    elif group and event.get('sourceid') is not None:
        identity = 'src-' + sha256(group + ':' + str(event['sourceid']))[:20]
    elif event.get('uid'):
        identity = 'uid-' + event['uid']
    else:
        identity = 'ta-' + sha256(title_key(title) + '|' + '|'.join(sorted(a.casefold() for a in authors)))[:24]
    base = f'https://{venue.lower()}.cc'
    detail = urljoin(base, event.get('virtualsite_url') or f'/virtual/{year}/poster/{event.get("id")}')
    keywords = event.get('keywords') or []
    if isinstance(keywords, str):
        keywords = [clean(x) for x in re.split(r'[,;]', keywords) if clean(x)]
    metadata = {'event_ids': [event.get('id')], 'official_uids': [event.get('uid')], 'source_groups': [group], 'source_ids': [event.get('sourceid')], 'raw_decisions': [event.get('decision')], 'detail_urls': [detail], 'source_snapshots': [snapshot] if snapshot else [], 'event_topic': event.get('topic'), 'collection_stage': 'bulk'}
    return {'paper_id':f'{venue}-{year}-{identity}', 'venue':venue, 'year':int(year), 'title':title, 'abstract':clean(event.get('abstract')), 'authors':authors, 'keywords':keywords, 'source':'official_virtual_program', 'source_id':str(event.get('id')), 'source_url':detail, 'openreview_id':forum or None, 'track':track, 'track_evidence':evidence, 'decision':decision_from_text(event.get('decision')), 'presentation':[clean(event.get('event_type') or event.get('eventtype'))] if event.get('event_type') or event.get('eventtype') else [], 'text_version':'official_program', 'collected_at':snapshot.get('collected_at') if snapshot else utcnow(), 'metadata':metadata}


def merge_papers(papers):
    merged, quarantine = {}, []
    # Exact title+author fallback joins duplicated presentation events with no forum.
    aliases = {}
    forum_aliases = {}
    for p in papers:
        alias = (p['venue'], p['year'], title_key(p['title']), tuple(sorted(a.casefold() for a in p['authors'])))
        key = p['paper_id']
        exact_forum=(p['venue'],p['year'],p.get('openreview_id')) if p.get('openreview_id') else None
        if exact_forum in forum_aliases:
            key=forum_aliases[exact_forum]
        if key not in merged and alias in aliases:
            previous = merged[aliases[alias]]
            if not p.get('openreview_id') or not previous.get('openreview_id') or p['openreview_id'] == previous['openreview_id']:
                key = aliases[alias]
        if key not in merged:
            merged[key] = p
            aliases[alias] = key
            if exact_forum:
                forum_aliases[exact_forum]=key
            continue
        old = merged[key]
        if old.get('openreview_id') and p.get('openreview_id') and old['openreview_id'] != p['openreview_id']:
            quarantine.append({'reason':'same_identity_forum_conflict','paper_id':key,'incoming':p})
            continue
        if title_key(old['title']) != title_key(p['title']):
            quarantine.append({'reason':'same_identity_title_conflict', 'paper_id':key, 'kept_title':old['title'], 'incoming':p})
            continue
        if old['track'] != p['track'] and old['track'] != 'unknown' and p['track'] != 'unknown':
            quarantine.append({'reason':'same_identity_track_conflict','paper_id':key,'incoming':p})
            old['track'] = 'unknown'
            old['metadata']['track_conflict'] = True
        elif old['track'] == 'unknown' and p['track'] != 'unknown' and not old['metadata'].get('track_conflict'):
            old['track'], old['track_evidence'] = p['track'], p['track_evidence']
        if not old['abstract'] and p['abstract']:
            old['abstract'] = p['abstract']
        if not old.get('openreview_id') and p.get('openreview_id'):
            old['openreview_id'] = p['openreview_id']
        if old.get('openreview_id'):
            forum_aliases[(old['venue'],old['year'],old['openreview_id'])]=key
        if not old.get('authors') and p.get('authors'):
            old['authors'] = p['authors']
        if old['decision'] == 'unknown' and not old['metadata'].get('decision_conflict'):
            old['decision'] = p['decision']
        elif p['decision'] not in ('unknown',old['decision']):
            quarantine.append({'reason':'decision_conflict','paper_id':key,'incoming_decision':p['decision']})
            old['decision'] = 'unknown'
            old['metadata']['decision_conflict'] = True
        old['presentation'] = sorted(set(old['presentation'] + p['presentation']))
        for field in ('event_ids','official_uids','source_ids','source_groups','detail_urls','raw_decisions','source_snapshots'):
            target = old['metadata'].setdefault(field, [])
            for value in p['metadata'].get(field, []):
                if value not in target:
                    target.append(value)
    return list(merged.values()), quarantine


def apply_patches(papers, patches):
    indexed = {p['paper_id']:p for p in papers}
    quarantined = []
    for patch in patches:
        p = indexed.get(patch.get('paper_id'))
        if not p:
            continue
        if not patch.get('title') or title_key(p['title']) != title_key(patch['title']):
            quarantined.append({'reason':'detail_title_conflict','paper_id':p['paper_id'],'kept_title':p['title'],'patch':patch})
            continue
        if p.get('openreview_id') and patch.get('openreview_id') and p['openreview_id'] != patch['openreview_id']:
            quarantined.append({'reason':'detail_forum_conflict','paper_id':p['paper_id'],'patch':patch})
            continue
        # A requested event matching title is needed; URL alone is not an identity.
        if patch.get('abstract') and not p['abstract']:
            p['abstract'] = clean(patch['abstract'])
            p['metadata']['abstract_repair'] = {k:v for k,v in patch.items() if k!='abstract'}
        if patch.get('openreview_id') and not p.get('openreview_id'):
            p['openreview_id'] = patch['openreview_id']
        p['metadata'].setdefault('detail_attempts', []).append({k:v for k,v in patch.items() if k not in ('abstract','authors')})
        # Unknown directory entries may be promoted only by explicit per-paper evidence.
        if p['track'] == 'unknown' and not p['metadata'].get('track_conflict') and patch.get('track') in ('main','position','datasets_benchmarks','workshop') and patch.get('track_evidence'):
            p['track'],p['track_evidence'] = patch['track'],patch['track_evidence']
        if p['decision'] == 'unknown' and not p['metadata'].get('decision_conflict') and patch.get('decision') == 'accepted' and patch.get('decision_evidence'):
            p['decision'] = 'accepted'
    return papers, quarantined


def coverage_rows(papers, config):
    rows=[]
    for venue in config['venues']:
        for year in config['years']:
            ps=[p for p in papers if p['venue']==venue and p['year']==year]
            for track in ['all','main','position','datasets_benchmarks','workshop','unknown']:
                group=ps if track=='all' else [p for p in ps if p['track']==track]
                n=len(group); absn=sum(bool(p['abstract']) for p in group)
                rows.append({'venue':venue,'year':year,'track':track,'papers':n,'accepted':sum(p['decision']=='accepted' for p in group),'with_abstract':absn,'without_abstract':n-absn,'abstract_coverage':absn/n if n else None,'decisions':dict(Counter(p['decision'] for p in group))})
    return rows


def prepare(config, output, with_details=False):
    out=Path(output); inputs=[out/'bulk/papers.jsonl',out/'bulk/reviews.jsonl']
    ps=read_jsonl(inputs[0])
    if (out/'bulk/openreview_papers.jsonl').exists():
        ps += read_jsonl(out/'bulk/openreview_papers.jsonl')
        inputs.append(out/'bulk/openreview_papers.jsonl')
    papers, quarantine=merge_papers(ps)
    for quarantine_file in sorted((out/'bulk').glob('*-quarantine.jsonl')):
        quarantine += read_jsonl(quarantine_file)
        inputs.append(quarantine_file)
    if with_details:
        extras=read_jsonl(out/'details/directory_papers.jsonl')
        papers,q=merge_papers(papers+extras);quarantine+=q
        patches=read_jsonl(out/'details/patches.jsonl')
        papers,q=apply_patches(papers,patches);quarantine+=q
        inputs += [out/'details/directory_papers.jsonl',out/'details/patches.jsonl']
    papers.sort(key=lambda p:(p['venue'],p['year'],p['paper_id']))
    valid_ids={p['paper_id'] for p in papers}
    forum_map={(p['venue'],p['year'],p.get('openreview_id')):p['paper_id'] for p in papers if p.get('openreview_id')}
    reviews={}
    for r in read_jsonl(out/'bulk/reviews.jsonl'):
        if r.get('paper_id') not in valid_ids:
            r['paper_id']=forum_map.get((r.get('venue'),r.get('year'),r.get('forum')))
        if not r.get('paper_id'):
            quarantine.append({'reason':'review_without_matched_paper','review':r});continue
        previous=reviews.get(r['review_id'])
        if not previous or (r.get('updated_at') or 0) > (previous.get('updated_at') or 0):
            reviews[r['review_id']]=r
    processed=out/'processed'
    write_jsonl(processed/'papers.jsonl',papers);write_csv(processed/'papers.csv',papers)
    write_jsonl(processed/'reviews.jsonl',list(reviews.values()));write_jsonl(processed/'quarantine.jsonl',quarantine)
    coverage=coverage_rows(papers,config);write_csv(processed/'coverage.csv',coverage);write_json(processed/'coverage.json',coverage)
    main=[p for p in papers if p['track']=='main' and p['decision']=='accepted']
    quality={'generated_at':utcnow(),'paper_count':len(papers),'id_unique':len(valid_ids)==len(papers),'review_count':len(reviews),'quarantine_count':len(quarantine),'main_accepted':len(main),'main_missing_abstract':sum(not p['abstract'] for p in main),'model_eligible':sum(bool(p['title'] and p['abstract']) for p in main),'track_counts':dict(Counter(p['track'] for p in papers)),'decision_counts':dict(Counter(p['decision'] for p in papers)),'with_details':with_details,'input_hashes':{str(p.relative_to(out)):sha256(p) for p in inputs if p.exists()},'papers_sha256':sha256(processed/'papers.jsonl'),'title_conflicts_quarantined':sum('conflict' in q['reason'] for q in quarantine)}
    scoped_forums=[(p['venue'],p['year'],p['openreview_id']) for p in papers if p.get('openreview_id')]
    quality['forum_identity_unique']=len(scoped_forums)==len(set(scoped_forums))
    write_json(processed/'quality.json',quality)
    return quality
