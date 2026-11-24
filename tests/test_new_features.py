import hashlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core, tasks, downloads, recognition


class NewFeaturesTests(unittest.TestCase):
    def test_tasks_lifecycle(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(core, 'APP_DIR', Path(tmp)):
            tid = tasks.create('Проверить конфиг', 'без выполнения')
            self.assertEqual(tasks.list_all()[0][3], 'planned')
            tasks.set_state(tid, 'done')
            self.assertEqual(tasks.list_all()[0][3], 'done')
            tasks.delete(tid)
            self.assertEqual(tasks.list_all(), [])

    def test_invalid_task_state(self):
        with self.assertRaises(ValueError):
            tasks.set_state(1, 'shell')

    def test_dangerous_download_urls(self):
        with tempfile.TemporaryDirectory() as tmp:
            for url in ('http://example.org/model.gguf', 'https://127.0.0.1/x',
                        'https://user:pass@example.org/x', 'https://example.org:8443/x'):
                with self.assertRaises(ValueError, msg=url):
                    downloads.validate(url, '0' * 64, str(Path(tmp)/'test.gguf'))

    def test_checksum_and_cleanup(self):
        class FakeOpener:
            def __init__(self, blob):
                self.blob = blob
            def open(self, req, timeout):
                return io.BytesIO(self.blob)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / 'model.gguf'
            blob = b'GGUF' + b'xyz' * 100
            result = downloads.download('https://example.org/model.gguf', hashlib.sha256(blob).hexdigest(),
                                        target, opener=FakeOpener(blob))
            self.assertEqual(result, len(blob))
            self.assertEqual(target.read_bytes(), blob)
            with self.assertRaises(FileExistsError):
                downloads.download('https://example.org/model.gguf', hashlib.sha256(blob).hexdigest(),
                                   target, opener=FakeOpener(blob))
            target.unlink()
            with self.assertRaises(ValueError):
                downloads.download('https://example.org/model.gguf', 'a'*64,
                                   target, opener=FakeOpener(blob))
            self.assertFalse(target.exists())
            self.assertFalse(list(Path(tmp).glob('*.part')))

    def test_download_size_limit(self):
        class FakeOpener:
            def open(self, req, timeout):
                return io.BytesIO(b'GGUF' + b'a' * 100)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                downloads.download('https://example.org/file.gguf', 'a'*64, Path(tmp)/'file.gguf',
                                   max_bytes=20, opener=FakeOpener())
            self.assertFalse(list(Path(tmp).iterdir()))

    def test_recognition_folder_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                recognition.transcribe_once(tmp)
