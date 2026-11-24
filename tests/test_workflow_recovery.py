import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import core, workflows

class WorkflowRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patcher = patch.object(core, 'APP_DIR', Path(self.temp.name)/'data')
        self.patcher.start()
        self.root = Path(self.temp.name)/'project'
        self.root.mkdir()
        (self.root/'a.py').write_text('x=1')
        self.wid = workflows.create(self.root, 'audit_snapshot')

    def tearDown(self):
        self.patcher.stop()
        self.temp.cleanup()

    def set_running(self, timestamp):
        with core.db() as conn:
            conn.execute("UPDATE workflow_steps SET status='running',updated=? WHERE workflow_id=? AND position=1", (timestamp,self.wid))

    def test_old_interrupted_requires_approval_and_never_executes(self):
        self.set_running(10)
        self.assertEqual(len(workflows.list_interrupted(now=90000)), 1)
        with self.assertRaises(PermissionError):
            workflows.mark_interrupted(self.wid, now=90000)
        with patch('assistant_app.workflows.project_audit.scan', side_effect=AssertionError('executed')):
            self.assertEqual(workflows.mark_interrupted(self.wid, approved=True, now=90000), 1)
        self.assertEqual(workflows.next_step(self.wid)[3], 'failed')
        self.assertEqual(workflows.list_interrupted(now=90000), [])

    def test_fresh_running_not_reclassified(self):
        self.set_running(89999)
        self.assertFalse(workflows.list_interrupted(now=90000))
        with self.assertRaises(ValueError):
            workflows.mark_interrupted(self.wid, approved=True, now=90000)

    def test_completed_workflow_not_reclassified(self):
        self.set_running(10)
        with core.db() as conn:
            conn.execute("UPDATE workflows SET status='done' WHERE id=?", (self.wid,))
        self.assertFalse(workflows.list_interrupted(now=90000))

    def test_reclassification_is_idempotent(self):
        self.set_running(10)
        workflows.mark_interrupted(self.wid, approved=True, now=90000)
        with self.assertRaises(ValueError):
            workflows.mark_interrupted(self.wid, approved=True, now=90000)

if __name__ == '__main__':
    unittest.main()
