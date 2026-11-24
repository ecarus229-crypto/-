import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from assistant_app import workflows, core


class CustomWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = patch.object(core, 'APP_DIR', Path(self.tmp.name)/'data')
        self.patch.start()
        self.addCleanup(self.patch.stop)
        self.root = Path(self.tmp.name)/'project'
        self.root.mkdir()
        (self.root/'file.py').write_text('# TODO: test\nx=1\n', encoding='utf-8')
        self.plan = json.dumps({'title': 'Проверка', 'steps': ['audit', 'snapshot']})

    def test_user_confirmation_needed_to_create(self):
        with self.assertRaises(PermissionError):
            workflows.create_from_plan(self.root, self.plan)
        self.assertEqual(workflows.list_all(), [])

    def test_plan_preview_and_steps_only_after_approval(self):
        self.assertIn('Этапы (2)', workflows.preview_plan(self.root, self.plan))
        wid = workflows.create_from_plan(self.root, self.plan, approved=True)
        self.assertEqual([step[2] for step in workflows.details(wid)[1]], ['audit','snapshot'])
        with self.assertRaises(PermissionError):
            workflows.execute_step(wid)
        self.assertIn('TODO', workflows.execute_step(wid, approved=True))
        self.assertEqual(workflows.next_step(wid)[2], 'snapshot')

    def test_does_not_run_when_created(self):
        with patch('assistant_app.workflows.project_audit.scan') as scan:
            workflows.create_from_plan(self.root, self.plan, approved=True)
            scan.assert_not_called()

    def test_strict_unknown_keys_and_kinds(self):
        bad = [
            {'title':'ok', 'steps':['shell']},
            {'title':'ok', 'steps':['audit'], 'command':'powershell'},
            {'title':'ok', 'steps':[]},
            {'title':'ok', 'steps':['audit']*9},
            {'title':'ok', 'steps':[{'kind':'audit'}]},
            {'title':'\n', 'steps':['audit']},
        ]
        for case in bad:
            with self.subTest(case=case), self.assertRaises(ValueError):
                workflows.parse_plan(json.dumps(case))

    def test_duplicate_keys_and_non_json_rejected(self):
        for text in ('{"title":"one","title":"two","steps":["audit"]}',
                     '```json\n'+self.plan+'\n```',
                     '{"title":"a","steps":["audit"]} trailing'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                workflows.parse_plan(text)

    def test_rejects_invalid_root_and_non_string(self):
        with self.assertRaises(Exception):
            workflows.create_from_plan(self.root/'missing', self.plan, approved=True)
        with self.assertRaises(ValueError):
            workflows.parse_plan(None)

    def test_no_ai_command_encoded_in_plan(self):
        with self.assertRaises(ValueError):
            workflows.create_from_plan(self.root, '{"title":"x","steps":["run_program"]}',approved=True)
        self.assertEqual(workflows.list_all(),[])
