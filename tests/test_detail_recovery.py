"""Recovery contracts: keep evidence after prepare and preserve completed work.

All HTTP is an in-memory boundary fake. Production data and the active backfill
process are never touched by this suite.
"""
from copy import deepcopy
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from ai_trends.common import read_jsonl, write_jsonl
from ai_trends.details import backfill, parse_detail
from ai_trends.processing import event_to_paper, prepare


CONFIG={'venues':['ICLR'],'years':[2024],'http':{'workers':1}}


def paper(number,abstract=''):
    return event_to_paper(dict(id=number,sourceid=number,name='Paper '+str(number),authors=['Ada Author'],sourceurl='https://openreview.net/group?id=ICLR.cc/2024/Conference',paper_url='https://openreview.net/forum?id=forum'+str(number),decision='Accept',abstract=abstract),'ICLR',2024)


def task(p,reason='main_missing_abstract'):
    return {k:p[k] for k in ('paper_id','source_url','title','venue','year')}|{'reason':reason}


class MemoryHTTP:
    def __init__(self,directory=b'<html><body></body></html>'):
        self.directory=directory;self.calls=[]
    def fetch(self,url):
        self.calls.append(url)
        if url.endswith('/papers.html'):body=self.directory
        else:
            number=int(url.rsplit('/',1)[-1])
            work={'@type':'ScholarlyArticle','name':'Paper '+str(number),'author':[{'name':'Ada Author'}],'abstract':'Recovered abstract '+str(number)}
            body=('<script type="application/ld+json">'+json.dumps(work)+'</script>').encode()
        return body,{'url':url,'sha256':'detail-snapshot','body_path':'raw/http/fixture.body.gz','collected_at':'2026-10-28T00:00:00Z'}


def run_without_live_http(config,out,client,**kwargs):
    with patch('ai_trends.details.HttpClient',return_value=client),patch('sys.stdout',new=io.StringIO()):
        return backfill(config,out,**kwargs)


class DetailRecoveryTests(unittest.TestCase):
    def test_prepare_then_backfill_keeps_repair_needed_to_rebuild_from_bulk(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);original=paper(1);repaired=deepcopy(original);repaired['abstract']='Recovered abstract'
            write_jsonl(out/'bulk/papers.jsonl',[original]);write_jsonl(out/'bulk/reviews.jsonl',[])
            write_jsonl(out/'processed/papers.jsonl',[repaired])
            old_task=task(original)
            old_patch={'paper_id':original['paper_id'],'title':original['title'],'title_match':True,'abstract':'Recovered abstract','snapshot_sha256':'detail-snapshot'}
            write_jsonl(out/'details/plan.jsonl',[old_task]);write_jsonl(out/'details/patches.jsonl',[old_patch])
            write_jsonl(out/'details/attempts.jsonl',[old_task|{'status':'success'}])
            client=MemoryHTTP();summary=run_without_live_http(CONFIG,out,client)
            self.assertEqual(summary['planned'],1)
            self.assertEqual(read_jsonl(out/'details/patches.jsonl'),[old_patch])
            self.assertEqual([u for u in client.calls if not u.endswith('/papers.html')],[])
            prepare(CONFIG,out,with_details=True)
            rebuilt=read_jsonl(out/'processed/papers.jsonl')
            self.assertEqual(rebuilt[0]['abstract'],'Recovered abstract')

    def test_completed_directory_resume_keeps_authors_abstract_and_source_hash(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);known=paper(1,'Existing abstract');extra=paper(2,'Recovered abstract')
            extra.update(paper_id='ICLR-2024-directory-2',source='official_live_directory',track='unknown',decision='unknown')
            write_jsonl(out/'bulk/papers.jsonl',[known]);write_jsonl(out/'processed/papers.jsonl',[known,extra])
            old_task=task(extra,'directory_missing_from_bulk')
            old_patch={'paper_id':extra['paper_id'],'title':extra['title'],'title_match':True,'abstract':'Recovered abstract','authors':['Ada Author'],'openreview_id':'forum2','track':'unknown','snapshot_sha256':'detail-snapshot','snapshot_body_path':'raw/http/fixture.body.gz'}
            write_jsonl(out/'details/plan.jsonl',[old_task]);write_jsonl(out/'details/patches.jsonl',[old_patch]);write_jsonl(out/'details/attempts.jsonl',[old_task|{'status':'success'}])
            client=MemoryHTTP(b'<a href="/virtual/2024/poster/2">Paper 2</a>')
            summary=run_without_live_http(CONFIG,out,client)
            rows=read_jsonl(out/'details/directory_papers.jsonl')
            self.assertEqual(summary['remaining'],0)
            self.assertEqual(len(rows),1)
            self.assertEqual(rows[0]['authors'],['Ada Author'])
            self.assertEqual(rows[0]['abstract'],'Recovered abstract')
            self.assertEqual(rows[0]['metadata'].get('detail_snapshot_sha256'),'detail-snapshot')
            self.assertEqual(summary['directory_new_papers'],1)
            self.assertEqual([u for u in client.calls if not u.endswith('/papers.html')],[])

    def test_navigation_data_track_cannot_promote_a_paper(self):
        work='<script type="application/ld+json">{"@type":"ScholarlyArticle","name":"A paper","abstract":"Scientific abstract"}</script>'
        result=parse_detail(work+'<nav data-track="main">Main Track</nav>','https://iclr.cc/virtual/2024/poster/1')
        self.assertEqual(result['track'],'unknown')
        # Explicit paper-scoped evidence remains supported.
        explicit=parse_detail(work+'<article data-track="main"></article>','https://iclr.cc/virtual/2024/poster/1')
        self.assertEqual(explicit['track'],'main')

    def test_retry_failed_retries_only_network_failure_or_missing_abstract(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d);papers=[paper(i) for i in range(1,5)]
            write_jsonl(out/'bulk/papers.jsonl',papers);write_jsonl(out/'processed/papers.jsonl',papers)
            tasks=[task(p) for p in papers]
            statuses=['failed','missing_abstract','blocked','title_conflict']
            attempts=[t|{'status':s,'error':'original failure'} for t,s in zip(tasks,statuses)]
            write_jsonl(out/'details/plan.jsonl',tasks);write_jsonl(out/'details/attempts.jsonl',attempts)
            default_client=MemoryHTTP();run_without_live_http(CONFIG,out,default_client)
            self.assertEqual([u for u in default_client.calls if not u.endswith('/papers.html')],[])
            retry_client=MemoryHTTP();run_without_live_http(CONFIG,out,retry_client,retry_failed=True)
            requested={u for u in retry_client.calls if not u.endswith('/papers.html')}
            self.assertEqual(requested,{papers[0]['source_url'],papers[1]['source_url']})
            after={r['paper_id']:r['status'] for r in read_jsonl(out/'details/attempts.jsonl')}
            self.assertEqual([after[p['paper_id']] for p in papers],['success','success','blocked','title_conflict'])
            self.assertEqual(len(read_jsonl(out/'details/attempts_history.jsonl')),2)


if __name__=='__main__':unittest.main()
