import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core

class ReleaseTests(unittest.TestCase):
    def test_cloud_fallback_off_by_default(self):
        cfg = core.DEFAULT_CONFIG.copy()
        cfg['local_url'] = 'http://127.0.0.1:9/v1'
        cfg['timeout_seconds'] = 5
        with self.assertRaisesRegex(RuntimeError, 'отключено для приватности'):
            core.chat(cfg, [{'role':'user','content':'hi'}], cloud_key='fake')

    def test_notes_and_export(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core, 'APP_DIR', Path(td)):
            core.add_note('test', 'some text')
            notes = core.list_notes()
            self.assertEqual(notes[0][1:], ('test', 'some text'))
            core.remove_note(notes[0][0])
            self.assertFalse(core.list_notes())
            core.add_message('user', 'hello')
            dest = Path(td) / 'export.json'
            self.assertEqual(core.export_history(dest), 1)
            self.assertIn('hello', dest.read_text(encoding='utf-8'))

    def test_block_redirects_and_plain_remote_http(self):
        for url in ('http://evil.com/v1', 'http://localhost:8080@evil.com/v1',
                    'https://user:password@api.example.org/v1'):
            with self.assertRaises(ValueError):
                core.request_chat(url, 'model', '', [])
