import base64
import gzip
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from ai_trends.common import write_csv, write_json, write_jsonl
from ai_trends.report import build_report, script_json, stratified_sample, official_percent


class ReportBehaviorTests(unittest.TestCase):
    def test_published_rate_does_not_gain_false_decimal_precision(self):
        self.assertEqual(official_percent({'official_rate':31,'official_rate_precision_digits':0}),'31%')
        self.assertEqual(official_percent({'official_rate':27.4,'official_rate_precision_digits':1}),'27.4%')
        self.assertEqual(official_percent({'official_rate':24.52,'official_rate_precision_digits':2}),'24.52%')
        self.assertEqual(official_percent({'official_rate':None}),'—')

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = {'venues': ['ICLR', 'ICML', 'NeurIPS'], 'years': [2024, 2025, 2026], 'report': {'max_rows': 5000}}
        self.paper = {'paper_id': 'ICLR:2024:p1', 'venue': 'ICLR', 'year': 2024, 'title': '</script><img src=x onerror="alert(1)">',
                      'abstract': 'A & B <script>alert(2)</script> \u2028 text', 'authors': ['<script>A</script>'],
                      'source_url': 'javascript:alert(3)', 'track': 'main', 'decision': 'accepted'}
        write_jsonl(self.root / 'processed/papers.jsonl', [self.paper])
        write_csv(self.root / 'processed/papers.csv', [self.paper])
        write_jsonl(self.root / 'processed/reviews.jsonl', [])
        write_json(self.root / 'source_coverage.json', [{'venue': 'ICLR', 'year': 2024, 'status': 'success', 'openreview_status': 'blocked'}])
        write_jsonl(self.root / 'models/lsa/assignments.jsonl', [{'paper_id': self.paper['paper_id'], 'topic_id': 0, 'similarity': .8, 'outlier': False}])
        write_json(self.root / 'models/lsa/topics.json', [{'topic_id': 0, 'size': 1, 'keywords': ['a', '</script>'], 'representatives': [self.paper]}])
        write_json(self.root / 'models/lsa/manifest.json', {'status': 'completed'})

    def tearDown(self):
        self.temp.cleanup()

    def build(self):
        result = build_report(self.config, self.root, 'lsa')
        return result, (self.root / 'report.html').read_text()

    def test_untrusted_text_and_urls_do_not_become_executable_markup(self):
        _, report = self.build()
        self.assertNotIn('<img src=x', report)
        self.assertNotIn('href="javascript:', report)
        self.assertNotIn('<script>alert(', report)
        self.assertIn('&lt;/script&gt;', report)
        data = json.loads(re.search(r'<script type="application/json" id="report-data">(.*?)</script>', report, re.S).group(1))
        self.assertEqual(data['papers'][0]['title'], self.paper['title'])
        self.assertEqual(data['papers'][0]['source_url'], '')
        self.assertEqual(len(re.findall(r'<script(?:\s|>)', report)), 3)

    def test_embedded_exports_reproduce_exact_original_bytes(self):
        _, report = self.build()
        exports = json.loads(re.search(r'<script type="application/json" id="exports-data">(.*?)</script>', report, re.S).group(1))
        names = {e['name'] for e in exports}
        self.assertIn('processed/papers.jsonl', names)
        self.assertIn('processed/papers.csv', names)
        for record in exports:
            restored = gzip.decompress(base64.b64decode(record['data']))
            self.assertEqual(restored, (self.root / record['name']).read_bytes())
            self.assertEqual(len(restored), record['size_bytes'])

    def test_no_scores_or_missing_sources_are_explained(self):
        _, report = self.build()
        self.assertIn('零条评审不代表零分', report)
        self.assertIn('未采集', report)
        self.assertIn('不计算主题条件接收率', report)
        self.assertIn('connect-src \'none\'', report)

    def test_embedded_javascript_parses_without_browser(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('Node.js is unavailable')
        _, report = self.build()
        script = re.search(r'<script>\s*(.*?)</script>', report, re.S).group(1)
        target = self.root / 'inline.js'
        target.write_text(script)
        proc = subprocess.run([node, '--check', str(target)], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)

    def test_stratification_and_hard_browser_limit(self):
        papers = [{'paper_id': f'a{i:05}', 'venue': 'ICLR', 'year': 2024, 'track': 'main'} for i in range(6000)]
        rare = {'paper_id': 'rare', 'venue': 'ICML', 'year': 2026, 'track': 'unknown'}
        sample = stratified_sample(papers + [rare], maximum=10000)
        self.assertEqual(len(sample), 5000)
        self.assertIn(rare, sample)
        self.assertEqual(sample, stratified_sample(list(reversed(papers)) + [rare], maximum=5000))

    def test_script_data_preserves_text_without_closing_tag(self):
        text = '</script> & < > \u2028 \u2029'
        packed = script_json({'value': text})
        self.assertNotIn('<', packed)
        self.assertNotIn('\u2028', packed)
        self.assertEqual(json.loads(packed)['value'], text)

    def test_detail_checkpoint_is_visible_and_embedded_with_directory_audit(self):
        summary = {'planned': 10, 'attempted': 4, 'successful': 3, 'failed': 1, 'remaining': 6,
                   'main_missing_planned': 5, 'main_repaired': 3, 'main_abstract_repair_rate': .6,
                   'directory_new_papers': 5, 'status': 'running', 'updated_at': '2026-10-28T08:00:00Z'}
        write_json(self.root / 'details/summary.json', summary)
        write_csv(self.root / 'details/reconciliation.csv', [{'venue': 'NeurIPS', 'year': 2026,
                  'directory_events': 20, 'bulk_events': 15, 'directory_absent_from_bulk_events': 5,
                  'bulk_title_not_in_directory': 0, 'new_titles_vs_bulk': 5, 'status': 'success',
                  'pages': ['https://neurips.cc/virtual/2026/papers.html', 'javascript:alert(9)']}])
        _, report = self.build()
        self.assertIn('详情补采仍在执行', report)
        self.assertIn('60.00%', report)
        self.assertIn('不纳入主会主题模型', report)
        self.assertIn('目录有/批量无事件', report)
        self.assertNotIn('href="javascript:', report)
        exports = json.loads(re.search(r'<script type="application/json" id="exports-data">(.*?)</script>', report, re.S).group(1))
        names = {e['name'] for e in exports}
        self.assertIn('details/summary.json', names)
        self.assertIn('details/reconciliation.csv', names)
        exported_summary = next(e for e in exports if e['name'] == 'details/summary.json')
        self.assertEqual(json.loads(gzip.decompress(base64.b64decode(exported_summary['data']))), summary)

    def test_dynamic_validation_is_displayed_with_timestamp_but_never_exported(self):
        timestamp = '2026-10-28T09:00:00Z'
        write_json(self.root / 'validation.json', {'generated_at': timestamp, 'structural_status': 'passed'})
        write_json(self.root / 'validation_results.json', {'generated_at': '2026-10-27T00:00:00Z'})
        write_csv(self.root / 'analysis/lsa/topic_trends.csv', [{'venue': 'ICLR', 'year': 2024, 'topic_id': 0, 'paper_count': 1}])
        _, report = self.build()
        self.assertIn('本报告读取的验证记录时间（UTC）：' + timestamp, report)
        self.assertIn('完整验证记录见最终数据包中的 validation.json', report)
        exports = json.loads(re.search(r'<script type="application/json" id="exports-data">(.*?)</script>', report, re.S).group(1))
        names = {e['name'] for e in exports}
        self.assertNotIn('validation.json', names)
        self.assertNotIn('validation_results.json', names)
        self.assertIn('analysis/lsa/topic_trends.csv', names)
        self.assertIn('processed/papers.csv', names)


if __name__ == '__main__':
    unittest.main()
