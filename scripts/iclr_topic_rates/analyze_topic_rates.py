"""Descriptive topic rates for explicitly defined PUBLIC ICLR snapshot cohorts.

The primary denominator excludes withdrawals/desk rejections; official valid
submission acceptance rates remain a separate, unavailable estimand here.
"""
import collections
import csv
import hashlib
import json
import pathlib
import statistics
import sys

ROOT=pathlib.Path(__file__).resolve().parent
WORK=ROOT.parent
sys.path.insert(0,str(WORK/'source_existing/src'))
from ai_trends.common import write_csv,write_json,write_jsonl,sha256,utcnow


def summarize(values):
    values=list(values)
    return dict(n=len(values),mean=statistics.fmean(values) if values else None,
                sd=statistics.stdev(values) if len(values)>1 else None,
                median=statistics.median(values) if values else None)


def rate(a,b):return a/b if b else None


def load_projection_rows(results):
    """Use full JSONL when present; the small result bundle also supports CSV."""
    full=results/'iclr_public_topic_assignments.jsonl'
    if full.exists():
        rows=[json.loads(line) for line in full.open()];kind='full_jsonl'
    else:
        table=results/'iclr_public_topic_assignments.csv'
        prior=json.loads((results/'cohort_verification.json').read_text())
        assert sha256(table)==prior['projected_csv_sha256']
        with table.open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
        for r in rows:
            for key in ['year','topic_id','original_topic_id','n_reviews']:
                r[key]=int(r[key]) if r[key]!='' else None
            for key in ['mean_rating','scale_min','scale_max','similarity','euclidean_margin','original_similarity']:
                r[key]=float(r[key]) if r[key]!='' else None
            r['outlier']=r['outlier'].lower()=='true'
        kind='verified_compact_csv'
    conflicts=results/'original_title_conflicts.csv'
    if not conflicts.exists():conflicts=WORK/'supplement/results/quarantine_title_mismatches.csv'
    bad=set()
    if conflicts.exists():
        with conflicts.open(encoding='utf-8-sig',newline='') as f:
            bad={r['paper_id'] for r in csv.DictReader(f) if r['venue']=='ICLR'}
    for r in rows:r['original_title_conflict']=r.get('original_paper_id') in bad
    return rows,kind


def aggregate(rows,labels):
    outputs=[]
    for year in [2024,2025,2026]:
        year_rows=[r for r in rows if r['year']==year]
        year_accepted=sum(r['current_status']=='accepted' for r in year_rows)
        for topic in range(50):
            group=[r for r in year_rows if r['topic_id']==topic]
            old_group=[r for r in year_rows if (r['original_topic_id'] if r['original_topic_id'] is not None and not r.get('original_title_conflict',False) else r['topic_id'])==topic]
            counts=collections.Counter(r['current_status'] for r in group)
            issued=collections.Counter(r['issued_decision'] for r in group)
            a,b=counts['accepted'],counts['rejected']
            note_a,note_b=issued['accepted'],issued['rejected']
            nonout=[r for r in group if not r['outlier']]
            no_a=sum(r['current_status']=='accepted' for r in nonout)
            no_b=sum(r['current_status']=='rejected' for r in nonout)
            orig_a=sum(r['current_status']=='accepted' for r in old_group)
            orig_b=sum(r['current_status']=='rejected' for r in old_group)
            scores=summarize(r['mean_rating'] for r in group if r['mean_rating'] is not None)
            ac_scores=summarize(r['mean_rating'] for r in group if r['current_status']=='accepted' and r['mean_rating'] is not None)
            re_scores=summarize(r['mean_rating'] for r in group if r['current_status']=='rejected' and r['mean_rating'] is not None)
            outputs.append(dict(venue='ICLR',year=year,topic_id=topic,topic_keywords=labels[topic],
                public_topic_submissions=len(group),public_year_submissions=len(year_rows),
                topic_submission_share=rate(len(group),len(year_rows)),
                current_accepted=a,current_rejected=b,current_withdrawn=counts['withdrawn'],
                current_desk_rejected=counts['desk_rejected'],current_unknown=counts['unknown'],
                current_decided_denominator=a+b,current_public_conditional_acceptance_rate=rate(a,a+b),
                current_public_conditional_acceptance_percent=100*rate(a,a+b) if a+b else None,
                all_public_submission_acceptance_rate=rate(a,len(group)),
                accepted_topic_share=rate(a,year_accepted),
                issued_accept_count=note_a,issued_reject_count=note_b,issued_decision_denominator=note_a+note_b,
                issued_decision_acceptance_rate=rate(note_a,note_a+note_b),
                outlier_papers=sum(r['outlier'] for r in group),
                outlier_decided_papers=sum(r['outlier'] and r['current_status'] in ['accepted','rejected'] for r in group),
                nonoutlier_accepted=no_a,nonoutlier_rejected=no_b,
                nonoutlier_conditional_acceptance_rate=rate(no_a,no_a+no_b),
                original_label_sensitivity_accepted=orig_a,original_label_sensitivity_rejected=orig_b,
                original_label_sensitivity_acceptance_rate=rate(orig_a,orig_a+orig_b),
                original_title_conflict_records=sum(r.get('original_title_conflict',False) for r in group),
                scored_public_papers=scores['n'],mean_public_paper_rating=scores['mean'],sd_public_paper_rating=scores['sd'],
                accepted_scored_papers=ac_scores['n'],mean_accepted_paper_rating=ac_scores['mean'],
                rejected_scored_papers=re_scores['n'],mean_rejected_paper_rating=re_scores['mean'],
                score_scale_min=0 if year==2026 else 1,score_scale_max=10,
                scope='public_archived_main_submissions_with_current_accept_or_reject_status_only',
                official_all_valid_submissions_topic_acceptance_rate=None,
                official_full_valid_denominator_verified=False,
                low_decided_count_flag=a+b<50))
    return outputs


def main():
    results=ROOT/'results'
    projection=json.loads((results/'projection_manifest.json').read_text())
    assert projection['status']=='completed' and not projection['model_fit_executed']
    rows,input_kind=load_projection_rows(results)
    if input_kind=='full_jsonl':
        assert sha256(results/'iclr_public_topic_assignments.jsonl')==projection['assigned_public_data_sha256']
    topics=json.loads((WORK/'recovered_existing/models/onnx/topics.json').read_text())
    labels={r['topic_id']:' / '.join(r['keywords'][:5]) for r in topics}
    conflict_table=results/'original_title_conflicts.csv'
    if not conflict_table.exists():
        with (WORK/'supplement/results/quarantine_title_mismatches.csv').open(encoding='utf-8-sig',newline='') as f:
            conflicts=[r for r in csv.DictReader(f) if r['venue']=='ICLR']
        write_csv(conflict_table,conflicts)
    prior=json.loads((WORK/'supplement/results/supplement_manifest.json').read_text())
    output=aggregate(rows,labels)
    cohorts=[];checks=[]
    assert len(rows)==38890 and len(output)==150
    assert len({(r['year'],r['openreview_id']) for r in rows})==len(rows)
    for year in [2024,2025,2026]:
        group=[r for r in rows if r['year']==year]
        cross=next(r for r in prior['iclr_crosschecks'] if r['year']==year)
        assert len(group)==cross['copilot_main_ids']==cross['qh_submission_ids']==cross['paper_score_lists_identical']
        assert cross['extra_qh_submission_ids']==cross['missing_qh_submission_ids']==0
        counts=collections.Counter(r['current_status'] for r in group)
        note_counts=collections.Counter(r['issued_decision'] for r in group)
        decided=[r for r in group if r['current_status'] in ['accepted','rejected']]
        # A positive cross-source outcome confirmation for EVERY current decided paper.
        contradictions=[r for r in decided if r['issued_decision']!=r['current_status'] or not r['decision_note_id']]
        assert not contradictions
        totals=[r for r in output if r['year']==year]
        assert sum(r['current_accepted'] for r in totals)==counts['accepted']
        assert sum(r['current_rejected'] for r in totals)==counts['rejected']
        assert sum(r['public_topic_submissions'] for r in totals)==len(group)
        assert sum(r['issued_decision_denominator'] for r in totals)==note_counts['accepted']+note_counts['rejected']
        cohorts.append(dict(venue='ICLR',year=year,public_submissions=len(group),
            accepted=counts['accepted'],rejected=counts['rejected'],withdrawn=counts['withdrawn'],desk_rejected=counts['desk_rejected'],
            current_decided_denominator=len(decided),current_conditional_acceptance_rate=rate(counts['accepted'],len(decided)),
            issued_accepted=note_counts['accepted'],issued_rejected=note_counts['rejected'],
            issued_decision_denominator=note_counts['accepted']+note_counts['rejected'],
            issued_decision_acceptance_rate=rate(note_counts['accepted'],note_counts['accepted']+note_counts['rejected']),
            accepted_over_all_public_submissions=rate(counts['accepted'],len(group)),
            topics_assigned=sum(r['topic_id'] is not None for r in group),
            public_decision_cohort_verified=True,official_full_valid_submission_cohort_verified=False,
            current_decisions_confirmed_by_formal_decision_notes=len(decided),
            current_vs_historical_status_differences=sum(r['current_status']!=r['issued_decision'] and r['issued_decision']!='unknown' for r in group),
            source_archives_same_public_id_set=True,
            score_stage='latest_public_archive_snapshot_not_initial',
            topic_model_basis='unchanged_frozen_50_topic_space_trained_on_accepted_papers'))
        checks.append(dict(year=year,check='independent_public_ids_explicit_decisions_and_topic_denominators_reconcile',status='passed'))
    changes=[]
    for topic in range(50):
        series=sorted([r for r in output if r['topic_id']==topic],key=lambda r:r['year'])
        for before,after in zip(series,series[1:]):
            a,b=before['current_public_conditional_acceptance_rate'],after['current_public_conditional_acceptance_rate']
            changes.append(dict(topic_id=topic,topic_keywords=labels[topic],from_year=before['year'],to_year=after['year'],
                from_decided_n=before['current_decided_denominator'],to_decided_n=after['current_decided_denominator'],
                from_acceptance_rate=a,to_acceptance_rate=b,change_percentage_points=100*(b-a) if a is not None and b is not None else None,
                from_submission_share=before['topic_submission_share'],to_submission_share=after['topic_submission_share'],
                submission_share_change_pp=100*(after['topic_submission_share']-before['topic_submission_share'])))
    write_csv(results/'iclr_topic_metrics_150.csv',output)
    write_json(results/'iclr_topic_metrics_150.json',output)
    write_csv(results/'iclr_cohort_summary.csv',cohorts)
    write_csv(results/'iclr_topic_year_changes.csv',changes)
    write_jsonl(results/'status_history_disagreements.jsonl',[r for r in rows if r['issued_decision']!='unknown' and r['issued_decision']!=r['current_status']])
    write_json(results/'cohort_verification.json',dict(created_at=utcnow(),status='passed',checks=checks,
        rows=len(rows),topic_year_rows=len(output),current_decided_papers=sum(c['current_decided_denominator'] for c in cohorts),
        cohorts=cohorts,conditional_rate_released_for='the_verified_public_snapshot_cohort_only',
        official_all_valid_submission_topic_rate_released=False,
        original_assignment_file_still_matches=sha256(WORK/'recovered_existing/models/onnx/assignments.csv')==projection['original_assignment_table_sha256'],
        projected_csv_sha256=sha256(results/'iclr_public_topic_assignments.csv'),input_kind=input_kind,
        classification_validation_file='model_compatibility_validation.json',
        statistical_method='Descriptive census of the archived public cohort; no sampling confidence intervals, significance tests, or causal claims.'))
    print(json.dumps({'status':'passed','topic_year_rows':len(output),'cohorts':cohorts},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
