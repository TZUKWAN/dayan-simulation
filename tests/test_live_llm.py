"""Explicit opt-in real LLM execution; no canned responder counts as this test."""
import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(os.environ.get('DAYAN_TEST_LLM')=='1','真实LLM未显式启用，未执行')
class LiveLLM(unittest.TestCase):
    def test_actual_call_and_action_evidence(self):
        from dayan.llm_client import configured
        if not configured():self.skipTest('未提供可用的真实LLM配置；未调用')
        from dayan.runtime import execution_dependencies, run_model_full
        for model in ('BEH129','BEH130','BEH131','BEH132','BEH133'):
            with self.subTest(model=model):
                self.assertEqual(execution_dependencies(model)[0]['state'],'configured_not_probed')
                rr=run_model_full(model,parameters={'n':1,'max_llm_calls':1,
                    'scenario':'抽象互助资源实验，只观察主体从初始状态完成一个模型动作。'},
                    ticks=1,seed=7,capture_state=True,strict=True)
                calls=rr.manifest['llm_calls']
                self.assertEqual(len(calls),1)
                self.assertTrue(calls[0]['ok'])
                self.assertTrue(calls[0]['request_sha256'] and calls[0]['response_sha256'])
                self.assertGreaterEqual(rr.observations[-1]['actions_executed'],1)
                self.assertTrue(rr.state_frames)


if __name__=='__main__':unittest.main(verbosity=2)
