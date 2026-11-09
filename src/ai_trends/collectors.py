"""Public official programs and OpenReview; no authentication or challenge bypass."""
from __future__ import annotations
import json
import re
from pathlib import Path
from urllib.parse import urljoin, urlencode
from .common import HttpClient, FetchError, read_json, read_jsonl, write_json, write_jsonl, write_csv, utcnow, sha256
from .processing import event_to_paper, merge_papers, decision_from_text, clean


def unwrap(value):
    return value.get('value') if isinstance(value, dict) and 'value' in value else value


def discover_urls(page, page_url):
    found = re.findall(r'''[^\s'"<>]*?(?:orals-posters|abstracts)[^\s'"<>]*?\.json[^\s'"<>]*''', page)
    return list(dict.fromkeys(urljoin(page_url, x.replace('&amp;', '&')) for x in found))


def fetch_pages(client, url, collection='results'):
    rows, metas, seen = [], [], set()
    expected = None
    while url:
        if url in seen:
            raise RuntimeError('Pagination cycle')
        seen.add(url)
        body, meta = client.fetch(url)
        data = json.loads(body)
        start=len(rows)
        if isinstance(data, list):
            rows.extend(data)
            metas.append({**meta,'record_start':start,'record_end':len(rows)})
            break
        if collection not in data:
            raise RuntimeError(f'Missing collection {collection}')
        rows.extend(data[collection])
        metas.append({**meta,'record_start':start,'record_end':len(rows)})
        if expected is None:
            expected=data.get('count')
        url=urljoin(url, data['next']) if data.get('next') else None
    return rows, metas, expected


def _public(entity):
    readers=entity.get('readers')
    return isinstance(readers,list) and 'everyone' in readers


def _public_content(entity):
    """Field readers may be more restrictive than an otherwise public note."""
    return {k:unwrap(v) for k,v in entity.get('content',{}).items() if not isinstance(v,dict) or 'readers' not in v or _public(v)}


def _public_note(note):
    if not _public(note):return None
    public=dict(note)
    public['content']={k:v for k,v in note.get('content',{}).items() if not isinstance(v,dict) or 'readers' not in v or _public(v)}
    if isinstance(note.get('details'),dict):
        public['details']={key:[r for n in note['details'][key] if (r:=_public_note(n)) is not None] for key in ('directReplies','replies') if isinstance(note['details'].get(key),list)}
    return public


def _invitation_ids(note):
    invitations=note.get('invitations') or []
    if isinstance(invitations,str):invitations=[invitations]
    if note.get('invitation'):invitations=list(invitations)+[note['invitation']]
    return list(dict.fromkeys(x for x in invitations if isinstance(x,str)))


def _api_json(client,base,resource,params):
    url=base+'/'+resource+'?'+urlencode(params,doseq=True)
    try:body,meta=client.fetch(url)
    except FetchError as e:
        e.request_url=url
        if e.status in (401,403):e.challenge=True
        raise
    data=json.loads(body)
    if isinstance(data,dict) and data.get('name')=='ChallengeRequiredError':
        error=FetchError('ChallengeRequiredError',403,True);error.request_url=url;raise error
    return data,meta


def get_openreview_group(client,group_id):
    """Fallback only for absent API2 groups; never bypass platform verification."""
    for base in ('https://api2.openreview.net','https://api.openreview.net'):
        try:data,meta=_api_json(client,base,'groups',{'id':group_id})
        except FetchError as e:
            if e.challenge or e.status!=404 or base=='https://api.openreview.net':raise
            continue
        groups=[g for g in data.get('groups',[]) if g.get('id')==group_id]
        if groups:
            if not _public(groups[0]):raise RuntimeError('Conference group is not explicitly public')
            return groups[0],base,meta
        if base=='https://api.openreview.net':return None,base,meta
    return None,None,None


def fetch_openreview_notes(client,base,params,page_size=1000,on_page=None):
    """End only at an empty cursor page, not short pages or page-local counts."""
    if not isinstance(page_size,int) or not 1<=page_size<=1000:raise ValueError('OpenReview page_size must be between 1 and 1000')
    params={**params,'limit':page_size,'sort':'id:asc'}
    rows=[];metas=[];ids=set();cursors=set();cursor=None;announced=None;duplicates=0
    while True:
        data,meta=_api_json(client,base,'notes',{**params,**({'after':cursor} if cursor else {})})
        notes=data.get('notes')
        if not isinstance(notes,list):raise RuntimeError('OpenReview notes response lacks a notes array')
        if announced is None and isinstance(data.get('count'),int):announced=data['count']
        start=len(rows)
        for note in notes:
            note_id=note.get('id')
            if not note_id:raise RuntimeError('OpenReview note lacks ID')
            if note_id not in ids:rows.append(note);ids.add(note_id)
            else:duplicates+=1
        meta={**meta,'record_start':start,'record_end':len(rows),'cursor':cursor}
        metas.append(meta)
        if on_page:on_page(notes,meta)
        if not notes:break
        next_cursor=notes[-1]['id']
        if next_cursor in cursors or next_cursor==cursor:raise RuntimeError('OpenReview cursor cycle/no progress')
        cursors.add(next_cursor);cursor=next_cursor
    return rows,metas,{'traversal_complete':True,'announced_count':announced,'unique_note_count':len(rows),'duplicate_note_count':duplicates,'count_matches':announced is None or announced==len(rows),'pages':len(metas)}


def _score_number(value):
    value=unwrap(value)
    if value is None or isinstance(value,bool):return None
    match=re.match(r'^\s*([+-]?(?:\d+(?:\.\d*)?|\.\d+))(?=\s*:|\s|$)',str(value))
    return float(match.group(1)) if match else None


def parse_score(raw,options=None):
    """Parse only the exact invitation's declared enum or numeric range."""
    value=_score_number(raw)
    if isinstance(options,dict) and options.get('kind')=='range':
        low,high=options['min'],options['max']
        valid=value is not None and low<=value<=high and (not options.get('integer') or value.is_integer())
        return value if valid else None,low,high
    allowed=[v for option in (options or []) if (v:=_score_number(option)) is not None]
    if not allowed:return None,None,None
    return value if value in allowed else None,min(allowed),max(allowed)


def _field_scale(field):
    if not isinstance(field,dict):return None
    for key in ('value-radio','value-dropdown'):
        if isinstance(field.get(key),list):return field[key]
    spec=field.get('value',field)
    if isinstance(spec,dict):spec=spec.get('param',spec)
    if not isinstance(spec,dict):return None
    if isinstance(spec.get('enum'),list):return spec['enum']
    bounds=spec.get('range')
    if isinstance(bounds,list) and len(bounds)==2 and all(isinstance(x,(int,float)) and not isinstance(x,bool) for x in bounds) and bounds[0]<bounds[1]:return {'kind':'range','min':bounds[0],'max':bounds[1],'integer':spec.get('type')=='integer'}
    return None


def score_schema_from_invitation(invitation,rating_field=None,confidence_field=None):
    """Read API2 note/edit templates or API1 reply schemas; never infer a scale."""
    candidates=[]
    if isinstance(invitation.get('reply'),dict):candidates.append(invitation['reply'].get('content'))
    edit=invitation.get('edit')
    if isinstance(edit,dict):
        candidates.append(edit.get('note',{}).get('content') if isinstance(edit.get('note'),dict) else None)
        child=edit.get('invitation')
        if isinstance(child,dict) and isinstance(child.get('edit'),dict):candidates.append(child['edit'].get('note',{}).get('content') if isinstance(child['edit'].get('note'),dict) else None)
    schema=next((c for c in candidates if isinstance(c,dict) and c),{})
    rating_fields=[rating_field] if rating_field else ['rating','overall_assessment','recommendation']
    confidence_fields=[confidence_field] if confidence_field else ['confidence']
    rating_name=next((f for f in rating_fields if f in schema),None)
    confidence_name=next((f for f in confidence_fields if f in schema),None)
    return {'rating':_field_scale(schema.get(rating_name)),'confidence':_field_scale(schema.get(confidence_name)),'rating_field':rating_name,'confidence_field':confidence_name,'source_invitation':invitation.get('id')}


def _reply_kind(note,review_names=None,decision_names=None):
    names={x.rsplit('/',1)[-1].casefold() for x in _invitation_ids(note)}
    formal={x.casefold() for x in (review_names or ['Official_Review','Review'])}
    decided={x.casefold() for x in (decision_names or ['Decision'])}
    if names & decided:return 'decision'
    if names & formal:return 'review'
    if any(n in ('rating','review_rating','review_quality','review_quality_rating') or n.endswith('_review_rating') for n in names):return 'review_quality'
    return 'other'


def parse_public_replies(notes,venue,year,score_options=None,review_names=None,decision_names=None,decision_field='decision'):
    reviews=[];decisions=[];quality_ratings=[]
    for note in notes:
        if not _public(note) or not note.get('id'):continue
        content=_public_content(note);invitations=_invitation_ids(note);kind=_reply_kind(note,review_names,decision_names)
        url='https://openreview.net/forum?'+urlencode({'id':note.get('forum',''),'noteId':note['id']})
        timestamp=note.get('tmdate',note.get('mdate'))
        if kind=='decision' and decision_field in content:
            decisions.append({'note_id':note['id'],'venue':venue,'year':year,'forum':note.get('forum'),'decision':decision_from_text(content[decision_field]),'decision_raw':content[decision_field],'updated_at':timestamp,'source_url':url,'raw_invitation':invitations})
        elif kind=='review':
            schema=score_options or {};by_invitation=schema.get('by_invitation')
            if isinstance(by_invitation,dict):schema=next((by_invitation[i] for i in invitations if i in by_invitation),{})
            rating_field=schema.get('rating_field') or next((f for f in ('rating','overall_assessment','recommendation') if f in content),None)
            confidence_field=schema.get('confidence_field') or 'confidence'
            rating_raw=content.get(rating_field)
            rating,lo,hi=parse_score(rating_raw,schema.get('rating'))
            confidence,_,_=parse_score(content.get(confidence_field),schema.get('confidence'))
            reviews.append({'review_id':note['id'],'paper_id':f'{venue}-{year}-or-'+note['forum'] if note.get('forum') else None,'venue':venue,'year':year,'forum':note.get('forum'),'rating_raw':rating_raw,'rating':rating,'confidence':confidence,'scale_min':lo,'scale_max':hi,'score_stage':'public_latest_official_review','source_url':url,'updated_at':timestamp,'raw_invitation':invitations,'score_schema':schema,'rating_field':rating_field,'confidence_field':confidence_field})
        elif kind=='review_quality':quality_ratings.append({'note_id':note['id'],'venue':venue,'year':year,'content':content,'forum':note.get('forum'),'replyto':note.get('replyto'),'updated_at':timestamp,'source_url':url,'classification':'review_quality_rating_not_paper_score'})
    return reviews,decisions,quality_ratings


def _timestamp(row):
    value=row.get('updated_at',row.get('tmdate',row.get('mdate')))
    if value is None and isinstance(row.get('note'),dict):value=row['note'].get('tmdate',row['note'].get('mdate'))
    try:return (1,float(value))
    except (TypeError,ValueError):return (0,str(value or ''))


def _unique_latest(rows,key):
    result={}
    for row in rows:
        identity=key(row)
        if identity is None:continue
        if identity not in result or _timestamp(row)>=_timestamp(result[identity]):result[identity]=row
    return list(result.values())


def openreview_note_to_paper(note,venue,year,group,decisions=None,snapshot=None):
    """Normalize explicit public status/track facts; ambiguous states stay unknown."""
    if not _public(note) or not note.get('id'):return None
    content=_public_content(note);group_content=_public_content(group);group_id=group['id'];forum=note.get('forum') or note['id']
    accepted_ids={group_id}
    accepted_id=group_content.get('accepted_venue_id')
    if isinstance(accepted_id,str):accepted_ids.add(accepted_id)
    venue_id=content.get('venueid')
    status_ids={group_content.get(k):v for k,v in [('submission_venue_id','under_review'),('rejected_venue_id','rejected'),('withdrawn_venue_id','withdrawn'),('desk_rejected_venue_id','desk_rejected')] if group_content.get(k)}
    mapped='accepted' if venue_id in accepted_ids else status_ids.get(venue_id,'unknown')
    related=[d for d in (decisions or []) if d.get('forum')==forum]
    latest=max(related,key=_timestamp) if related else None
    decided=latest.get('decision','unknown') if latest else 'unknown'
    conflict=mapped not in ('unknown','under_review') and decided not in ('unknown',mapped)
    decision='unknown' if conflict else decided if decided!='unknown' else mapped
    explicit_track=clean(content.get('track') or content.get('track_name')).casefold()
    mapping={'main':'main','main track':'main','position':'position','position papers':'position','datasets_benchmarks':'datasets_benchmarks','datasets and benchmarks':'datasets_benchmarks','evaluations and datasets':'datasets_benchmarks','workshop':'workshop'}
    title=clean(content.get('title'))
    if explicit_track in mapping:
        track=mapping[explicit_track];track_evidence={'field':'content.track','value':explicit_track,'group':group_id}
    elif re.match(r'^Position(?:\s+Paper)?\s*:',title,re.I):
        track='position';track_evidence={'field':'content.title','value':title,'group':group_id,'rule':'explicit Position title marker'}
    elif any(x in group_id.casefold() for x in ('datasets_and_benchmarks','evaluations_and_datasets')):
        track='datasets_benchmarks';track_evidence={'field':'group.id','value':group_id}
    elif '/workshop' in group_id.casefold():
        track='workshop';track_evidence={'field':'group.id','value':group_id}
    elif venue_id in accepted_ids and group_id.casefold()==f'{venue}.cc/{year}/Conference'.casefold():
        track='main';track_evidence={'field':'content.venueid','value':venue_id,'declared_accepted_group':group_id,'rule':'exact accepted venue ID in public conference group'}
    elif decision=='accepted' and latest and group_id.casefold()==f'{venue}.cc/{year}/Conference'.casefold():
        track='main';track_evidence={'field':'public_decision','value':latest,'declared_submission_invitation':group_content.get('submission_id'),'group':group_id}
    else:
        track='unknown';track_evidence={'field':'content.venueid','value':venue_id,'group':group_id,'rule':'insufficient explicit per-paper main evidence'}
    authors=content.get('authors') or []
    if isinstance(authors,str):authors=[authors]
    authors=[clean(a) for a in authors if isinstance(a,str) and clean(a)]
    keywords=content.get('keywords') or []
    if isinstance(keywords,str):keywords=[clean(k) for k in re.split(r'[,;]',keywords) if clean(k)]
    keywords=[clean(k) for k in keywords if isinstance(k,str) and clean(k)]
    source_url='https://openreview.net/forum?'+urlencode({'id':forum})
    metadata={'event_ids':[],'official_uids':[],'source_groups':[group_id],'source_ids':[note['id']],'detail_urls':[source_url],'source_snapshots':[snapshot] if snapshot else [],'raw_decisions':[d.get('decision_raw') for d in related],'collection_stage':'openreview_public','raw_venueid':venue_id,'raw_venue':content.get('venue'),'note_invitations':_invitation_ids(note),'updated_at':note.get('tmdate',note.get('mdate')),'decision_conflict':conflict,'complete_decision_cohort':False}
    return {'paper_id':f'{venue}-{year}-or-{forum}','venue':venue,'year':int(year),'title':title,'abstract':clean(content.get('abstract')),'authors':authors,'keywords':keywords,'source':'openreview_public','source_id':note['id'],'source_url':source_url,'openreview_id':forum,'track':track,'track_evidence':track_evidence,'decision':decision,'presentation':[],'text_version':'openreview_public_latest_submission','collected_at':snapshot.get('collected_at') if snapshot else utcnow(),'metadata':metadata}


def _review_schemas(client,base,group,replies):
    content=_public_content(group)
    review_names=[content.get('review_name') or 'Official_Review','Review']
    formal={n.casefold() for n in review_names}
    ids=sorted({i for r in replies if _public(r) and _reply_kind(r,review_names)=='review' for i in _invitation_ids(r) if i.startswith(group['id']+'/') and i.rsplit('/',1)[-1].casefold() in formal})
    schemas={};snapshots=[];warnings=[]
    # Fetch the exact per-paper invitations. API2 supports a bounded IDs batch.
    batch_size=40 if base=='https://api2.openreview.net' else 1
    for start in range(0,len(ids),batch_size):
        batch=ids[start:start+batch_size]
        query={'ids':batch,'limit':len(batch)} if batch_size>1 else {'id':batch[0]}
        try:data,meta=_api_json(client,base,'invitations',query)
        except FetchError as e:
            if e.challenge:raise
            warnings.append({'invitation_ids':batch,'error':str(e),'status':e.status});continue
        snapshots.append(meta)
        returned={i['id']:i for i in data.get('invitations',[]) if i.get('id') in batch and _public(i)}
        for invitation_id in batch:
            invitation=returned.get(invitation_id)
            if invitation is None:
                warnings.append({'invitation_id':invitation_id,'reason':'Exact public invitation schema unavailable'});continue
            schema=score_schema_from_invitation(invitation,content.get('review_rating'),content.get('review_confidence'))
            schema['snapshot_sha256']=meta['sha256'];schemas[invitation_id]=schema
    return {'by_invitation':schemas},snapshots,warnings


def collect_openreview(client,config,out,coverage):
    out=Path(out);state=read_json(out/'openreview_state.json',{})
    page_size=config.get('openreview',{}).get('page_size',1000)
    cohort_root=out/'bulk/openreview'
    for row in coverage:
        venue,year=row['venue'],row['year'];group_id=f'{venue}.cc/{year}/Conference';cohort=cohort_root/f'{venue}-{year}'
        status={'venue':venue,'year':year,'group':group_id,'submission_count':0,'review_count':0,'decision_count':0,'complete_decision_cohort':False,'sample_limit':None,'live_retry_performed':False}
        if state.get('blocked'):
            previous=read_json(cohort/'checkpoint.json',{})
            status.update(submission_count=previous.get('submission_count',0),review_count=previous.get('review_count',0),decision_count=previous.get('decision_count',0),status='blocked',reason='Same-run OpenReview channel halted after platform verification',blocked_at=state.get('blocked_at'),trigger_url=state.get('trigger_url'),retained_prior_public_records=bool(previous))
            row['openreview']=status;continue
        group=None;notes_wrapped=[];all_note_ids=set()
        try:
            status['live_retry_performed']=True
            group,base,group_meta=get_openreview_group(client,group_id)
            if group is None:
                status.update(status='unavailable',reason='Public conference group absent in API2 and API1')
                row['openreview']=status;write_json(cohort/'checkpoint.json',status);continue
            content=_public_content(group)
            status.update(group_config=content,group_snapshot_sha256=group_meta['sha256'],api_version=2 if base=='https://api2.openreview.net' else 1)
            write_json(cohort/'group.json',{'group':group,'snapshot':group_meta,'api_base':base})
            invitations=[]
            for field in ('submission_id','blind_submission_id','submission_invitation','blind_submission_invitation'):
                value=content.get(field)
                if isinstance(value,str) and value.startswith(group_id+'/'):invitations.append(value)
            if not invitations and content.get('submission_name'):invitations.append(group_id+'/-/'+content['submission_name'])
            invitations=list(dict.fromkeys(invitations))
            if not invitations:
                status.update(status='unavailable',reason='Group does not declare a submission invitation/name')
                row['openreview']=status;write_json(cohort/'checkpoint.json',status);continue
            status['submission_invitations']=invitations
            notes_wrapped=[];all_note_ids=set();traversals=[];page_metas=[]
            def persist_page(notes,meta):
                page_metas.append(meta);all_note_ids.update(n.get('id') for n in notes if n.get('id'))
                for note in notes:
                    public=_public_note(note)
                    if public is not None:notes_wrapped.append({'venue':venue,'year':year,'note':public,'snapshot':meta,'api_version':status['api_version']})
                unique=_unique_latest(notes_wrapped,lambda r:r['note']['id'])
                write_jsonl(cohort/'submissions.jsonl',unique)
                write_json(cohort/'pagination_checkpoint.json',{'status':'running','public_unique_notes':len(unique),'queried_unique_notes':len(all_note_ids),'page_snapshots':page_metas,'complete_decision_cohort':False})
            for invitation in invitations:
                notes,metas,info=fetch_openreview_notes(client,base,{'invitation':invitation,'details':'replies,directReplies'},page_size,persist_page)
                traversals.append({'invitation':invitation,**info})
            notes_wrapped=_unique_latest(notes_wrapped,lambda r:r['note']['id'])
            replies=[]
            for wrapped in notes_wrapped:
                details=wrapped['note'].get('details',{});replies.extend(details.get('replies',[]));replies.extend(details.get('directReplies',[]))
            replies=_unique_latest(replies,lambda r:r.get('id'))
            review_names=[content.get('review_name') or 'Official_Review','Review'];decision_names=[content.get('decision_name') or 'Decision'];decision_field=content.get('decision_field_name') or 'decision'
            # Persist notes and decisions before fetching schemas; a challenge in
            # that later request must not erase successfully retrieved pages.
            initial_reviews,decisions,quality=parse_public_replies(replies,venue,year,{},review_names,decision_names,decision_field)
            papers=[p for wrapped in notes_wrapped if (p:=openreview_note_to_paper(wrapped['note'],venue,year,group,decisions,wrapped['snapshot'])) is not None]
            write_jsonl(cohort/'papers.jsonl',papers);write_jsonl(cohort/'decisions.jsonl',decisions);write_jsonl(cohort/'quality.jsonl',quality);write_jsonl(cohort/'reviews.jsonl',initial_reviews)
            status.update(submission_count=len(notes_wrapped),queried_note_count=len(all_note_ids),excluded_not_public=len(all_note_ids)-len(notes_wrapped),review_count=len(initial_reviews),decision_count=len(decisions),submission_traversals=traversals,submission_traversal_complete=all(t['traversal_complete'] for t in traversals),source_page_snapshots=page_metas)
            schemas,schema_snapshots,schema_warnings=_review_schemas(client,base,group,replies)
            write_json(cohort/'review_schemas.json',{'schemas':schemas,'source_snapshots':schema_snapshots,'warnings':schema_warnings})
            reviews,decisions,quality=parse_public_replies(replies,venue,year,schemas,review_names,decision_names,decision_field)
            write_jsonl(cohort/'reviews.jsonl',reviews)
            status.update(status='public_sample' if all(t['count_matches'] for t in traversals) else 'partial_public_sample',review_count=len(reviews),decision_count=len(decisions),review_schemas_available=len(schemas['by_invitation']),valid_rating_count=sum(r['rating'] is not None for r in reviews),schema_warnings=schema_warnings,reason='Public invitation traversal is audited; public visibility does not prove all original submissions or a complete decision cohort')
            write_json(cohort/'pagination_checkpoint.json',{'status':'completed','public_unique_notes':len(notes_wrapped),'queried_unique_notes':len(all_note_ids),'page_snapshots':page_metas,'traversals':traversals,'complete_decision_cohort':False})
        except FetchError as e:
            if group and notes_wrapped and not status.get('submission_traversal_complete'):
                # A later notes page may challenge. Preserve the already public
                # pages as a partial, explicitly blocked sample, without making
                # any invitation/API fallback requests after the challenge.
                retained=_unique_latest(notes_wrapped,lambda r:r['note']['id'])
                replies=[]
                for wrapped in retained:
                    details=wrapped['note'].get('details',{})
                    replies+=details.get('replies',[])+details.get('directReplies',[])
                replies=_unique_latest(replies,lambda r:r.get('id'))
                content=_public_content(group)
                rv,dc,qr=parse_public_replies(replies,venue,year,{},[content.get('review_name') or 'Official_Review','Review'],[content.get('decision_name') or 'Decision'],content.get('decision_field_name') or 'decision')
                papers=[p for wrapped in retained if (p:=openreview_note_to_paper(wrapped['note'],venue,year,group,dc,wrapped['snapshot'])) is not None]
                for filename,records in [('papers.jsonl',papers),('reviews.jsonl',rv),('decisions.jsonl',dc),('quality.jsonl',qr)]:
                    write_jsonl(cohort/filename,records)
                status.update(submission_count=len(retained),review_count=len(rv),decision_count=len(dc),queried_note_count=len(all_note_ids),excluded_not_public=len(all_note_ids)-len(retained),submission_traversal_complete=False,retained_partial_public_sample=True)
            status.update(status='blocked' if e.challenge else 'failed',reason=str(e))
            if e.challenge:
                state={'blocked':True,'blocked_at':utcnow(),'trigger_url':getattr(e,'request_url',None),'reason':str(e)}
                write_json(out/'openreview_state.json',state);status.update(blocked_at=state['blocked_at'],trigger_url=state['trigger_url'])
        except Exception as e:status.update(status='failed',reason=repr(e))
        row['openreview']=status;write_json(cohort/'checkpoint.json',status);write_json(out/'source_coverage.json',coverage)
    # A blocked restart preserves earlier public records; no zero overwrite.
    routes=[('openreview_submissions.jsonl','submissions.jsonl',lambda r:(r.get('venue'),r.get('year'),r.get('note',{}).get('id'))),('openreview_papers.jsonl','papers.jsonl',lambda r:r.get('paper_id')),('reviews.jsonl','reviews.jsonl',lambda r:r.get('review_id')),('decisions.jsonl','decisions.jsonl',lambda r:(r.get('venue'),r.get('year'),r.get('note_id'))),('review_quality_ratings.jsonl','quality.jsonl',lambda r:(r.get('venue'),r.get('year'),r.get('note_id')))]
    for global_name,cohort_name,key in routes:
        previous=read_jsonl(out/'bulk'/global_name)
        for path in sorted(cohort_root.glob('*/'+cohort_name)):previous+=read_jsonl(path)
        write_jsonl(out/'bulk'/global_name,_unique_latest(previous,key))
    return coverage


def collect(config, output):
    out=Path(output)
    client=HttpClient(out,config.get('http'))
    scope={k:config[k] for k in ('venues','years','http')}
    scope_hash=sha256(json.dumps(scope,sort_keys=True))
    existing=read_json(out/'collection_scope.json')
    if existing and existing['sha256']!=scope_hash:
        raise RuntimeError('Different collection scope/config requires another output directory')
    write_json(out/'collection_scope.json',{'sha256':scope_hash,'config':scope,'created_at':existing.get('created_at') if existing else utcnow()})
    coverage=[]
    all_events=[]
    all_papers=[]
    for venue in config['venues']:
        for year in config['years']:
            url=f'https://{venue.lower()}.cc/virtual/{year}/papers.html'
            row={'venue':venue,'year':year,'source_url':url,'status':'failed','sample_limit':None,'warnings':[],'list_events':0,'unique_papers':0,'main_papers':0,'with_abstract':0,'abstract_coverage':None}
            try:
                body,meta=client.fetch(url)
                links=discover_urls(body.decode('utf-8'),url)
                row.update(declared_json_urls=links,page_snapshot=meta)
                list_urls=[u for u in links if 'orals-posters' in u]
                if not list_urls:
                    raise RuntimeError('No official declared bulk list URL')
                events=[]
                snapshots=[]
                event_snap={}
                for list_url in list_urls:
                    es,ms,expected=fetch_pages(client,list_url)
                    events+=es
                    snapshots+=ms
                    for page in ms:
                        snapshot={k:v for k,v in page.items() if k not in ('record_start','record_end')}
                        for e in es[page['record_start']:page['record_end']]:
                            event_snap[str(e['id'])]=snapshot
                    if expected is not None and len(es)!=expected:
                        row['warnings'].append(f'count mismatch: {expected} announced versus {len(es)} fetched')
                abstracts={}
                abstract_snapshots=[]
                for abs_url in [u for u in links if 'abstracts' in u]:
                    try:
                        ab,am=client.fetch(abs_url)
                        abstracts.update(json.loads(ab))
                        abstract_snapshots.append(am)
                    except FetchError as e:
                        row['warnings'].append({'optional_abstract_url':abs_url,'status':e.status,'error':str(e),'embedded_abstracts_retained':True})
                cohort=[]
                for e in events:
                    event=dict(e)
                    mapped=abstracts.get(str(e['id']))
                    if not event.get('abstract') and mapped:
                        event['abstract']=mapped.get('abstract','') if isinstance(mapped,dict) else mapped
                    snapshot=event_snap.get(str(e['id']))
                    p=event_to_paper(event,venue,year,snapshot)
                    if mapped:
                        p['metadata']['abstract_mapping_snapshots']=[m['sha256'] for m in abstract_snapshots]
                    cohort.append(p)
                    all_events.append({'venue':venue,'year':year,'event':e,'snapshot':snapshot})
                unique,quarantine=merge_papers(cohort)
                all_papers+=unique
                write_jsonl(out/f'bulk/{venue}-{year}-papers.jsonl',unique)
                write_jsonl(out/f'bulk/{venue}-{year}-quarantine.jsonl',quarantine)
                row.update(status='success' if not any(isinstance(x,str) and x.startswith('count mismatch') for x in row['warnings']) else 'partial',list_events=len(events),unique_papers=len(unique),main_papers=sum(p['track']=='main' for p in unique),with_abstract=sum(bool(p['abstract']) for p in unique),abstract_coverage=sum(bool(p['abstract']) for p in unique)/len(unique) if unique else None,track_counts={t:sum(p['track']==t for p in unique) for t in sorted({p['track'] for p in unique})},list_snapshots=snapshots,abstract_snapshots=abstract_snapshots,quarantine_count=len(quarantine))
            except Exception as e:
                row.update(error=repr(e),status='blocked' if getattr(e,'challenge',False) else 'failed')
            coverage.append(row)
            write_json(out/f'bulk/{venue}-{year}-checkpoint.json',row)
            write_json(out/'source_coverage.json',coverage)
            print(f'{venue} {year}: {row["status"]}, events={row["list_events"]}, papers={row["unique_papers"]}, main={row["main_papers"]}',flush=True)
    write_jsonl(out/'bulk/events.jsonl',all_events)
    write_jsonl(out/'bulk/papers.jsonl',all_papers)
    write_csv(out/'bulk/papers.csv',all_papers)
    collect_openreview(client,config,out,coverage)
    write_json(out/'source_coverage.json',coverage)
    write_csv(out/'source_coverage.csv',coverage)
    write_json(out/'bulk/manifest.json',{'generated_at':utcnow(),'rows':len(all_papers),'events':len(all_events),'cohorts':len(coverage),'coverage':[{k:v for k,v in r.items() if k in ('venue','year','status','list_events','unique_papers','main_papers','openreview')} for r in coverage],'papers_sha256':sha256(out/'bulk/papers.jsonl'),'events_sha256':sha256(out/'bulk/events.jsonl'),'completeness_claim':'Only official declared batch endpoints traversed; details/directory reconciliation separate'})
    return {'cohorts':len(coverage),'papers':len(all_papers),'failed_cohorts':sum(r['status']!='success' for r in coverage),'openreview_statuses':[r['openreview']['status'] for r in coverage]}
