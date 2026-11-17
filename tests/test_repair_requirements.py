"""Original Chinese request -> actual runtime and durable evidence."""
from __future__ import annotations
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.agent.agent import DayanAgent
from dayan.research.requirements import extract_request
from dayan.agent import intent
from dayan.research.compiler import compile_research


class RequirementsTests(unittest.TestCase):
    def test_facility_coordinates_do_not_overwrite_agent_state_parameters(self):
        text='创建37名行人的模型，右侧出口（x=40米，y=15米），目标(x=20,y=10)，起点（x=2，y=3）。运行20步，步长0.2。'
        request=extract_request(text)
        self.assertEqual(request['explicit_parameters'],{'exit_x':40,'exit_y':15,
                         'target_x':20,'target_y':10,'start_x':2,'start_y':3,'n':37})
        self.assertEqual(request['options'],{'ticks':20,'dt':.2})
        self.assertEqual(request['original_text'],text)
        self.assertEqual(extract_request('新建方程模型，x=40，y=15')['explicit_parameters'],{'x':40,'y':15})

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DAYAN_DATA_DIR": self.temp.name})
        self.env.start()
        self.old_planner = intent._LLM_PLANNER
        intent.set_llm_planner(None)

    def tearDown(self):
        intent.set_llm_planner(self.old_planner)
        self.env.stop()
        self.temp.cleanup()

    def test_exact_experiment(self):
        r = DayanAgent().fulfill("NET052 beta=0.4，运行40步，步长0.1，种子7和8，第2秒beta减半")
        self.assertTrue(r["ok"], r)
        p = r["executed"][0]["payload"]
        spec = p["experiment_spec"]
        self.assertEqual((spec["ticks"], spec["dt"], spec["seeds"], spec["baseline_params"]), (40, .1, [7, 8], {"beta": .4}))
        self.assertEqual(len(p["runs"]), 4)
        for run in p["runs"][2:]:
            self.assertIn(run["manifest"]["rng"]["seed"], [7, 8])
            iv = run["manifest"]["interventions"][0]
            self.assertEqual((iv["actual_t"], iv["params"], iv["applied"]), (2, {"beta": .2}, True))
        base, arm = p["observations_by_arm"].values()
        self.assertEqual([o["I"] for o in base[0] if o["sim_t"] <= 2],
                         [o["I"] for o in arm[0] if o["sim_t"] <= 2])
        self.assertLess(arm[0][-1]["I"], base[0][-1]["I"])

    def test_followup_preserves_configuration(self):
        prior = {"model_id": "NET106", "params": {"cells": 100, "p": .2, "vmax": 4, "density": .3}, "ticks": 35, "seed": 7, "dt": .2}
        r = DayanAgent().fulfill("沿用刚才配置，只把density改成0.5对比流量", last_run=prior)
        self.assertTrue(r["ok"], r)
        p = r["executed"][0]["payload"]
        self.assertEqual(p["primary_metric"], "flux")
        self.assertEqual([run["value"] for run in p["runs"]], [.3, .5])
        for run in p["runs"]:
            m = run["manifest"]
            self.assertEqual(m["rng"]["seed"], 7)
            self.assertEqual(m["actual"]["effective_parameters"]["cells"], 100)
            self.assertEqual(m["actual"]["effective_parameters"]["p"], .2)
            self.assertEqual(len(run["observations"]), 36)

    def test_no_unrelated_sis_substitute(self):
        text = "武汉暴雨疏散，老人行动困难，谣言传播，公交接驳提高30%，使用真实道路人口"
        c = compile_research(text)
        self.assertIsNone(c.experiment_spec)
        r = DayanAgent().fulfill(text)
        self.assertFalse(r["ok"])
        self.assertEqual(r["executed"], [])
        self.assertTrue(r["errors"])

    def test_no_unspecified_intervention_or_missing_context(self):
        self.assertIsNone(compile_research("NET052 beta减半做对照实验").experiment_spec)
        self.assertFalse(DayanAgent().fulfill("沿用刚才的配置运行20步")["ok"])
        self.assertEqual(extract_request("运行NET106，种子7，运行60步")["model_ids"], ["NET106"])

    def test_negated_real_data_and_new_model_wording(self):
        for text in ("创建一个新主体模型，不用现实数据", "建立新方程模型，无需真实数据", "创建模型，不使用实际数据"):
            r = extract_request(text)
            self.assertFalse(r["requires_real_data"], text)
            self.assertEqual(r["kind"], "build_model")
        self.assertTrue(extract_request("不用现实数据，但需要采集真实道路")["requires_real_data"])

    def test_invalid_chinese_numbers_are_not_dropped_or_truncated(self):
        for text in ("运行NET106，运行-3步", "运行NET106，运行1.5步", "运行NET106，种子-1", "运行NET106，种子1.5"):
            result = DayanAgent().fulfill(text)
            self.assertFalse(result["ok"], text)
            self.assertFalse(any(e.get("ok") for e in result["executed"]), text)


if __name__ == "__main__":
    unittest.main(verbosity=2)
