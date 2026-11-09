"""Separate an exact center-identity check from fresh-batch portability checks.

The original strict fresh-batch validation FAILED and remains an immutable
diagnostic. It is not relabeled as a passing test. Replaying the original
contexts resolves all of its mismatches and establishes center identity.
"""
import json
import pathlib
import shutil
import sys

ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT.parent/'source_existing/src'))
from ai_trends.common import write_json,sha256,utcnow

dest=ROOT/'results'
initial_path=dest/'fresh_batch_validation.json'
if not initial_path.exists():
    shutil.copyfile(dest/'model_compatibility_validation.json',initial_path)
    shutil.copyfile(dest/'model_compatibility_validation.csv',dest/'fresh_batch_validation.csv')
initial=json.loads(initial_path.read_text())
replay=json.loads((dest/'original_batch_context_check.json').read_text())
assert initial['status']=='failed'
assert replay['papers_checked']==replay['label_matches']==89
assert replay['mean_similarity_error']<1e-6
assert replay['mismatches']==[]
assert len(initial['mismatches'])==39
assert initial['centers_sha256']==sha256(ROOT.parent/'upload/centroids.npy')
result=dict(status='identity_confirmed_with_batch_sensitivity_warning',created_at=utcnow(),
    centers_sha256=initial['centers_sha256'],centers_shape=initial['centers_shape'],
    initial_strict_fresh_batch_status='failed',initial_fresh_batch_diagnostic=initial,
    original_context_replay=replay,
    identity_experiment_design='All 39 fresh-batch mismatch cases plus one original representative from each of 50 topics; diagnostic, not an independent accuracy estimate.',
    inference_approved_for='exploratory_public_cohort_projection_in_the_unchanged_topic_space',
    strict_fresh_batch_portability_passed=False,
    original_assignment_table_will_not_be_overwritten=True,
    model_fit_executed=False,
    interpretation='The supplied centers reproduce original assignments and similarities in original batch contexts; quantized encoding changes slightly with batch composition. Do not claim exact fresh-batch replay or topic-label correctness.')
write_json(dest/'model_compatibility_validation.json',result)
print(json.dumps({k:v for k,v in result.items() if k not in ['initial_fresh_batch_diagnostic','original_context_replay']},ensure_ascii=False),flush=True)
