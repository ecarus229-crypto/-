import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core, conversations, review_queue, maintenance, workspace

class VersionTwoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(core, 'APP_DIR', Path(self.tmp.name)/'data')
        self.patcher.start()
        self.root = Path(self.tmp.name)/'workspace'
        self.root.mkdir()
    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()

    def test_literal_casefold_search_and_isolation(self):
        a = conversations.list_all()[0][0]
        b = conversations.create('Второй')
        conversations.add_message(a,'user','СтРОКА%_ для поиска')
        conversations.add_message(b,'assistant','совсем другое')
        results = conversations.search_messages('%_')
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][1], a)
        self.assertEqual(len(conversations.search_messages('строка')), 1)
        self.assertEqual(conversations.search_messages('отсутствует'), [])
        for term in ('', 'z', 'x'*161):
            with self.assertRaises(ValueError):
                conversations.search_messages(term)

    def test_queue_requires_approval_and_persists(self):
        target=self.root/'test.txt'
        target.write_text('old',encoding='utf-8')
        plan={'summary':'change','actions':[{'type':'write_text','path':'test.txt','content':'new'}]}
        (sid,)=review_queue.enqueue(self.root,plan)
        self.assertEqual(target.read_text(), 'old')
        self.assertEqual(review_queue.pending()[0][0],sid)
        root,name,draft=review_queue.preview(sid)
        with self.assertRaises(PermissionError):
            review_queue.decide(sid,'apply',draft=draft,backup_dir=core.ensure_dir()/'backups')
        with self.assertRaises(ValueError):
            review_queue.decide(sid,'apply',approved=True,draft=None,backup_dir=core.ensure_dir()/'backups')
        self.assertEqual(review_queue.decide(sid,'apply',approved=True,draft=draft,
                          backup_dir=core.ensure_dir()/'backups'),'applied')
        self.assertEqual(target.read_text(), 'new')
        self.assertTrue(list((core.ensure_dir()/'backups').glob('*.bak')))
        with self.assertRaises(ValueError):
            review_queue.decide(sid,'apply',approved=True,draft=draft,backup_dir=core.ensure_dir()/'backups')

    def test_queue_rejects_stale_file(self):
        target=self.root/'test.txt'
        target.write_text('original',encoding='utf-8')
        (sid,)=review_queue.enqueue(self.root,{'summary':'x','actions':[{'type':'write_text','path':'test.txt','content':'new'}]})
        _,_,draft=review_queue.preview(sid)
        target.write_text('changed externally',encoding='utf-8')
        with self.assertRaises(workspace.WorkspaceError):
            review_queue.decide(sid,'apply',approved=True,draft=draft,backup_dir=core.ensure_dir()/'backups')
        self.assertEqual(target.read_text(), 'changed externally')
        self.assertEqual(review_queue.pending()[0][3], 'pending')
        self.assertEqual(review_queue.decide(sid,'reject',approved=True),'rejected')

    def test_queue_disallows_traversal(self):
        plan={'summary':'bad','actions':[{'type':'write_text','path':'../outside.txt','content':'bad'}]}
        with self.assertRaises(workspace.WorkspaceError):
            review_queue.enqueue(self.root,plan)
        self.assertFalse(review_queue.pending())

    def test_legacy_purge_keeps_migrated_messages(self):
        core.add_message('user','old data')
        cid=conversations.list_all()[0][0]
        with self.assertRaises(PermissionError):
            maintenance.clear_legacy_history()
        self.assertEqual(maintenance.clear_legacy_history(approved=True),1)
        self.assertEqual(conversations.history(cid), [('user','old data')])
        self.assertEqual(conversations.list_all()[0][0],cid)
        self.assertEqual(maintenance.clear_legacy_history(approved=True),0)
