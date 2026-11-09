from copy import deepcopy
import unittest
from ai_trends.processing import event_to_paper,merge_papers

class ExactForumAssociation(unittest.TestCase):
    def paper(self,title='Original title',abstract='Original abstract'):
        return event_to_paper({'id':123,'name':title,'abstract':abstract,'authors':['Ada Author'],'sourceurl':'https://openreview.net/group?id=NeurIPS.cc/2026/Conference','paper_url':'https://openreview.net/forum?id=abcdefghij','decision':'Accept'},'NeurIPS',2026)
    def test_directory_id_cannot_hide_same_forum_title_conflict(self):
        original=self.paper(abstract='')
        incoming=self.paper('Another scientific paper','Wrong abstract')
        incoming['paper_id']='NeurIPS-2026-directory-999'
        rows,quarantine=merge_papers([original,incoming])
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['abstract'],'')
        self.assertEqual(quarantine[0]['reason'],'same_identity_title_conflict')
    def test_directory_and_program_same_forum_keep_all_events(self):
        original=self.paper();incoming=deepcopy(original)
        incoming['paper_id']='NeurIPS-2026-directory-999';incoming['metadata']['event_ids']=[999]
        rows,quarantine=merge_papers([original,incoming])
        self.assertEqual(len(rows),1);self.assertEqual(quarantine,[])
        self.assertEqual(set(rows[0]['metadata']['event_ids']),{123,999})
    def test_exact_forum_association_is_scoped_to_venue_and_year(self):
        original=self.paper();incoming=deepcopy(original)
        incoming.update(venue='ICML',year=2025,paper_id='ICML-2025-or-abcdefghij')
        rows,quarantine=merge_papers([original,incoming])
        self.assertEqual(len(rows),2);self.assertEqual(quarantine,[])

if __name__=='__main__':unittest.main()
