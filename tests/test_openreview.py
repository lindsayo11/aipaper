"""Offline OpenReview contracts from published API1/API2 schemas.

Network boundary fakes model capped pages, private fields, exact invitation
schemas, and platform verification. No live OpenReview requests occur.
"""
from __future__ import annotations
import json
from pathlib import Path
import tempfile
import unittest
from urllib.parse import parse_qs, urlparse

from ai_trends.common import FetchError, read_jsonl, write_json, write_jsonl, sha256
from ai_trends.collectors import (fetch_openreview_notes, get_openreview_group,
    score_schema_from_invitation, parse_score, openreview_note_to_paper,
    collect_openreview, parse_public_replies)


VENUE='ICLR.cc/2024/Conference'


def note(n,venueid=None,readers=None,replies=None):
    content={'title':{'value':'Title '+n},'abstract':{'value':'Scientific abstract '+n},'authors':{'value':['Ada Author']},'keywords':{'value':['learning']}}
    if venueid is not None:content['venueid']={'value':venueid}
    return dict(id=n,forum=n,number=1,invitations=[VENUE+'/-/Submission'],readers=['everyone'] if readers is None else readers,content=content,tmdate=123,details={'directReplies':replies or []})


def group():
    return dict(id=VENUE,readers=['everyone'],content={k:{'value':v} for k,v in dict(submission_id=VENUE+'/-/Submission',submission_name='Submission',submission_venue_id=VENUE+'/Submission',rejected_venue_id=VENUE+'/Rejected_Submission',withdrawn_venue_id=VENUE+'/Withdrawn_Submission',desk_rejected_venue_id=VENUE+'/Desk_Rejected_Submission',review_name='Official_Review',review_rating='rating',review_confidence='confidence').items()})


class FakeClient:
    def __init__(self,handler):self.handler=handler;self.calls=[]
    def fetch(self,url):
        self.calls.append(url)
        data=self.handler(url)
        body=json.dumps(data).encode()
        return body,dict(url=url,sha256=sha256(body),collected_at='2026-10-28T00:00:00Z')


class PaginationTests(unittest.TestCase):
    def test_short_capped_pages_and_page_local_counts_do_not_truncate(self):
        pages={None:([note('a')],3),'a':([note('b')],2),'b':([note('c')],1),'c':([],0)}
        def handler(url):
            cursor=parse_qs(urlparse(url).query).get('after',[None])[0]
            notes,count=pages[cursor];return {'notes':notes,'count':count}
        client=FakeClient(handler)
        rows,metas,info=fetch_openreview_notes(client,'https://api2.openreview.net',{'invitation':VENUE+'/-/Submission'},page_size=1000)
        self.assertEqual([r['id'] for r in rows],['a','b','c'])
        self.assertEqual(len(client.calls),4)
        self.assertTrue(info['traversal_complete'])
        self.assertEqual(info['announced_count'],3)

    def test_repeated_cursor_is_a_failure(self):
        client=FakeClient(lambda url:{'notes':[note('a')],'count':3})
        with self.assertRaisesRegex(RuntimeError,'cursor|cycle|progress'):
            fetch_openreview_notes(client,'https://api2.openreview.net',{'invitation':VENUE+'/-/Submission'})


class VersionAndPrivacyTests(unittest.TestCase):
    def test_api2_empty_group_falls_back_to_api1(self):
        client=FakeClient(lambda url:{'groups':[] if urlparse(url).hostname=='api2.openreview.net' else [group()]})
        actual,base,meta=get_openreview_group(client,VENUE)
        self.assertEqual(actual['id'],VENUE)
        self.assertEqual(base,'https://api.openreview.net')
        self.assertEqual(len(client.calls),2)

    def test_api2_404_group_falls_back_to_api1(self):
        def handler(url):
            if urlparse(url).hostname=='api2.openreview.net':raise FetchError('Not found',404)
            return {'groups':[group()]}
        actual,base,meta=get_openreview_group(FakeClient(handler),VENUE)
        self.assertEqual(base,'https://api.openreview.net')

    def test_platform_verification_never_falls_back(self):
        def handler(url):raise FetchError('ChallengeRequiredError',403,True)
        client=FakeClient(handler)
        with self.assertRaises(FetchError):get_openreview_group(client,VENUE)
        self.assertEqual(len(client.calls),1)

    def test_api2_non_404_failure_does_not_fallback(self):
        def handler(url):raise FetchError('Server unavailable',503)
        client=FakeClient(handler)
        with self.assertRaises(FetchError):get_openreview_group(client,VENUE)
        self.assertEqual(len(client.calls),1)

    def test_public_note_does_not_reveal_restricted_fields(self):
        n=note('a',VENUE)
        n['content']['authors']={'value':['Private author'],'readers':['Program_Chairs']}
        p=openreview_note_to_paper(n,'ICLR',2024,group())
        self.assertEqual(p['authors'],[])
        self.assertEqual(p['track'],'main')
        self.assertEqual(p['decision'],'accepted')
        self.assertIsNone(openreview_note_to_paper(note('private',VENUE,readers=['private']),'ICLR',2024,group()))


class ScaleAndDecisionTests(unittest.TestCase):
    def test_api2_schema_uses_actual_noncontiguous_enum(self):
        inv={'id':VENUE+'/Submission1/-/Official_Review','edit':{'note':{'content':{'rating':{'value':{'param':{'type':'string','enum':['1: reject','4: weak reject','8: accept']}}},'confidence':{'value':{'param':{'type':'integer','range':[1,5]}}}}}}}
        schema=score_schema_from_invitation(inv)
        self.assertEqual(parse_score('8: accept',schema['rating']),(8,1,8))
        self.assertEqual(parse_score('5: arbitrary',schema['rating']),(None,1,8))
        self.assertEqual(parse_score(4,schema['confidence']),(4,1,5))

    def test_api1_zero_rating_and_radio_schema(self):
        inv={'id':'legacy/-/Official_Review','reply':{'content':{'rating':{'value-dropdown':['0: poor','1: fair','2: good']},'confidence':{'value-radio':['1: low','3: high']}}}}
        schema=score_schema_from_invitation(inv)
        self.assertEqual(parse_score(0,schema['rating']),(0,0,2))
        self.assertEqual(parse_score('2: fabricated',schema['confidence']),(None,1,3))

    def test_status_mapping_never_turns_unknown_into_rejection(self):
        expected={VENUE:'accepted',VENUE+'/Submission':'under_review',VENUE+'/Rejected_Submission':'rejected',VENUE+'/Withdrawn_Submission':'withdrawn',VENUE+'/Desk_Rejected_Submission':'desk_rejected','unknown-venue':'unknown',None:'unknown'}
        for vid,decision in expected.items():
            with self.subTest(vid=vid):
                p=openreview_note_to_paper(note('a',vid),'ICLR',2024,group())
                self.assertEqual(p['decision'],decision)

    def test_review_quality_and_private_field_ratings_stay_separate(self):
        review=dict(id='r',forum='a',readers=['everyone'],invitations=[VENUE+'/Submission1/-/Official_Review'],content={'rating':{'value':'8: accept'},'confidence':{'value':'3: high','readers':['private']}},tmdate=123)
        quality=dict(id='q',forum='a',replyto='r',readers=['everyone'],invitations=[VENUE+'/Submission1/-/Rating'],content={'review_quality':{'value':'5: excellent'}},tmdate=124)
        rv,dc,qr=parse_public_replies([review,quality],'ICLR',2024,{'rating':['1: reject','8: accept'],'confidence':['1: low','3: high']})
        self.assertEqual(len(rv),1);self.assertEqual(rv[0]['rating'],8);self.assertIsNone(rv[0]['confidence'])
        self.assertEqual(len(qr),1);self.assertEqual(qr[0]['classification'],'review_quality_rating_not_paper_score')


class CollectionTests(unittest.TestCase):
    def test_second_page_challenge_retains_first_page_papers_and_stops_channel(self):
        def handler(url):
            parsed=urlparse(url);query=parse_qs(parsed.query)
            if parsed.path=='/groups':return {'groups':[group()]}
            if parsed.path=='/notes' and 'after' not in query:return {'notes':[note('a',VENUE)],'count':2}
            if parsed.path=='/notes':raise FetchError('ChallengeRequiredError',403,True)
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);client=FakeClient(handler)
            coverage=[{'venue':'ICLR','year':2024},{'venue':'ICML','year':2025}]
            collect_openreview(client,{},out,coverage)
            papers=read_jsonl(out/'bulk/openreview_papers.jsonl')
            self.assertEqual([p['paper_id'] for p in papers],['ICLR-2024-or-a'])
            self.assertEqual(len(read_jsonl(out/'bulk/openreview_submissions.jsonl')),1)
            self.assertTrue(all(r['openreview']['status']=='blocked' for r in coverage))
            self.assertEqual(coverage[0]['openreview']['submission_count'],1)
            self.assertEqual(len(client.calls),3)

    def test_public_collection_emits_linked_papers_and_real_schema_scores(self):
        review=dict(id='r',forum='a',readers=['everyone'],invitations=[VENUE+'/Submission1/-/Official_Review'],content={'rating':{'value':'8: accept'},'confidence':{'value':'3: high'}},tmdate=125)
        quality=dict(id='q',forum='a',replyto='r',readers=['everyone'],invitations=[VENUE+'/Submission1/-/Rating'],content={'review_quality':{'value':5}},tmdate=126)
        notes=[note('a',VENUE,replies=[review,quality]),note('b','unknown-venue'),note('private',VENUE,readers=['private'])]
        inv={'id':VENUE+'/Submission1/-/Official_Review','readers':['everyone'],'edit':{'note':{'content':{'rating':{'value':{'param':{'type':'string','enum':['1: reject','8: accept']}}},'confidence':{'value':{'param':{'type':'string','enum':['1: low','3: high']}}}}}}}
        def handler(url):
            p=urlparse(url);query=parse_qs(p.query)
            if p.path=='/groups':return {'groups':[group()]}
            if p.path=='/notes':return {'notes':[] if 'after' in query else notes,'count':0 if 'after' in query else 3}
            if p.path=='/invitations':return {'invitations':[inv] if inv['id'] in query.get('ids',[])+query.get('id',[]) else [],'count':1}
            raise AssertionError(url)
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);coverage=[{'venue':'ICLR','year':2024}]
            collect_openreview(FakeClient(handler),{'openreview':{'page_size':1000}},out,coverage)
            ps=read_jsonl(out/'bulk/openreview_papers.jsonl');rs=read_jsonl(out/'bulk/reviews.jsonl')
            self.assertEqual(len(ps),2)
            self.assertEqual(next(p for p in ps if p['openreview_id']=='a')['paper_id'],'ICLR-2024-or-a')
            self.assertEqual(rs[0]['paper_id'],'ICLR-2024-or-a')
            self.assertEqual(rs[0]['rating'],8)
            self.assertEqual((rs[0]['scale_min'],rs[0]['scale_max']),(1,8))
            self.assertEqual(len(read_jsonl(out/'bulk/review_quality_ratings.jsonl')),1)
            self.assertFalse(coverage[0]['openreview']['complete_decision_cohort'])
            self.assertEqual(coverage[0]['openreview']['excluded_not_public'],1)

    def test_blocked_restart_makes_no_calls_and_keeps_prior_public_reviews(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);write_json(out/'openreview_state.json',{'blocked':True,'blocked_at':'2026-10-28T00:00:00Z'})
            prior={'review_id':'prior','paper_id':'ICLR-2024-or-a','rating':8,'updated_at':123}
            write_jsonl(out/'bulk/reviews.jsonl',[prior])
            client=FakeClient(lambda url:(_ for _ in ()).throw(AssertionError('No request allowed')))
            coverage=[{'venue':'ICLR','year':2024},{'venue':'ICML','year':2025}]
            collect_openreview(client,{},out,coverage)
            self.assertEqual(client.calls,[])
            self.assertEqual(read_jsonl(out/'bulk/reviews.jsonl'),[prior])
            self.assertTrue(all(r['openreview']['status']=='blocked' for r in coverage))


if __name__=='__main__':unittest.main()
