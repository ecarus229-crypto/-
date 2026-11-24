import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core, workflows

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(core, 'APP_DIR', Path(self.temp.name) / 'data')
        self.patch.start()
        self.root = Path(self.temp.name) / 'code'
        self.root.mkdir()
        (self.root/'main.py').write_text('x=1\n# TODO: check\n', encoding='utf-8')

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_full_workflow_requires_approval_at_every_step(self):
        task = workflows.create(self.root,'audit_snapshot')
        self.assertIn('Проверить исходники', workflows.preview(task))
        with self.assertRaises(PermissionError):
            workflows.execute_step(task)
        self.assertEqual(workflows.next_step(task)[2], 'audit')
        audit = workflows.execute_step(task,approved=True)
        self.assertIn('TODO', audit)
        self.assertEqual(workflows.next_step(task)[2], 'snapshot')
        self.assertFalse(workflows.list_all()[0][3] == 'done')
        with self.assertRaises(PermissionError):
            workflows.execute_step(task)
        result = workflows.execute_step(task,approved=True)
        self.assertIn('Снимок #', result)
        self.assertEqual(workflows.details(task)[0][3], 'done')
        self.assertIsNone(workflows.next_step(task))
        with self.assertRaises(ValueError):
            workflows.execute_step(task,approved=True)

    def test_invalid_template_and_missing_root(self):
        with self.assertRaises(ValueError):
            workflows.create(self.root,'shell')
        with self.assertRaises(Exception):
            workflows.create(self.root/'missing','audit_only')

    def test_cancelled_never_runs(self):
        task = workflows.create(self.root,'snapshot_only')
        with self.assertRaises(PermissionError):
            workflows.cancel(task)
        workflows.cancel(task,approved=True)
        with self.assertRaises(ValueError):
            workflows.execute_step(task, approved=True)
        self.assertEqual(workflows.details(task)[0][3],'cancelled')

    def test_failure_is_persisted_and_requires_new_approval(self):
        task = workflows.create(self.root,'audit_only')
        with patch('assistant_app.workflows.project_audit.scan', side_effect=OSError('fake IO failure')):
            with self.assertRaises(OSError):
                workflows.execute_step(task,approved=True)
        self.assertEqual(workflows.next_step(task)[3], 'failed')
        with self.assertRaises(PermissionError):
            workflows.execute_step(task)
        self.assertIn('Проверить исходники',workflows.preview(task))
        workflows.execute_step(task,approved=True)
        self.assertEqual(workflows.details(task)[0][3],'done')

    def test_disallowed_kind_and_running_step(self):
        task = workflows.create(self.root,'audit_only')
        with core.db() as conn:
            conn.execute('UPDATE workflow_steps SET kind=? WHERE workflow_id=?',('exec_shell',task))
        with self.assertRaises(ValueError):
            workflows.execute_step(task,approved=True)
        with core.db() as conn:
            conn.execute('UPDATE workflow_steps SET kind=?,status=? WHERE workflow_id=?',('audit','running',task))
        with self.assertRaises(ValueError):
            workflows.execute_step(task,approved=True)
        with self.assertRaises(ValueError):
            workflows.cancel(task,approved=True)

    def test_no_arbitrary_project_modification(self):
        task = workflows.create(self.root, 'audit_snapshot')
        before = (self.root/'main.py').read_bytes()
        workflows.execute_step(task,approved=True)
        workflows.execute_step(task,approved=True)
        self.assertEqual((self.root/'main.py').read_bytes(), before)
        self.assertTrue((core.ensure_dir()/'memory.db').exists())

if __name__ == '__main__':
    unittest.main()
