"""Observed-acceptance trends and source-aware statistics, never inferred odds.

All model shares use observed accepted MAIN papers as denominator, including
those without abstracts. Public scores are paper-weighted within each scale and
stage. A public convenience sample never establishes a full decision cohort.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import math
import statistics

from .common import read_json, read_jsonl, write_json, write_csv, sha256, utcnow


STAT_FIELDS = ['venue','year','track','source_id','preferred','raw_submissions','valid_submissions','reported_submissions','reviewed','accepted','accepted_lower_bound','accepted_display','official_rate','official_rate_unit','official_rate_precision_digits','official_rate_rounding','computed_rate_percent','rate_denominator_count','denominator_definition','source_level','source_url','source_date','collected_at','approximate','notes','evidence_file','snapshot_sha256']
TREND_FIELDS = ['venue','year','topic_id','paper_count','observed_main_accepted','assigned_papers','missing_abstract','share','share_percent']
CHANGE_FIELDS = ['venue','topic_id','from_year','to_year','year_gap','from_count','to_count','from_denominator','to_denominator','from_share_percent','to_share_percent','delta_pp']
HEAT_FIELDS = ['year','venue','topic_id','paper_count','denominator','share','share_percent']
SCORE_FIELDS = ['venue','year','topic_id','scale_min','scale_max','score_stage','papers_with_reviews','mean_paper_rating']
DECISION_FIELDS = ['venue','year','total_public_papers','accepted','rejected','withdrawn','desk_rejected','under_review','unknown','independent_complete_decision_cohort','conditional_acceptance_rate','reason']
RECON_FIELDS = ['venue','year','source_id','official_accepted','official_accepted_lower_bound','observed_main_accepted','missing_abstract','assigned_papers','difference_observed_minus_official','coverage_ratio','source_url','source_level','preferred','approximate','status']


def _number(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _latest_key(review):
    value = review.get('updated_at')
    numeric = _number(value)
    return (1, numeric) if numeric is not None else (0, str(value or ''))


def aggregate_scores(papers, reviews, assignments):
    """Return equal-paper means; drop invalid scales/ratings and superseded IDs."""
    papers_by_id = {p['paper_id']:p for p in papers}
    topics = {a['paper_id']:a['topic_id'] for a in assignments}
    latest = {}
    for r in reviews:
        rid = r.get('review_id')
        if not rid:
            continue
        if rid not in latest or _latest_key(r) >= _latest_key(latest[rid]):
            latest[rid] = r
    within_paper = defaultdict(list)
    for r in latest.values():
        pid = r.get('paper_id')
        p = papers_by_id.get(pid)
        if p is None or pid not in topics:
            continue
        value, lo, hi = (_number(r.get(k)) for k in ('rating','scale_min','scale_max'))
        if None in (value, lo, hi) or not lo < hi or not lo <= value <= hi:
            continue
        # Do not silently mix provisional and post-discussion scores.
        stage = r.get('score_stage') or 'unknown'
        key = (p['venue'],p['year'],topics[pid],lo,hi,stage,pid)
        within_paper[key].append(value)
    by_topic = defaultdict(list)
    for key, ratings in within_paper.items():
        by_topic[key[:-1]].append(statistics.fmean(ratings))
    rows = []
    for key, ratings in sorted(by_topic.items(), key=lambda x:str(x[0])):
        row = dict(zip(SCORE_FIELDS[:6],key))
        row.update(papers_with_reviews=len(ratings), mean_paper_rating=statistics.fmean(ratings))
        rows.append(row)
    return rows


def _load_statistics(config):
    default = Path(__file__).resolve().parents[2] / 'configs/official_statistics.json'
    rows = read_json(Path(config.get('statistics_file',default)), [])
    if isinstance(rows,dict):
        rows = rows.get('statistics',[])
    # No synthetic defaults for submissions, rates or accepted counts.
    return [{**{k:None for k in STAT_FIELDS},**r} for r in rows]


def _model_topics(raw, assignments):
    if isinstance(raw, dict):
        raw = raw.get('topics',list(raw.values()))
    ids = {a['topic_id'] for a in assignments}
    ids.update(t['topic_id'] for t in raw if isinstance(t,dict) and 'topic_id' in t)
    return sorted(ids,key=lambda x:(str(type(x)),x))


def analyze(config, output, backend='lsa'):
    output = Path(output)
    destination = output/'analysis'/backend
    destination.mkdir(parents=True, exist_ok=True)
    papers_path, reviews_path = output/'processed/papers.jsonl', output/'processed/reviews.jsonl'
    assignment_path = output/'models'/backend/'assignments.jsonl'
    papers, reviews = read_jsonl(papers_path), read_jsonl(reviews_path)
    assignments = read_jsonl(assignment_path)
    if not papers:
        raise ValueError('No processed papers; run prepare before analysis')
    if len({p['paper_id'] for p in papers}) != len(papers):
        raise ValueError('Duplicate processed paper IDs')
    eligible = {p['paper_id'] for p in papers if p.get('track')=='main' and p.get('decision')=='accepted' and str(p.get('title') or '').strip() and str(p.get('abstract') or '').strip()}
    assignment_ids = [a['paper_id'] for a in assignments]
    if len(assignment_ids) != len(set(assignment_ids)) or set(assignment_ids) != eligible:
        raise ValueError(f'Model assignment/input ID mismatch: expected {len(eligible)}, got {len(set(assignment_ids))}')
    topic_ids = _model_topics(read_json(output/'models'/backend/'topics.json',[]),assignments)
    topic_for = {a['paper_id']:a['topic_id'] for a in assignments}
    stats = _load_statistics(config)
    stats = [r for r in stats if r.get('venue') in config['venues'] and r.get('year') in config['years']]
    by_group = defaultdict(list)
    main = defaultdict(list)
    for p in papers:
        key=(p['venue'],p['year'])
        by_group[key].append(p)
        if p.get('track')=='main' and p.get('decision')=='accepted':
            main[key].append(p)

    trends=[]
    for key, group in sorted(main.items()):
        if not group:
            continue
        denominator=len(group)
        missing=sum(not str(p.get('abstract') or '').strip() for p in group)
        counts=Counter(topic_for[p['paper_id']] for p in group if p['paper_id'] in topic_for)
        assigned=sum(counts.values())
        for topic_id in topic_ids:
            count=counts[topic_id]
            trends.append(dict(venue=key[0],year=key[1],topic_id=topic_id,paper_count=count,observed_main_accepted=denominator,assigned_papers=assigned,missing_abstract=missing,share=count/denominator,share_percent=100*count/denominator))
    changes=[]
    for venue in config['venues']:
        for topic in topic_ids:
            series=sorted((t for t in trends if t['venue']==venue and t['topic_id']==topic),key=lambda t:t['year'])
            for before,after in zip(series,series[1:]):
                changes.append(dict(venue=venue,topic_id=topic,from_year=before['year'],to_year=after['year'],year_gap=after['year']-before['year'],from_count=before['paper_count'],to_count=after['paper_count'],from_denominator=before['observed_main_accepted'],to_denominator=after['observed_main_accepted'],from_share_percent=before['share_percent'],to_share_percent=after['share_percent'],delta_pp=after['share_percent']-before['share_percent']))

    reconciliation=[]
    for venue in config['venues']:
        for year in config['years']:
            group=main[(venue,year)]
            observed=len(group)
            relevant=[s for s in stats if s.get('venue')==venue and s.get('year')==year and s.get('track')=='main']
            if not relevant:
                relevant=[dict(source_id=None,accepted=None,source_level='unavailable',source_url=None,preferred=False,approximate=None)]
            for s in relevant:
                accepted=s.get('accepted')
                ratio=observed/accepted if accepted else None
                exact_delta=observed-accepted if accepted is not None and not s.get('approximate') else None
                status='unavailable_reference' if accepted is None else ('partial_sample' if ratio < .9 else 'no_large_gap_detected')
                reconciliation.append(dict(venue=venue,year=year,source_id=s.get('source_id'),official_accepted=accepted,official_accepted_lower_bound=s.get('accepted_lower_bound'),observed_main_accepted=observed,missing_abstract=sum(not str(p.get('abstract') or '').strip() for p in group),assigned_papers=sum(p['paper_id'] in topic_for for p in group),difference_observed_minus_official=exact_delta,coverage_ratio=ratio,source_url=s.get('source_url'),source_level=s.get('source_level'),preferred=s.get('preferred',False),approximate=s.get('approximate'),status=status))

    heatmap_years=[]; exclusions=[]
    for year in config['years']:
        details=[]; reasons=[]
        for venue in config['venues']:
            rows=[r for r in reconciliation if r['venue']==venue and r['year']==year and r['official_accepted'] is not None and not r.get('approximate')]
            # Across conflicting comparable references, use the highest registered
            # accepted count for this exclusion gate rather than selecting the
            # smallest denominator to make coverage look complete.
            row=max(rows,key=lambda r:r['official_accepted']) if rows else None
            observed=len(main[(venue,year)])
            detail=dict(venue=venue,observed_main_accepted=observed,registered_accepted=row['official_accepted'] if row else None,coverage_ratio=row['coverage_ratio'] if row else None,source_level=row['source_level'] if row else None,source_url=row['source_url'] if row else None)
            details.append(detail)
            if not observed:
                reasons.append(venue+': no observed accepted main papers')
            elif row is None:
                reasons.append(venue+': no exact comparable registered main count')
            elif row['coverage_ratio'] < .9:
                reasons.append(venue+': observed/registered < 0.90')
        if reasons:
            exclusions.append(dict(year=year,reason='; '.join(reasons),venue_details=details))
        else:
            heatmap_years.append(year)
    heatmap=[dict(year=t['year'],venue=t['venue'],topic_id=t['topic_id'],paper_count=t['paper_count'],denominator=t['observed_main_accepted'],share=t['share'],share_percent=t['share_percent']) for t in trends if t['year'] in heatmap_years]

    scores=aggregate_scores(papers,reviews,assignments)
    cohort_reason='缺少事先独立完整决定队列证明；节目册录用名单与自愿公开样本不能作为全部投稿分母。'
    decisions=[]
    for venue in config['venues']:
        for year in config['years']:
            group=by_group[(venue,year)]
            count=Counter(p.get('decision') or 'unknown' for p in group)
            row=dict(venue=venue,year=year,total_public_papers=len(group),**{k:count[k] for k in ['accepted','rejected','withdrawn','desk_rejected','under_review','unknown']})
            row.update(independent_complete_decision_cohort=False,conditional_acceptance_rate=None,reason=cohort_reason)
            decisions.append(row)

    tables=[('official_statistics',stats,STAT_FIELDS),('reconciliation',reconciliation,RECON_FIELDS),('topic_trends',trends,TREND_FIELDS),('topic_changes',changes,CHANGE_FIELDS),('heatmap',heatmap,HEAT_FIELDS),('scores',scores,SCORE_FIELDS),('decision_samples',decisions,DECISION_FIELDS)]
    for name,rows,fields in tables:
        write_json(destination/(name+'.json'),rows)
        write_csv(destination/(name+'.csv'),rows,fields)
    model_manifest_path=output/'models'/backend/'manifest.json'
    statistics_path=Path(config.get('statistics_file',Path(__file__).resolve().parents[2]/'configs/official_statistics.json'))
    manifest=dict(generated_at=utcnow(),backend=backend,status='completed_with_public_review_limitations' if not scores else 'completed_observed_sample_analysis',counts=dict(papers=len(papers),main_accepted=sum(map(len,main.values())),modeled=len(assignments),formal_reviews_observed=len(reviews),valid_score_strata=len(scores),topics=len(topic_ids),statistics_sources=len(stats)),heatmap_years=heatmap_years,heatmap_exclusions=exclusions,coverage_gate=.90,coverage_gate_note='明显缺口筛选，不是网络完整性或完整提交队列认证。冲突同口径来源取最大录用数作排除检验。',share_denominator='all_observed_main_accepted_in_venue_year_including_missing_abstracts',change_unit='percentage_points',scores_status='observed_public_sample' if scores else 'not_computable',score_unavailable_reason=None if scores else '未采到可合法解析且有量表及阶段的公开正式评审；零条评审不是零分。评审通道状态见 source_coverage。',conditional_acceptance_status='not_estimable',conditional_acceptance_reason=cohort_reason,bias_notes=['仅录用成果，存在选择偏差与时滞，不能推断投稿分布或选题录用优势。','自动主题词与编号需人工复核，跨模型编号不可直接对齐。','官方总录用率保留来源原分母；未由实采录用论文数反推。'],inputs={'papers_sha256':sha256(papers_path),'reviews_sha256':sha256(reviews_path) if reviews_path.exists() else None,'assignments_sha256':sha256(assignment_path),'model_manifest_sha256':sha256(model_manifest_path) if model_manifest_path.exists() else None},files={})
    manifest['inputs']['statistics_config_sha256']=sha256(statistics_path) if statistics_path.exists() else None
    manifest['statistics_source_level_counts']=dict(Counter(s.get('source_level') or 'unknown' for s in stats))
    manifest['statistics_missing_cohorts']=[{'venue':v,'year':y} for v in config['venues'] for y in config['years'] if not any(s.get('venue')==v and s.get('year')==y for s in stats)]
    manifest['preferred_statistics_sources']=[s.get('source_id') for s in stats if s.get('preferred')]
    for name,rows,fields in tables:
        manifest['files'][name]={'rows':len(rows),'csv_sha256':sha256(destination/(name+'.csv')),'json_sha256':sha256(destination/(name+'.json'))}
    write_json(destination/'analysis_manifest.json',manifest)
    return manifest
