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
        from dayan.runtime import run_model_full
        rr=run_model_full('BEH129',parameters={'n':1,'max_llm_calls':1},ticks=1,seed=7,capture_state=True)
        self.assertTrue(rr.manifest['llm_calls'])
        self.assertTrue(any(c.get('ok') for c in rr.manifest['llm_calls']))
        self.assertGreaterEqual(rr.observations[-1]['actions_executed'],1)
        self.assertTrue(rr.state_frames)


if __name__=='__main__':unittest.main(verbosity=2)
