import json
import os
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from assistant_app import core

class CoreTests(unittest.TestCase):
    def test_config_never_saves_secret(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core, 'APP_DIR', Path(td)):
            core.save_config({**core.DEFAULT_CONFIG, 'api_key': 'very-secret'})
            self.assertNotIn('very-secret', core.config_path().read_text(encoding='utf-8'))
            self.assertNotIn('api_key', core.load_config())

    def test_history_and_clear(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core, 'APP_DIR', Path(td)):
            core.add_message('user', 'Hello')
            core.add_message('assistant', 'Hi')
            self.assertEqual(core.history(), [('user', 'Hello'), ('assistant', 'Hi')])
            core.clear_history()
            self.assertEqual(core.history(), [])

    def test_cloud_requires_https(self):
        with self.assertRaises(ValueError):
            core.request_chat('http://example.com/v1', 'model', '', [])

    def test_hybrid_fallback_requires_key(self):
        config = {**core.DEFAULT_CONFIG, 'local_url': 'http://127.0.0.1:9/v1', 'timeout_seconds': 5, 'cloud_fallback': True}
        with self.assertRaisesRegex(RuntimeError, 'API-ключ'):
            core.chat(config, [{'role': 'user', 'content': 'test'}])

if __name__ == '__main__':
    unittest.main()
