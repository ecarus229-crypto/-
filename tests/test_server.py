import tempfile
import unittest
from pathlib import Path
from assistant_app.server import ServerManager

class ServerTests(unittest.TestCase):
    def test_invalid_files_cannot_start(self):
        manager=ServerManager()
        with tempfile.TemporaryDirectory() as td:
            ex=Path(td)/'not-llama.exe'; ex.write_text('x')
            model=Path(td)/'test.gguf'; model.write_text('x')
            with self.assertRaises(ValueError):
                manager.start(ex, model)
            self.assertFalse(manager.is_running())
