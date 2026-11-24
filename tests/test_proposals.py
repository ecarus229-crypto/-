import json
import tempfile
import unittest
from pathlib import Path
from assistant_app import proposals, maintenance, workspace

class ProposalTests(unittest.TestCase):
    def test_valid(self):
        p = proposals.parse_proposal(json.dumps({'summary':'test','actions':[{'type':'write_text','path':'a.txt','content':'new'}]}))
        self.assertEqual(p['actions'][0]['path'], 'a.txt')
    def test_forbidden(self):
        for path in ('../outside.txt','/tmp/z.txt','C:/Windows/system32/x.txt',r'\\server\share'):
            with self.subTest(path=path):
                with self.assertRaises(proposals.ProposalError):
                    proposals.parse_proposal(json.dumps({'summary':'x','actions':[{'type':'write_text','path':path,'content':'x'}]}))
    def test_no_commands(self):
        with self.assertRaises(proposals.ProposalError):
            proposals.parse_proposal(json.dumps({'summary':'x','actions':[{'type':'shell','path':'a','content':'whoami'}]}))
    def test_size_and_duplicates(self):
        for actions in ([{'type':'write_text','path':'a','content':'x'}]*2, [{'type':'write_text','path':'a','content':'x'}]*5):
            with self.assertRaises(proposals.ProposalError):
                proposals.parse_proposal(json.dumps({'summary':'x','actions':actions}))
    def test_draft_no_write(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'a.txt').write_text('before')
            proposal=proposals.parse_proposal(json.dumps({'summary':'x','actions':[{'type':'write_text','path':'a.txt','content':'after'}]}))
            drafts=proposals.prepare_drafts(d,proposal)
            self.assertEqual(Path(d,'a.txt').read_text(),'before')
            self.assertIn('after',drafts[0][1]['diff'])
    def test_restore_guard(self):
        with tempfile.TemporaryDirectory() as d:
            base=Path(d); backup=base/'bak';backup.mkdir()
            (base/'file.txt').write_text('current')
            (backup/'test.bak').write_text('original')
            with self.assertRaises(PermissionError):
                maintenance.restore_backup(base,'file.txt',backup,'test.bak')
            with self.assertRaises(ValueError):
                maintenance.restore_backup(base,'file.txt',backup,'../test.bak',approved=True)
            maintenance.restore_backup(base,'file.txt',backup,'test.bak',approved=True)
            self.assertEqual((base/'file.txt').read_text(),'original')
            self.assertTrue(list(backup.glob('*.bak')))

if __name__=='__main__': unittest.main()
