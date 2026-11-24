import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import model_inventory

class InventoryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def model(self, name='sample.gguf', version=3, data=b'abc'):
        target = self.root/name
        target.write_bytes(b'GGUF' + version.to_bytes(4, 'little') + data)
        return target

    def test_valid_format(self):
        info = model_inventory.inspect_model(self.model())
        self.assertEqual(info['version'], 3)
        self.assertEqual(info['size'], 11)

    def test_invalid_magic(self):
        path = self.model()
        path.write_bytes(b'NOTG' + bytes(8))
        with self.assertRaisesRegex(ValueError, 'сигнатура'):
            model_inventory.inspect_model(path)

    def test_invalid_version(self):
        with self.assertRaisesRegex(ValueError, 'версия'):
            model_inventory.inspect_model(self.model(version=100))

    def test_inventory_skips_invalid_files(self):
        self.model('ok.gguf')
        (self.root/'bad.gguf').write_bytes(b'no')
        (self.root/'other.txt').write_text('x')
        result = model_inventory.inventory(self.root)
        self.assertEqual([x['name'] for x in result['models']], ['ok.gguf'])
        self.assertEqual(result['skipped'], 1)

    def test_no_recursive_scan(self):
        nested = self.root/'sub'
        nested.mkdir()
        (nested/'nested.gguf').write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'x')
        self.assertEqual(model_inventory.inventory(self.root)['models'], [])

    def test_symlink_ignored(self):
        original = self.model()
        link = self.root/'link.gguf'
        try:
            link.symlink_to(original)
        except (OSError, NotImplementedError):
            self.skipTest('symlinks unavailable')
        with self.assertRaises(ValueError):
            model_inventory.inspect_model(link)
        self.assertEqual(model_inventory.inventory(self.root)['skipped'], 1)

    def test_checksum(self):
        path = self.model()
        self.assertEqual(model_inventory.checksum(path), hashlib.sha256(path.read_bytes()).hexdigest())

    def test_checksum_limit(self):
        with self.assertRaisesRegex(ValueError, 'лимит'):
            model_inventory.checksum(self.model(), max_bytes=5)

    def test_entry_limit(self):
        self.model('a.gguf')
        self.model('b.gguf')
        result = model_inventory.inventory(self.root, max_entries=1)
        self.assertEqual(len(result['models']), 1)
        self.assertEqual(result['skipped'], 1)

    def test_bad_folder(self):
        with self.assertRaises(ValueError):
            model_inventory.inventory(self.root/'missing')

    def test_gpu_guidance_is_not_promise(self):
        self.assertIn('проверки', model_inventory.guidance(1024))
        self.assertIn('CPU', model_inventory.guidance(9*1024**3))
