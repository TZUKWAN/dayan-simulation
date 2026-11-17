"""Verify discovery and failure accounting with intentionally labelled fixtures."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
import run_all


class TestRunner(unittest.TestCase):
    def test_discovery_includes_previously_omitted_suites_and_node(self):
        suites=run_all.discover();names={s['name'] for s in suites}
        self.assertTrue({'test_agent_job_store','test_assistant_scene_routing','test_research_integrity',
            'test_scenario_alignment','test_scene_contract','test_workspace_reports','dayan_session_binding.test'} <= names)
        self.assertEqual(len(names),len(suites))

    def test_nonzero_empty_traceback_skip_and_node_accounting(self):
        judge=run_all.judge_suite
        self.assertEqual(judge('bad',1,'[PASS] fixture','',0)['verdict'],'FAIL')
        self.assertEqual(judge('empty',0,'','',0)['verdict'],'FAIL')
        self.assertEqual(judge('tb',0,'','Traceback (most recent call last)',0)['verdict'],'FAIL')
        skipped=judge('skip',0,'','Ran 2 tests in 0.1s\n\nOK (skipped=2)\n',0)
        self.assertEqual((skipped['verdict'],skipped['passed'],skipped['skipped']),('SKIP',0,2))
        node=judge('node',0,'# tests 3\n# pass 2\n# skipped 1\n# fail 0\n','',0)
        self.assertEqual((node['verdict'],node['passed'],node['skipped']),('PASS',2,1))

    def test_real_child_exit_code_and_timeout_are_not_passed(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'tests').mkdir();output=root/'logs'
            fixture=root/'tests/test_failure_fixture.py'
            fixture.write_text("print('[PASS] fixture marker'); raise SystemExit(7)",encoding='utf-8')
            suite={'name':'test_failure_fixture','path':'tests/test_failure_fixture.py','runtime':'python','category':'unit'}
            result=run_all.run_suite(suite,root,output,5)
            self.assertEqual(result['returncode'],7);self.assertEqual(result['verdict'],'FAIL')
            fixture.write_text('import time; time.sleep(20)',encoding='utf-8')
            result=run_all.run_suite(suite,root,output,.2)
            self.assertEqual(result['verdict'],'FAIL');self.assertIn('执行超时',result['reasons'])


if __name__=='__main__':unittest.main(verbosity=2)
