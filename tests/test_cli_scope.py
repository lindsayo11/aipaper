import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from ai_trends.common import write_json,sha256

class ScopeGuard(unittest.TestCase):
    def test_prepare_cannot_relabel_existing_collection_as_another_scope(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'output';a={'venues':['ICLR'],'years':[2024],'http':{}}
            write_json(out/'collection_scope.json',{'sha256':sha256(json.dumps(a,sort_keys=True)),'config':a})
            changed={**a,'years':[2025]};write_json(root/'changed.json',changed)
            runner=Path(__file__).resolve().parents[1]/'scripts/run.py'
            p=subprocess.run([sys.executable,str(runner),'--config',str(root/'changed.json'),'--output',str(out),'prepare'],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertIn('another output directory',p.stderr)
            self.assertFalse((out/'processed/papers.jsonl').exists())

if __name__=='__main__':unittest.main()
