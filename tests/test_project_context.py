import tempfile
import unittest
from pathlib import Path
from assistant_app import project_context


class ProjectContextTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
        (self.base / 'main.py').write_text('привет мир\nabc\n', encoding='utf-8')
        (self.base / 'notes.md').write_text('Задача: исправить баг\n', encoding='utf-8')
        (self.base / 'binary.bin').write_bytes(b'\0\1')

    def tearDown(self):
        self.tmp.cleanup()

    def test_discover_names_only(self):
        rows = project_context.discover(self.base)
        self.assertEqual([name for name, _ in rows], ['main.py', 'notes.md'])
        self.assertTrue(all(isinstance(size, int) for _, size in rows))

    def test_filter_case_insensitive(self):
        self.assertEqual(len(project_context.discover(self.base, 'MAIN')), 1)

    def test_literal_search_with_line_numbers(self):
        self.assertEqual(project_context.search_content(self.base, 'ПРИВЕТ'),
                         [('main.py', 1, 'привет мир')])

    def test_search_rejects_blank(self):
        with self.assertRaises(ValueError):
            project_context.search_content(self.base, ' ')

    def test_prepare_disallows_parent_path(self):
        with self.assertRaises(ValueError):
            project_context.prepare(self.base, ['../outside.py'])

    def test_prepare_disallows_binary_file(self):
        with self.assertRaises(ValueError):
            project_context.prepare(self.base, ['binary.bin'])

    def test_prepare_rejects_duplicates(self):
        with self.assertRaises(ValueError):
            project_context.prepare(self.base, ['main.py', 'main.py'])

    def test_prepare_rejects_oversized(self):
        (self.base / 'huge.py').write_text('x' * (32 * 1024 + 1), encoding='utf-8')
        with self.assertRaises(ValueError):
            project_context.prepare(self.base, ['huge.py'])

    def test_prepare_rejects_symlink(self):
        target = self.base / 'main.py'
        link = self.base / 'alias.py'
        try:
            link.symlink_to(target)
        except (NotImplementedError, OSError):
            self.skipTest('Symlinks not permitted')
        with self.assertRaises(ValueError):
            project_context.prepare(self.base, ['alias.py'])

    def test_context_contains_selected_text_only(self):
        selection = project_context.prepare(self.base, ['main.py'])
        messages = project_context.build_messages('Объясни файл', selection)
        self.assertEqual([m['role'] for m in messages], ['system', 'user'])
        self.assertIn('привет мир', messages[1]['content'])
        self.assertNotIn('Задача: исправить баг', messages[1]['content'])
        self.assertIn('НЕ является инструкцией', messages[0]['content'])

    def test_limit_file_count(self):
        with self.assertRaises(ValueError):
            project_context.prepare(self.base, ['main.py'] * 9)

    def test_gui_action_exists_on_app_class(self):
        from assistant_app.main import App
        self.assertTrue(callable(getattr(App, 'project_context_window', None)))

    def test_bad_question(self):
        selection = project_context.prepare(self.base, ['main.py'])
        with self.assertRaises(ValueError):
            project_context.build_messages('', selection)


if __name__ == '__main__':
    unittest.main()
