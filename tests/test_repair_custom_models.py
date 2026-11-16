"""DSL computations, coupled agent state and rejection of executable code."""
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dayan.custom_models import Expression, register
from dayan.runtime import run_model_full


class CustomModelTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DAYAN_DATA_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_new_equation_matches_analytic_solution(self):
        result = register({"name": "Exponential analytical check", "description": "dx/dt=r*x", "kind": "stocks", "time_unit": "model unit",
                           "parameters": {"r": {"default": .2, "minimum": 0, "maximum": 1, "mutable": True}, "x0": {"default": 2}},
                           "initial_state": {"x": "x0"}, "rates": {"x": "r*x"}, "observables": {"x": "x"}})
        run = run_model_full(result["model_id"], ticks=100, dt=.1, seed=7, capture_state=True, strict=True)
        self.assertAlmostEqual(run.observations[-1]["x"], 2*math.exp(2), places=6)
        self.assertEqual(run.manifest["model_definition"], result["definition"])
        self.assertEqual(run.state_frames[10]["aggregates"]["x"], run.observations[10]["x"])
        policy = run_model_full(result["model_id"], ticks=100, dt=.1, seed=7,
                                interventions=[{"at_t": 5, "params": {"r": "*0.5"}}])
        self.assertAlmostEqual(policy.observations[-1]["x"], 2*math.exp(1.5), places=6)

    def test_simultaneous_agents_and_actual_frames(self):
        result = register({"name": "Opinion relaxation with moving agents", "description": "Each opinion approaches previous population mean", "kind": "agents", "time_unit": "model unit",
                           "parameters": {"n": {"default": 37, "type": "int", "minimum": 1, "maximum": 2000}, "alpha": {"default": .8, "minimum": 0, "maximum": 1, "mutable": True}},
                           "agents": {"count": "n", "initial": {"x": "uniform(0,10)", "y": "uniform(0,10)", "opinion": "uniform(0,1)"},
                                      "update": {"opinion": "opinion+alpha*(mean_opinion-opinion)*dt", "x": "(x+dt)%10"}, "color_by": "opinion"},
                           "space": {"width": 10, "height": 10, "unit": "model distance"}, "observables": {"mean": "mean_opinion", "spread": "max_opinion-min_opinion", "n": "n_agents"}})
        run = run_model_full(result["model_id"], ticks=30, dt=.1, seed=7, capture_state=True)
        self.assertEqual(len(run.state_frames), 31)
        self.assertEqual(len(run.state_frames[-1]["entities"]), 37)
        self.assertEqual(run.state_frames[-1]["entities"][0]["id"], 0)
        self.assertAlmostEqual(run.observations[0]["mean"], run.observations[-1]["mean"])
        self.assertLess(run.observations[-1]["spread"], run.observations[0]["spread"])
        self.assertAlmostEqual(run.state_frames[1]["entities"][0]["x"], (run.state_frames[0]["entities"][0]["x"]+.1)%10)

    def test_reject_code_and_unknown_variables(self):
        for expr in ("__import__('os').system('whoami')", "x.__class__", "[x for x in range(5)]", "open('secret')", "unknown+1"):
            with self.assertRaises(ValueError, msg=expr):
                Expression(expr, {"x"})
        with self.assertRaises(ValueError):
            Expression("2**1000000", {}).value({})


if __name__ == "__main__":
    unittest.main(verbosity=2)
