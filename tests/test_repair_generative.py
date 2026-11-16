"""External-dependent models must fail honestly and never be probed implicitly."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.agent.tools import tool_run
from dayan.fidelity import _probe_worker


class GenerativeTests(unittest.TestCase):
    def test_non_llm_prototype_cannot_substitute_for_real_llm_agents(self):
        from dayan.agent.intent import plan_rule_based
        wrong = plan_rule_based("用BEH134做真实LLM主体")
        self.assertFalse(wrong["plan"])
        self.assertTrue(wrong["errors"])
        correct = plan_rule_based("运行一个生成式主体，运行2步")
        self.assertEqual(correct["plan"][0]["args"]["model_id"], "BEH129")
    def test_no_credentials_never_returns_scripted_success(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"DAYAN_DATA_DIR": td, "DAYAN_API_KEY": ""}):
            for mid in ("BEH129", "BEH130", "BEH131", "BEH132", "BEH133"):
                result = tool_run(mid, ticks=2)
                self.assertFalse(result["ok"], mid)
                self.assertIn("真实LLM", result["error"])
            self.assertFalse((Path(td)/"research_runs").exists())

    def test_probe_does_not_consume_cloud_calls(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"DAYAN_DATA_DIR": td}):
            result = _probe_worker("BEH129")
            self.assertTrue(result["skipped"])
            self.assertFalse(result["ok"])
            self.assertFalse((Path(td)/"llm_calls").exists())

    def test_real_connection_failure_is_not_success(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"DAYAN_DATA_DIR": td,
            "DAYAN_API_KEY": "explicit-failed-connection-test", "DAYAN_BASE_URL": "http://127.0.0.1:1", "DAYAN_MODEL": "unreachable"}):
            result = tool_run("BEH129", parameters={"n": 1, "max_llm_calls": 1}, ticks=1)
            self.assertFalse(result["ok"])
            self.assertTrue(list((Path(td)/"llm_calls").glob("*.json")))


if __name__ == "__main__":
    unittest.main(verbosity=2)
