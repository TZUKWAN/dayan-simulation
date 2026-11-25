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

    def test_function_suites_execute_in_real_pytest_child_and_keep_failure_and_skip_counts(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'tests').mkdir()
            fixture=root/'tests/test_pytest_fixture.py'
            source=('import pytest\n'
                    '@pytest.mark.parametrize("value", [1, 2])\n'
                    'def test_values(value):\n'
                    '    print("[PASS] labelled transport fixture")\n'
                    '    assert value > 0\n'
                    '@pytest.mark.skip(reason="labelled skip fixture")\n'
                    'def test_skipped():\n'
                    '    raise AssertionError("must not execute")\n')
            fixture.write_text(source,encoding='utf-8')
            suite=run_all.discover(root)[0]
            self.assertEqual(suite['framework'],'pytest')
            success=run_all.run_suite(suite,root,root/'success',30)
            self.assertEqual((success['verdict'],success['passed'],success['skipped']),('PASS',2,1))
            self.assertEqual(success['pytest_report']['testcases'],3)
            fixture.write_text(source.replace('assert value > 0','assert value == 1'),encoding='utf-8')
            failure=run_all.run_suite(suite,root,root/'failure',30)
            self.assertEqual((failure['verdict'],failure['passed'],failure['skipped']),('FAIL',1,1))
            self.assertEqual(failure['pytest_report']['failures'],1)
            self.assertNotEqual(failure['returncode'],0)
            self.assertTrue(Path(success['junit']).is_file())
            self.assertTrue(Path(failure['junit']).is_file())

    def test_framework_preserves_script_main_and_rejects_absent_or_empty_pytest_report(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);script=root/'legacy.py'
            script.write_text('def test_helper(value): pass\n'
                              'if __name__ == "__main__": test_helper(1)\n',encoding='utf-8')
            self.assertEqual(run_all.python_framework(script),'script')
            absent=run_all.pytest_counts(root/'missing.xml')
            self.assertEqual(run_all.judge_suite('missing',0,'[PASS] invented','',0,
                             pytest_report=absent)['verdict'],'FAIL')
            empty=root/'empty.xml';empty.write_text('<testsuites><testsuite tests="0"/></testsuites>')
            self.assertEqual(run_all.judge_suite('empty',0,'[PASS] invented','',0,
                             pytest_report=run_all.pytest_counts(empty))['verdict'],'FAIL')
            broken=root/'broken.xml';broken.write_text('<invalid')
            self.assertIn('损坏',run_all.pytest_counts(broken)['error'])


if __name__=='__main__':unittest.main(verbosity=2)
