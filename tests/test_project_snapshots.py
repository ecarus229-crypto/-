import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core, project_snapshots as snap

class SnapshotTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / 'project'
        self.root.mkdir()
        self.patcher = patch.object(core,'APP_DIR',self.base/'appdata')
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_change_detection(self):
        (self.root/'a.py').write_text('print(1)',encoding='utf-8')
        (self.root/'old.txt').write_text('old',encoding='utf-8')
        sid, state = snap.create(self.root,'До изменений')
        self.assertEqual(len(state['files']), 2)
        (self.root/'a.py').write_text('print(2)',encoding='utf-8')
        (self.root/'old.txt').unlink()
        (self.root/'new.txt').write_text('new',encoding='utf-8')
        _, _, diff, _ = snap.compare_to_disk(sid)
        self.assertEqual(diff['modified'], ['a.py'])
        self.assertEqual(diff['deleted'], ['old.txt'])
        self.assertEqual(diff['added'], ['new.txt'])
        self.assertEqual(len(snap.list_all(self.root)), 1)
        snap.delete(sid)
        self.assertFalse(snap.list_all(self.root))
        self.assertEqual((self.root/'a.py').read_text(), 'print(2)')

    def test_excludes_secrets_symlinks_large(self):
        (self.root/'.env').write_text('SECRET=abc')
        (self.root/'credentials.json').write_text('secret')
        (self.root/'large.bin').write_bytes(b'0' * 1024)
        (self.root/'ok.txt').write_text('okay')
        (self.root/'.git').mkdir()
        (self.root/'.git'/'config').write_text('hidden')
        outside = self.base / 'outside.txt'
        outside.write_text('not safe')
        try:
            (self.root/'alias.txt').symlink_to(outside)
        except OSError:
            pass
        with patch.object(snap,'MAX_FILE_SIZE',100):
            result = snap.scan(self.root)
        self.assertEqual(set(result['files']), {'ok.txt'})
        self.assertGreater(result['skipped'],0)

    def test_limit_reported(self):
        for i in range(4):
            (self.root/f'{i}.txt').write_text(str(i))
        with patch.object(snap,'MAX_FILES',2):
            result = snap.scan(self.root)
        self.assertEqual(len(result['files']),2)
        self.assertTrue(result['truncated'])
        d = snap.compare(result, {'files': {}, 'skipped':0,'truncated':False})
        self.assertTrue(d['incomplete'])
        self.assertIn('не было полным', snap.render_comparison(d))

    def test_names_and_hashes_only(self):
        marker = 'VERY_PRIVATE_PROJECT_CONTENT_98765'
        (self.root/'file.txt').write_text(marker)
        sid, state = snap.create(self.root)
        self.assertNotIn(marker, str(state))
        self.assertNotIn(marker, core.db().__repr__())
        self.assertNotIn(marker, (core.ensure_dir()/'memory.db').read_bytes().decode('latin1'))
        self.assertEqual(len(state['files']['file.txt']['sha256']),64)
        with self.assertRaises(ValueError):
            snap.create(self.root,' '*121)
        with self.assertRaises(ValueError):
            snap.load(sid+100)

if __name__ == '__main__':
    unittest.main()
