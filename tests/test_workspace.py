import tempfile
import unittest
from pathlib import Path
from assistant_app import workspace, agent, diagnostics


class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'root'
        self.root.mkdir()
        self.other = Path(self.temp.name) / 'secret.txt'
        self.other.write_text('SECRET', encoding='utf-8')
        self.file = self.root / 'hello.txt'
        # Stable fixture: Path.write_text() expands LF to CRLF on Windows.
        self.file.write_bytes(b'before\n')

    def test_stay_inside_root(self):
        for location in ('../secret.txt', str(self.other)):
            with self.assertRaises(workspace.WorkspaceError):
                workspace.safe_path(self.root, location)

    def test_safe_read(self):
        self.assertEqual(workspace.read_text(self.root, 'hello.txt'), 'before\n')

    def test_preview_and_backup(self):
        draft = workspace.draft_change(self.root, 'hello.txt', 'after\n')
        self.assertIn('-before', draft['diff'])
        self.assertIn('+after', draft['diff'])
        backups = self.root / 'backups'
        backup = workspace.apply_change(self.root, draft, backups)
        self.assertEqual(self.file.read_text(encoding='utf-8'), 'after\n')
        self.assertEqual(Path(backup).read_text(encoding='utf-8'), 'before\n')

    def test_reject_concurrent_edit(self):
        draft = workspace.draft_change(self.root, 'hello.txt', 'after')
        self.file.write_text('changed independently', encoding='utf-8')
        with self.assertRaises(workspace.WorkspaceError):
            workspace.apply_change(self.root, draft, self.root / 'backup')

    def test_reject_too_large(self):
        with self.assertRaises(workspace.WorkspaceError):
            workspace.draft_change(self.root, 'hello.txt', 'z' * (workspace.MAX_WRITE_BYTES+1))

    def test_symlink_escape(self):
        link = self.root / 'shortcut'
        try:
            link.symlink_to(self.other)
        except (OSError, NotImplementedError):
            self.skipTest('symlink not permitted')
        with self.assertRaises(workspace.WorkspaceError):
            workspace.read_text(self.root, link)

    def test_model_context_untrusted(self):
        prompt = agent.build_file_question(self.root, 'hello.txt', 'Что написано?')
        self.assertIn('НЕДОВЕРЕННЫМ', prompt)
        self.assertIn('before', prompt)

    def test_list(self):
        self.assertIn(('hello.txt', self.file.stat().st_size), workspace.list_files(self.root))

    def test_local_endpoint(self):
        self.assertTrue(diagnostics.local_endpoint('http://127.0.0.1:8080/v1'))
        for address in ('http://127.0.0.1.evil.com:8080/v1', 'http://example.com:8080/v1',
                        'http://localhost:8080@evil.com/v1', 'https://example.com/v1'):
            self.assertFalse(diagnostics.local_endpoint(address))
