import tempfile
import unittest
from pathlib import Path
from assistant_app import runtime_setup as r

class RuntimeSetupTests(unittest.TestCase):
    def test_profiles_are_explicit_and_conservative(self):
        self.assertEqual(r.profile_settings('CPU — надёжный старт')['gpu_layers'], 0)
        self.assertEqual(r.profile_settings('Vulkan — осторожный тест')['gpu_layers'], 8)
        self.assertEqual(r.profile_settings('Vulkan — расширенный тест')['context'], 4096)
    def test_no_arbitrary_profiles(self):
        with self.assertRaises(ValueError): r.profile_settings('shell:cmd')
    def test_ports(self):
        for port in (0, 80, 99999, 'nonsense'):
            with self.subTest(port=port), self.assertRaises(ValueError): r.profile_settings('CPU — надёжный старт', port)
    def test_local_url_prevents_external_network(self):
        for url in ('https://example.com/v1', 'http://localhost:8080@evil.com/v1',
                    'http://127.0.0.1:8080/v1?x=1', 'http://127.0.0.1:8080/admin',
                    'http://127.0.0.1:99999/v1', 'file:///tmp/v1'):
            with self.subTest(url=url), self.assertRaises(ValueError): r.validate_local_base(url)
    def test_loopback_only(self):
        self.assertEqual(r.validate_local_base('http://localhost:8080/v1'), 'http://127.0.0.1:8080/v1')
    def test_model_assessment(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'sample.gguf'; p.write_bytes(b'GGUF'+(3).to_bytes(4,'little')+b'payload')
            self.assertEqual(r.assess_model(p)['version'], 3)
            self.assertTrue(r.assess_model(p, free_gb=0)['warnings'])
    def test_report_does_not_execute(self):
        s={'local_url':'http://127.0.0.1:8080/v1', 'server_exe':'', 'model_file':''}
        report=r.runtime_report(s)
        self.assertIn('не тестирует GPU',report)
        self.assertIn('не обращается к сети',report)
