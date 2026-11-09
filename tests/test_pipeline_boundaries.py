"""Independent contract tests at identity, snapshot, and public-review boundaries.

All fixtures are synthetic; no external API, credentials or live OpenReview is
used. In particular, these checks never retry the blocked live channel.
"""
from __future__ import annotations
from copy import deepcopy
import gzip
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from ai_trends.common import HttpClient, FetchError, read_json, read_jsonl, write_jsonl
from ai_trends.processing import event_to_paper, merge_papers, apply_patches, prepare, forum_id, decision_from_text
from ai_trends.collectors import collect, fetch_pages, parse_public_replies


def paper(forum='forumA', event_id=1, title='An auditable scientific method', abstract=''):
    event=dict(id=event_id,uid='official-'+str(event_id),sourceid=1,name=title,abstract=abstract,authors=[{'fullname':'Ada Researcher'}],sourceurl='https://openreview.net/group?id=ICLR.cc/2024/Conference',decision='Accept',event_type='Poster')
    if forum:
        event['paper_url']='https://openreview.net/forum?id='+forum
    return event_to_paper(event,'ICLR',2024,{'collected_at':'2026-10-28T00:00:00Z','sha256':'snapshot'})


class IdentityBoundaryTests(unittest.TestCase):
    def test_official_display_placeholders_are_not_real_openreview_forums(self):
        self.assertEqual(forum_id('https://openreview.net/forum?id=2025-Oral--2229-e62823d9'),'')
        self.assertEqual(forum_id('https://openreview.net/forum?id=iRsZHAMNHL'),'iRsZHAMNHL')

    def test_negated_acceptance_does_not_become_accepted(self):
        self.assertEqual(decision_from_text('Reject (not accepted)'),'rejected')
        self.assertNotEqual(decision_from_text('Not accepted'),'accepted')

    def test_title_conflict_cannot_supply_abstract(self):
        a=paper(abstract='')
        b=paper(title='A completely different research paper',abstract='Wrong abstract')
        rows,quarantine=merge_papers([a,b])
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['abstract'],'')
        self.assertEqual(len(quarantine),1)

    def test_different_known_forums_do_not_merge_on_title_and_author(self):
        rows,_=merge_papers([paper('forumA'),paper('forumB')])
        self.assertEqual(len(rows),2)

    def test_a_missing_forum_does_not_bridge_two_different_known_forums(self):
        rows,_=merge_papers([paper(None),paper('forumA'),paper('forumB')])
        self.assertGreaterEqual(len(rows),2,'Unknown identity must not bridge distinct exact forum IDs')

    def test_track_conflict_stays_unknown_after_repeated_main_event(self):
        a=paper();b=deepcopy(a);b['track']='position';c=deepcopy(a)
        rows,q=merge_papers([a,b,c])
        self.assertEqual(rows[0]['track'],'unknown')
        self.assertTrue(q)

    def test_decision_conflict_stays_unknown_after_repeated_accept(self):
        a=paper();b=deepcopy(a);b['decision']='rejected';c=deepcopy(a)
        rows,q=merge_papers([a,b,c])
        self.assertEqual(rows[0]['decision'],'unknown')
        self.assertTrue(q)

    def test_detail_forum_conflict_cannot_supply_abstract_even_with_same_title(self):
        p=paper('forumA')
        incoming={'paper_id':p['paper_id'],'title':p['title'],'abstract':'Different identity abstract','openreview_id':'forumB'}
        rows,q=apply_patches([p],[incoming])
        self.assertEqual(rows[0]['abstract'],'')
        self.assertTrue(q)

    def test_bulk_quarantine_survives_prepare(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)
            write_jsonl(out/'bulk/papers.jsonl',[paper()])
            write_jsonl(out/'bulk/reviews.jsonl',[])
            conflict={'reason':'same_identity_title_conflict','paper_id':'known','kept_title':'Kept','incoming':{'title':'Conflict'}}
            write_jsonl(out/'bulk/ICLR-2024-quarantine.jsonl',[conflict])
            result=prepare({'venues':['ICLR'],'years':[2024]},out)
            self.assertIn(conflict,read_jsonl(out/'processed/quarantine.jsonl'))
            self.assertEqual(result['quarantine_count'],1)


class FakeResponse:
    def __init__(self,url,body):
        self.url=url;self.body=body;self.status=200;self.headers={'Content-Type':'application/json'}
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return self.body


class SnapshotBoundaryTests(unittest.TestCase):
    def test_captcha_research_in_valid_json_is_not_a_verification_page(self):
        with tempfile.TemporaryDirectory() as d:
            c=HttpClient(d,{'min_interval':0,'retries':0})
            url='https://example.org/papers'
            raw=b'{"title":"A scientific analysis of CAPTCHA recognition"}'
            with patch('ai_trends.common.urlopen',return_value=FakeResponse(url,raw)):
                body,meta=c.fetch(url)
            self.assertEqual(body,raw)
            self.assertEqual(meta['status'],'success')

    def test_successful_cache_is_reused_but_corruption_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c=HttpClient(d,{'min_interval':0,'retries':0})
            url='https://example.org/papers';raw=b'{"papers":[1]}'
            with patch('ai_trends.common.urlopen',return_value=FakeResponse(url,raw)) as net:
                first,meta=c.fetch(url)
                second,_=c.fetch(url)
                self.assertEqual((first,second),(raw,raw))
                self.assertEqual(net.call_count,1)
                (Path(d)/meta['body_path']).write_bytes(gzip.compress(b'tampered'))
                with self.assertRaisesRegex(FetchError,'hash'):
                    c.fetch(url)
                self.assertEqual(net.call_count,1)

    def test_platform_verification_is_not_retried_or_cached_as_success(self):
        with tempfile.TemporaryDirectory() as d:
            c=HttpClient(d,{'min_interval':0,'retries':4})
            url='https://example.org/blocked'
            error=HTTPError(url,403,'Forbidden',{},io.BytesIO(b'ChallengeRequiredError'))
            with patch('ai_trends.common.urlopen',side_effect=error) as net:
                with self.assertRaises(FetchError) as caught:c.fetch(url)
                self.assertTrue(caught.exception.challenge)
                self.assertEqual(net.call_count,1)
            metas=[read_json(p) for p in (Path(d)/'raw/http').glob('*.json')]
            self.assertEqual(len(metas),1)
            self.assertEqual(metas[0]['status'],'blocked')

    def test_empty_body_is_not_a_successful_snapshot(self):
        with tempfile.TemporaryDirectory() as d:
            c=HttpClient(d,{'min_interval':0,'retries':0})
            url='https://example.org/empty'
            with patch('ai_trends.common.urlopen',return_value=FakeResponse(url,b'')):
                with self.assertRaises(FetchError):c.fetch(url)
            self.assertNotIn('success',[read_json(p)['status'] for p in (Path(d)/'raw/http').glob('*.json')])


class PaginationAndReviewBoundaryTests(unittest.TestCase):
    def test_next_page_is_followed_and_cycles_are_rejected(self):
        class Client:
            def fetch(self,url):
                return json.dumps({'results':[url],'next':'?page=2' if 'page=2' not in url else '?page=2','count':3}).encode(),{'url':url}
        with self.assertRaisesRegex(RuntimeError,'cycle'):
            fetch_pages(Client(),'https://example.org/list')

    def test_each_event_points_to_its_own_source_page(self):
        root='https://iclr.cc/virtual/2024/papers.html'
        page1='https://iclr.cc/static/data-orals-posters.json'
        page2=page1+'?page=2'
        def event(n):
            return dict(id=n,uid='u'+str(n),sourceid=n,name='Paper '+str(n),authors=[{'fullname':'Author'}],abstract='Abstract',sourceurl='https://openreview.net/group?id=ICLR.cc/2024/Conference',paper_url='https://openreview.net/forum?id=forum'+str(n),decision='Accept')
        bodies={root:b'<script>start("/static/data-orals-posters.json")</script>',page1:json.dumps({'results':[event(1)],'next':'?page=2','count':2}).encode(),page2:json.dumps({'results':[event(2)],'next':None,'count':2}).encode()}
        class Client:
            def fetch(self,url):return bodies[url],dict(url=url,sha256='page2' if url==page2 else 'page1',collected_at='2026-10-28T00:00:00Z')
        def no_live_reviews(client,config,out,coverage):
            for r in coverage:r['openreview']={'status':'blocked'}
            return coverage
        with tempfile.TemporaryDirectory() as d:
            with patch('ai_trends.collectors.HttpClient',return_value=Client()),patch('ai_trends.collectors.collect_openreview',side_effect=no_live_reviews):
                collect({'venues':['ICLR'],'years':[2024],'http':{}},d)
            rows=read_jsonl(Path(d)/'bulk/papers.jsonl')
            p2=next(x for x in rows if x['title']=='Paper 2')
            self.assertTrue(any(s['sha256']=='page2' for s in p2['metadata']['source_snapshots']))

    def test_nonpublic_and_review_quality_ratings_do_not_become_paper_scores(self):
        def note(n,inv,readers,rating):return dict(id=n,forum='f',invitations=[inv],readers=readers,content={'rating':{'value':rating},'confidence':{'value':'3: confident'}},tmdate=123)
        notes=[note('review','ICLR.cc/2024/Conference/Paper1/-/Official_Review',['everyone'],'8: accept'),note('private','ICLR.cc/2024/Conference/Paper1/-/Official_Review',['private'],'10: accept'),note('quality','ICLR.cc/2024/Conference/Paper1/-/Review_Rating',['everyone'],'5: excellent review')]
        reviews,decisions,quality=parse_public_replies(notes,'ICLR',2024,{'rating':['1: reject','8: accept','10: strong accept'],'confidence':['1: unsure','3: confident']})
        self.assertEqual([r['review_id'] for r in reviews],['review'])
        self.assertEqual(reviews[0]['rating'],8)
        self.assertEqual(reviews[0]['scale_min'],1)
        self.assertEqual(reviews[0]['scale_max'],10)
        self.assertEqual([q['note_id'] for q in quality],['quality'])
        self.assertEqual(decisions,[])


if __name__=='__main__':unittest.main()
