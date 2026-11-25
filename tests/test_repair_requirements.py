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
    def test_symbolic_equations_indices_and_event_time_are_not_truncated_into_parameters(self):
        text=('构建4096名居民与64家企业的模型，居民编号i=0到4095，企业编号j=0到63。'
              'q_i=0.01*(1+(i模3))，dcapital_j/dt=0.2*capital_j-q_i。'
              '在t=0.35秒，企业各注资2元。运行10步，步长0.2秒。')
        request=extract_request(text)
        self.assertEqual(request['parameters'],{})
        self.assertEqual(request['interventions'],[])
        self.assertEqual(request['options'],{'ticks':10,'dt':.2})
        self.assertEqual(request['original_text'],text)
        literals=extract_request('新建模型，alpha=0.01，beta=2e-3，x=40米，weights=[1,2,3]。')
        self.assertEqual(literals['parameters'],{'alpha':.01,'beta':.002,'x':40,'weights':[1,2,3]})
        formulas=extract_request('新建模型，alpha=0.01*x，beta=2+3，i=0至9，state.x=2，密度=0.2*x。')
        self.assertEqual(formulas['parameters'],{})
        timed=extract_request('新建模型，beta=0.4。在t=0.35秒把beta改为0.2。')
        self.assertEqual(timed['parameters'],{'beta':.4})
        self.assertEqual([(iv['at_t'],iv['params']) for iv in timed['interventions']],[(.35,{'beta':.2})])

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

    def test_clock_origin_and_each_scheduled_update_keep_their_meaning(self):
        original = ("新建存量模型，初始存量 backlog=20、done=0。初始效率 efficiency=1。"
                    "从 t=0 推进12步，dt=0.25，随机种子为3、5。"
                    "t=1.0 时把 efficiency 改为0.5；t=2 当时 efficiency=0.75。")
        parsed = extract_request(original)
        self.assertEqual(parsed["original_text"], original)
        self.assertEqual(parsed["initial_state"], {"backlog": 20, "done": 0})
        self.assertEqual(parsed["parameters"], {"efficiency": 1})
        self.assertEqual(parsed["options"], {"ticks": 12, "dt": .25, "seeds": [3, 5]})
        self.assertEqual([(i["at_t"], i["params"]) for i in parsed["interventions"]],
                         [(1.0, {"efficiency": .5}), (2.0, {"efficiency": .75})])

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
