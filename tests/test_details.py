import json
from pathlib import Path
import tempfile
import unittest
from ai_trends.details import canonical_detail,directory_items,parse_detail
from ai_trends.common import read_jsonl,write_jsonl

class DetailBoundaries(unittest.TestCase):
    def test_location_and_fragment_do_not_create_duplicate_requests(self):
        self.assertEqual(canonical_detail('https://neurips.cc/virtual/2026/loc/paris/poster/123#x'),'https://neurips.cc/virtual/2026/poster/123')
        body=b'<a href="/virtual/2026/loc/sydney/poster/123">Paper</a><a href="/virtual/2026/loc/paris/poster/123">Paper</a><a href="/accounts/login?nextp=/virtual/2026/poster/999">Login</a><a href="/virtual/2026/loc/paris/papers.html#main">Paris</a>'
        items,loc=directory_items(body,'https://neurips.cc/virtual/2026/papers.html',2026)
        self.assertEqual(len(items),1);self.assertEqual(items[0]['event_id'],123)
        self.assertEqual(loc,['https://neurips.cc/virtual/2026/loc/paris/papers.html'])
    def test_navigation_main_track_is_never_per_paper_evidence(self):
        body='<nav>Main Track Handbook</nav><h2>Title</h2><div id="abstractText"><div class="abstract-text-inner">Real &amp; useful $x &lt; y$</div></div><a href="https://openreview.net/forum?id=abcdefghij">OR</a>'
        p=parse_detail(body,'https://neurips.cc/virtual/2026/poster/1')
        self.assertEqual(p['track'],'unknown');self.assertEqual(p['decision'],'unknown')
        self.assertEqual(p['abstract'],'Real & useful $x < y$');self.assertEqual(p['openreview_id'],'abcdefghij')
    def test_jsonld_title_authors_and_dedicated_abstract(self):
        data={'@type':'CreativeWork','name':'Exact title','author':[{'@type':'Person','name':'A B'}]}
        body='<script type="application/ld+json">'+json.dumps(data)+'</script><h2>Other navigation</h2><div id="abstractText">Correct abstract</div>'
        p=parse_detail(body,'https://iclr.cc/virtual/2026/poster/2')
        self.assertEqual(p['title'],'Exact title');self.assertEqual(p['authors'],['A B']);self.assertEqual(p['abstract'],'Correct abstract')
    def test_jsonl_literal_unicode_line_separator_stays_one_record(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'x.jsonl';rows=[{'abstract':'A\u2028B\u2029C'}];write_jsonl(path,rows)
            self.assertEqual(read_jsonl(path),rows)

if __name__=='__main__':unittest.main()
