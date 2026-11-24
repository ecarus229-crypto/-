import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core, conversations

class ConversationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(core, 'APP_DIR', Path(self.tmp.name))
        self.patcher.start()
    def tearDown(self):
        self.patcher.stop()
        self.tmp.cleanup()
    def test_migrate_legacy_once(self):
        core.add_message('user', 'история')
        a = conversations.list_all()
        self.assertEqual(conversations.history(a[0][0]), [('user','история')])
        self.assertEqual(conversations.list_all(), a)
    def test_separation(self):
        a = conversations.list_all()[0][0]
        b = conversations.create('Другой')
        conversations.add_message(a, 'user', 'секрет')
        conversations.add_message(b, 'user', 'публичное')
        self.assertEqual(conversations.history(a), [('user','секрет')])
        self.assertEqual(conversations.history(b), [('user','публичное')])
        conversations.clear(a)
        self.assertFalse(conversations.history(a))
        self.assertEqual(conversations.count(), 1)
    def test_rename_delete_and_last_guard(self):
        a = conversations.list_all()[0][0]
        b = conversations.create('Тест')
        conversations.rename(b,'Новое')
        self.assertEqual(conversations.list_all()[0][1], 'Новое')
        conversations.delete(b)
        with self.assertRaises(ValueError):
            conversations.delete(a)
    def test_export_does_not_overwrite(self):
        a = conversations.list_all()[0][0]
        conversations.add_message(a, 'user', 'Привет')
        path = Path(self.tmp.name)/'chat.json'
        self.assertEqual(conversations.export(a,path), 1)
        self.assertEqual(json.loads(path.read_text(encoding='utf-8'))[0]['text'],'Привет')
        with self.assertRaises(FileExistsError):
            conversations.export(a,path)
    def test_invalid_messages(self):
        a = conversations.list_all()[0][0]
        with self.assertRaises(ValueError):
            conversations.add_message(a, 'system','injected')
        with self.assertRaises(ValueError):
            conversations.add_message(999999, 'user','not found')
    def test_purge(self):
        a = conversations.list_all()[0][0]
        conversations.add_message(a,'user','old')
        with core.db() as conn:
            conn.execute('UPDATE conversation_messages SET ts=1')
        self.assertEqual(conversations.purge_before(2), 1)
        self.assertFalse(conversations.history(a))
