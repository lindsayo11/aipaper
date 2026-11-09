"""Run dependent analysis, checks, report, and packaging after inference ends."""
import json
import pathlib
import runpy
import subprocess
import sys
import unittest

ROOT=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))

runpy.run_path(str(ROOT/'analyze_topic_rates.py'),run_name='__main__')
import test_topic_rates
suite=unittest.defaultTestLoader.loadTestsFromModule(test_topic_rates)
with (ROOT/'results/test_results.txt').open('w') as log:
    result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
stats=dict(tests_run=result.testsRun,successful=result.wasSuccessful(),failures=len(result.failures),errors=len(result.errors),
           numerical_diagnostic_note='The strict fresh-batch parity test remains failed in its original record; exact original-context replay established center identity. These tests do not relabel that diagnostic as passed.')
(ROOT/'results/test_results.json').write_text(json.dumps(stats,ensure_ascii=False,indent=2))
print(json.dumps(stats),flush=True)
assert result.wasSuccessful()
runpy.run_path(str(ROOT/'build_topic_report.py'),run_name='__main__')
r=subprocess.run(['node','--check',str(ROOT/'results/report_script.js')],capture_output=True,text=True)
assert r.returncode==0,r.stderr
(ROOT/'results/report_checks.json').write_text(json.dumps(dict(javascript_syntax='passed',real_browser_interaction='not_tested_no_installed_browser',
    external_asset_dependencies=False,embedded_downloads='generated_from_verified_CSV_bytes'),indent=2))
runpy.run_path(str(ROOT/'package_topic_results.py'),run_name='__main__')
