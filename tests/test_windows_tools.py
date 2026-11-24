import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import windows_tools


class WindowsToolsTests(unittest.TestCase):
    def test_unapproved_never_starts_process(self):
        with patch.object(windows_tools.subprocess, 'Popen') as popen:
            with self.assertRaises(PermissionError):
                windows_tools.launch('notepad')
            popen.assert_not_called()

    def test_unknown_app_rejected(self):
        with self.assertRaises(ValueError):
            windows_tools.executable_for('powershell', platform='win32')

    def test_non_windows_rejected(self):
        with self.assertRaises(OSError):
            windows_tools.executable_for('notepad', platform='linux')

    def test_exact_app_paths_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'Windows'
            sys32 = root / 'System32'
            sys32.mkdir(parents=True)
            (sys32 / 'notepad.exe').write_bytes(b'mock executable')
            p = windows_tools.executable_for('notepad', windows_dir=root, platform='win32')
            self.assertEqual(p.name, 'notepad.exe')
            # Windows can return 8.3 (RUNNER~1) and expanded path aliases.
            self.assertTrue(p.parent.samefile(sys32))

    def test_invalid_windows_dir_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                windows_tools.executable_for('notepad', windows_dir=tmp, platform='win32')

    def test_missing_exe_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'Windows'
            (root/'System32').mkdir(parents=True)
            with self.assertRaises(FileNotFoundError):
                windows_tools.executable_for('notepad', windows_dir=root, platform='win32')

    def test_launch_uses_no_shell_and_no_args(self):
        with patch.object(windows_tools, 'executable_for', return_value=Path('C:/Windows/System32/calc.exe')):
            with patch.object(windows_tools.subprocess, 'Popen') as popen:
                self.assertEqual(windows_tools.launch('calculator', approved=True), 'Калькулятор')
                popen.assert_called_once_with([str(Path('C:/Windows/System32/calc.exe'))], shell=False, close_fds=True)


if __name__ == '__main__':
    unittest.main()
