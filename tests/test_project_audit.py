import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import project_audit

class AuditTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)
    def tearDown(self):
        self.tmp.cleanup()
    def test_clean_python_and_json(self):
        (self.base/'good.py').write_text('x = 2\n', encoding='utf-8')
        (self.base/'good.json').write_text('{"x":2}', encoding='utf-8')
        report = project_audit.scan(self.base)
        self.assertEqual(report['scanned'], 2)
        self.assertEqual(report['findings'], [])
    def test_syntax_detection(self):
        (self.base/'broken.py').write_text('def hi(:\n', encoding='utf-8')
        (self.base/'broken.json').write_text('{"a":}', encoding='utf-8')
        found = project_audit.scan(self.base)['findings']
        self.assertEqual({f['kind'] for f in found}, {'Синтаксис Python', 'Синтаксис JSON'})
    def test_secret_never_in_report(self):
        value='VERYPRIVATEabcdef123456'
        (self.base/'main.py').write_text('api_key = "'+value+'"\n# TODO rewrite\n', encoding='utf-8')
        output = project_audit.render(project_audit.scan(self.base))
        self.assertIn('Конфиденциальные данные', output)
        self.assertIn('Задача в коде', output)
        self.assertNotIn(value, output)
    def test_env_excluded(self):
        (self.base/'.env').write_text('password=SUPERSECRETSECRET', encoding='utf-8')
        report = project_audit.scan(self.base)
        self.assertEqual(report['scanned'],0)
        self.assertNotIn('SUPERSECRET', project_audit.render(report))
    def test_binary_excluded(self):
        (self.base/'a.exe').write_bytes(b'password=secretsecret')
        self.assertEqual(project_audit.scan(self.base)['scanned'],0)
    def test_large_skipped(self):
        (self.base/'huge.py').write_text('x'* (project_audit.MAX_READ_BYTES + 2), encoding='utf-8')
        self.assertEqual(project_audit.scan(self.base)['skipped'], 1)
    def test_symlink_skipped(self):
        (self.base/'normal.py').write_text('x=1', encoding='utf-8')
        try: (self.base/'alias.py').symlink_to(self.base/'normal.py')
        except (OSError, NotImplementedError): self.skipTest('symlink restricted')
        self.assertEqual(project_audit.scan(self.base)['scanned'],1)
    def test_bound_results(self):
        (self.base/'many.py').write_text('# TODO\n'*300, encoding='utf-8')
        report = project_audit.scan(self.base)
        self.assertEqual(len(report['findings']), project_audit.MAX_RESULTS)
        self.assertTrue(report['truncated'])
    def test_ui_is_connected(self):
        from assistant_app.main import App
        self.assertTrue(callable(getattr(App, 'audit_project_window', None)))
    def test_release_names_agree(self):
        root=Path(__file__).resolve().parents[1]
        workflow=(root/'.github/workflows/build-windows.yml').read_text(encoding='utf-8')
        iss=(root/'installer/PersonalAI.iss').read_text(encoding='utf-8')
        import re
        version = re.search(r'#define MyAppVersion "([^"]+)"', iss).group(1)
        self.assertIn(f'output/PersonalAI-Setup-{version}.exe', workflow)
        self.assertIn(f'OutputBaseFilename=PersonalAI-Setup-{version}', iss)
        self.assertIn(f'PersonalAI-v{version}-Windows-Setup', workflow)
if __name__ == '__main__': unittest.main()
