import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path
from assistant_app import data_portability as backup


class BackupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / 'profile'
        self.home.mkdir()
        self.out = Path(self.tmp.name) / 'archive.zip'
        with closing(sqlite3.connect(self.home / 'memory.db')) as db:
            with db:
                db.execute('CREATE TABLE notes (text TEXT)')
                db.execute('INSERT INTO notes VALUES (?)', ('Приватная заметка',))
        (self.home / 'settings.json').write_text(json.dumps({
            'mode': 'local', 'api_key': 'DO_NOT_ARCHIVE',
            'other_secret': 'DO_NOT_ARCHIVE', 'local_model':'qwen'}), encoding='utf-8')

    def test_export_verifies_and_preserves_database(self):
        result = backup.export_backup(self.out, data_dir=self.home)
        self.assertTrue(result['valid'])
        with zipfile.ZipFile(self.out) as z:
            self.assertEqual(set(z.namelist()), {'memory.db','settings.json','manifest.json'})
            settings=z.read('settings.json').decode('utf-8')
            self.assertNotIn('DO_NOT_ARCHIVE', settings)
            self.assertEqual(json.loads(settings)['mode'], 'local')
        self.assertTrue(backup.verify_backup(self.out)['valid'])

    def test_reject_overwrite_and_inside_data_folder(self):
        backup.export_backup(self.out, data_dir=self.home)
        with self.assertRaises(FileExistsError):
            backup.export_backup(self.out, data_dir=self.home)
        with self.assertRaises(ValueError):
            backup.export_backup(self.home/'archive.zip', data_dir=self.home)

    def test_reject_tampering(self):
        backup.export_backup(self.out, data_dir=self.home)
        with zipfile.ZipFile(self.out, 'a') as z:
            z.writestr('unexpected.txt', 'bad')
        with self.assertRaises(ValueError):
            backup.verify_backup(self.out)

    def test_reject_path_traversal(self):
        with zipfile.ZipFile(self.out, 'w') as z:
            z.writestr('../memory.db', 'bad')
        with self.assertRaises(ValueError):
            backup.verify_backup(self.out)

    def test_reject_corrupt_sqlite_before_export(self):
        (self.home/'memory.db').write_bytes(b'not a sqlite database')
        with self.assertRaises(sqlite3.DatabaseError):
            backup.export_backup(self.out, data_dir=self.home)
        self.assertFalse(self.out.exists())

    def test_reject_symlink_database(self):
        db=self.home/'memory.db'
        db.unlink()
        target=Path(self.tmp.name)/'other.db'
        target.write_bytes(b'no')
        try:
            db.symlink_to(target)
        except (OSError, NotImplementedError):
            self.skipTest('Создание символьных ссылок ограничено в Windows')
        with self.assertRaises(ValueError):
            backup.export_backup(self.out, data_dir=self.home)
