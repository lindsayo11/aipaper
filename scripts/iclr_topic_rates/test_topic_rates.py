"""Cohort-denominator, frozen-model, visibility, and artifact checks."""
import ast
import collections
import csv
import hashlib
import json
import pathlib
import sys
import unittest

import numpy as np

ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from analyze_topic_rates import aggregate,rate,load_projection_rows
from frozen_projection import predict
from ai_trends.modeling import paper_text

LABELS={i:str(i) for i in range(50)}


def row(status='accepted',issued='accepted',topic=0,original=None,score=6,outlier=False):
    return dict(year=2024,current_status=status,issued_decision=issued,topic_id=topic,
                original_topic_id=original,mean_rating=score,outlier=outlier)


class FormulaTests(unittest.TestCase):
    def test_euclidean_prediction_does_not_normalize_fitted_centers(self):
        labels,_,_=predict(np.array([[1,0]],dtype=np.float32),np.array([[3,0],[.5,.5]],dtype=np.float32))
        self.assertEqual(int(labels[0]),1)

    def test_current_conditional_rate_excludes_withdrawal_and_desk_reject(self):
        rows=[row(),row('rejected','rejected'),row('withdrawn','unknown'),row('desk_rejected','unknown')]
        r=aggregate(rows,LABELS)[0]
        self.assertEqual(r['current_decided_denominator'],2)
        self.assertEqual(r['current_public_conditional_acceptance_rate'],.5)
        self.assertEqual(r['all_public_submission_acceptance_rate'],.25)

    def test_missing_outcome_is_not_a_rejection(self):
        r=aggregate([row(),row('unknown','unknown')],LABELS)[0]
        self.assertEqual(r['current_rejected'],0)
        self.assertEqual(r['current_decided_denominator'],1)

    def test_past_acceptance_and_current_withdrawal_are_separate(self):
        r=aggregate([row('withdrawn','accepted'),row('rejected','rejected')],LABELS)[0]
        self.assertEqual(r['current_public_conditional_acceptance_rate'],0)
        self.assertEqual(r['issued_decision_acceptance_rate'],.5)

    def test_paper_means_have_equal_weights(self):
        r=aggregate([row(score=8),row(score=2)],LABELS)[0]
        self.assertEqual(r['mean_public_paper_rating'],5)

    def test_zero_score_is_not_missing(self):
        r=aggregate([row(score=0),row(score=2),row(score=None)],LABELS)[0]
        self.assertEqual(r['scored_public_papers'],2)
        self.assertEqual(r['mean_public_paper_rating'],1)

    def test_outliers_stay_in_primary_denominator(self):
        r=aggregate([row(outlier=True),row('rejected','rejected')],LABELS)[0]
        self.assertEqual(r['current_public_conditional_acceptance_rate'],.5)
        self.assertEqual(r['nonoutlier_conditional_acceptance_rate'],0)

    def test_zero_denominator_is_missing(self):
        self.assertIsNone(rate(0,0))
        self.assertIsNone(aggregate([],LABELS)[0]['current_public_conditional_acceptance_rate'])

    def test_original_label_sensitivity_reconciles_both_topics(self):
        result=aggregate([row(topic=1,original=0),row('rejected','rejected',topic=0)],LABELS)
        self.assertEqual(result[0]['original_label_sensitivity_acceptance_rate'],.5)
        self.assertEqual(result[1]['current_accepted'],1)

    def test_quarantined_title_does_not_reintroduce_an_old_label(self):
        a=row(topic=1,original=0);a['original_title_conflict']=True
        result=aggregate([a,row('rejected','rejected',topic=0)],LABELS)
        self.assertEqual(result[0]['original_label_sensitivity_acceptance_rate'],0)

    def test_official_valid_submission_rate_is_never_fabricated(self):
        self.assertTrue(all(r['official_all_valid_submissions_topic_acceptance_rate'] is None for r in aggregate([row()],LABELS)))

    def test_only_title_and_abstract_enter_the_text(self):
        a=dict(title='Paper',abstract='Abstract',rating=0,decision='rejected',year=2024)
        b={**a,'rating':10,'decision':'accepted','year':2026}
        self.assertEqual(paper_text(a),paper_text(b))

    def test_new_projection_code_never_fits_a_model(self):
        tree=ast.parse((ROOT/'frozen_projection.py').read_text())
        calls=[n.func.attr for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute)]
        self.assertFalse(set(calls)&{'fit','fit_predict','fit_transform','partial_fit'})


class ActualDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r=ROOT/'results'
        cls.projection=json.loads((r/'projection_manifest.json').read_text())
        cls.verification=json.loads((r/'cohort_verification.json').read_text())
        cls.compatibility=json.loads((r/'model_compatibility_validation.json').read_text())
        cls.metrics=json.loads((r/'iclr_topic_metrics_150.json').read_text())
        cls.assignments,_=load_projection_rows(r)

    def test_full_public_id_set_and_all_topics_assigned(self):
        rows=self.assignments
        self.assertEqual(len(rows),38890)
        self.assertEqual(len({(r['year'],r['openreview_id']) for r in rows}),38890)
        self.assertTrue(all(r['topic_id'] in range(50) for r in rows))

    def test_150_year_topic_rows(self):
        self.assertEqual(len(self.metrics),150)
        self.assertEqual({(r['year'],r['topic_id']) for r in self.metrics},{(y,t) for y in [2024,2025,2026] for t in range(50)})

    def test_all_decided_papers_have_matching_official_decision_notes(self):
        for r in self.assignments:
            if r['current_status'] in ['accepted','rejected']:
                self.assertEqual(r['current_status'],r['issued_decision'])
                self.assertTrue(r['decision_note_id'])

    def test_rate_weighted_by_topic_denominators_matches_each_year(self):
        for c in self.verification['cohorts']:
            rows=[r for r in self.metrics if r['year']==c['year']]
            self.assertEqual(sum(r['current_accepted'] for r in rows),c['accepted'])
            self.assertEqual(sum(r['current_rejected'] for r in rows),c['rejected'])
            weighted=sum((r['current_public_conditional_acceptance_rate'] or 0)*r['current_decided_denominator'] for r in rows)/c['current_decided_denominator']
            self.assertAlmostEqual(weighted,c['current_conditional_acceptance_rate'],places=12)

    def test_verified_public_scope_does_not_claim_official_full_scope(self):
        for c in self.verification['cohorts']:
            self.assertTrue(c['public_decision_cohort_verified'])
            self.assertFalse(c['official_full_valid_submission_cohort_verified'])
        self.assertFalse(self.verification['official_all_valid_submission_topic_rate_released'])

    def test_original_model_was_not_retrained_or_replaced(self):
        self.assertFalse(self.projection['model_fit_executed'])
        self.assertTrue(self.projection['original_assignment_table_unchanged'])
        self.assertTrue(self.verification['original_assignment_file_still_matches'])
        path=ROOT.parent/'recovered_existing/models/onnx/assignments.csv'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),self.projection['original_assignment_table_sha256'])

    def test_original_centroid_file_is_unchanged(self):
        p=ROOT.parent/'upload/centroids.npy'
        self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),self.projection['centers_sha256'])

    def test_no_claim_that_the_failed_fresh_batch_test_passed(self):
        c=self.compatibility
        self.assertEqual(c['initial_strict_fresh_batch_status'],'failed')
        self.assertFalse(c['strict_fresh_batch_portability_passed'])
        self.assertTrue(self.projection['quantization_batch_sensitivity_observed'])

    def test_all_diagnostic_mismatches_reproduced_in_original_context(self):
        r=self.compatibility['original_context_replay']
        self.assertEqual(r['papers_checked'],89)
        self.assertEqual(r['label_matches'],89)
        self.assertLess(r['mean_similarity_error'],1e-6)

    def test_old_and_new_text_counts_reconcile(self):
        p=self.projection
        self.assertEqual(p['public_papers'],p['reused_identical_text']+p['encoded_texts'])
        self.assertEqual(p['encoded_texts'],p['new_submissions']+p['revised_public_texts'])

    def test_primary_rates_missing_only_for_zero_denominators(self):
        for r in self.metrics:
            self.assertEqual(r['current_public_conditional_acceptance_rate'] is None,r['current_decided_denominator']==0)

    def test_score_counts_reconcile(self):
        for r in self.metrics:
            self.assertLessEqual(r['accepted_scored_papers'],r['current_accepted'])
            self.assertLessEqual(r['rejected_scored_papers'],r['current_rejected'])
            self.assertLessEqual(r['scored_public_papers'],r['public_topic_submissions'])

    def test_all_decided_public_papers_count(self):
        self.assertEqual(self.verification['current_decided_papers'],28043)

    def test_all_historical_title_conflicts_remain_flagged(self):
        self.assertEqual(sum(r['original_title_conflict'] for r in self.assignments),9)
        self.assertEqual(sum(r['original_title_conflict_records'] for r in self.metrics),9)


if __name__=='__main__':unittest.main(verbosity=2)
