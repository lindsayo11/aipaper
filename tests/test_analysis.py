"""Tests for denominator integrity, absent data, and review aggregation."""
import json
from pathlib import Path
import tempfile
import unittest
from ai_trends.common import write_json, write_jsonl, read_json
from ai_trends.analysis import analyze, aggregate_scores


class AnalysisContractTests(unittest.TestCase):
    def test_scores_equal_weight_papers_and_split_scales(self):
        papers = [{'paper_id':'a','venue':'ICLR','year':2024}, {'paper_id':'b','venue':'ICLR','year':2024}]
        assignments = [{'paper_id':'a','topic_id':0},{'paper_id':'b','topic_id':0}]
        reviews = [dict(review_id='a'+str(i),paper_id='a',rating=2,scale_min=1,scale_max=10,score_stage='final',updated_at=i) for i in range(3)]
        reviews += [dict(review_id='b',paper_id='b',rating=10,scale_min=1,scale_max=10,score_stage='final',updated_at=1)]
        reviews += [dict(review_id='invalid',paper_id='a',rating=11,scale_min=1,scale_max=10,score_stage='final',updated_at=1)]
        rows = aggregate_scores(papers, reviews, assignments)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['mean_paper_rating'],6)
        self.assertEqual(rows[0]['papers_with_reviews'],2)

    def fixture(self, root):
        def paper(pid, year=2024, abstract='abstract', decision='accepted'):
            return dict(paper_id=pid,venue='ICLR',year=year,title=pid,abstract=abstract,track='main',decision=decision)
        papers=[paper('a'),paper('b',abstract=''),paper('c',decision='unknown'),paper('d',year=2026)]
        write_jsonl(root/'processed/papers.jsonl',papers)
        write_jsonl(root/'processed/reviews.jsonl',[])
        write_jsonl(root/'models/lsa/assignments.jsonl',[{'paper_id':'a','topic_id':0},{'paper_id':'d','topic_id':0}])
        write_json(root/'models/lsa/topics.json',[{'topic_id':0,'keywords':['term'],'size':2}])
        stats=[dict(venue='ICLR',year=2024,source_id='official',track='main',accepted=3,preferred=True,source_url='https://iclr.cc/x',source_level='conference'),dict(venue='ICLR',year=2026,source_id='later',track='main',accepted=1,preferred=True,source_url='https://iclr.cc/y',source_level='conference')]
        write_json(root/'stats.json',stats)
        return dict(venues=['ICLR'],years=[2024,2025,2026],statistics_file=str(root/'stats.json'))

    def test_missing_abstract_stays_in_heat_denominator_and_unknown_is_not_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); cfg=self.fixture(root); analyze(cfg,root,'lsa')
            trends=read_json(root/'analysis/lsa/topic_trends.json')
            t=next(x for x in trends if x['year']==2024)
            self.assertEqual(t['paper_count'],1)
            self.assertEqual(t['observed_main_accepted'],2)
            self.assertEqual(t['share'],.5)
            self.assertEqual(t['missing_abstract'],1)
            self.assertFalse(any(x['year']==2025 for x in trends))
            decisions=read_json(root/'analysis/lsa/decision_samples.json')
            ds=next(x for x in decisions if x['year']==2024)
            self.assertEqual(ds['rejected'],0)
            self.assertEqual(ds['unknown'],1)
            self.assertIsNone(ds['conditional_acceptance_rate'])
            self.assertEqual(read_json(root/'analysis/lsa/scores.json'),[])

    def test_coverage_below_90_percent_excludes_common_year(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); cfg=self.fixture(root); analyze(cfg,root,'lsa')
            heat=read_json(root/'analysis/lsa/heatmap.json')
            self.assertFalse(any(x['year']==2024 for x in heat))
            self.assertTrue(any(x['year']==2026 for x in heat))

    def test_missing_model_assignment_is_a_hard_failure(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d); cfg=self.fixture(root)
            write_jsonl(root/'models/lsa/assignments.jsonl',[{'paper_id':'a','topic_id':0}])
            with self.assertRaisesRegex(ValueError,'assignment'):
                analyze(cfg,root,'lsa')


if __name__ == '__main__':
    unittest.main()
