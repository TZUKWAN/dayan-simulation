"""Explicit unit fixtures test coupling; they are not claimed to be Wuhan observations."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.datasets import ingest
from dayan.runtime import run_model_full


class EvacuationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DAYAN_DATA_DIR": self.tmp.name})
        self.env.start()
        road = {"elements": [{"type": "way", "tags": {"highway": "residential"},
                "geometry": [{"lon": 114.3+i*.001, "lat": 30.6} for i in range(6)]}]}
        ds = ingest(json.dumps(road).encode(), name="unit artificial road", format="osm", source="unit fixture", role="roads")
        population = ingest(b"lon,lat,population,elderly_fraction\n114.3,30.6,100,1\n", name="unit artificial population", format="csv", source="unit fixture", role="population")
        self.params = {"roads_dataset_id": ds["dataset_id"], "population_dataset_id": population["dataset_id"], "n": 100, "preparation_delay": 0., "bus_capacity": 10, "bus_count": 1}

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_bus_capacity_is_applied_and_changes_evacuation(self):
        base = run_model_full("CPL001", self.params, ticks=100, dt=.1, seed=7, capture_state=True)
        arm = run_model_full("CPL001", self.params, ticks=100, dt=.1, seed=7,
                             interventions=[{"at_t": 2, "params": {"bus_capacity": "*1.3"}}], capture_state=True)
        self.assertEqual([o for o in base.observations if o["sim_t"]<=2], [o for o in arm.observations if o["sim_t"]<=2])
        self.assertGreater(arm.observations[-1]["evacuated"], base.observations[-1]["evacuated"])
        self.assertEqual(arm.manifest["interventions"][0]["params"], {"bus_capacity": 13})
        self.assertEqual(len(arm.manifest["data_bindings"]), 2)
        self.assertEqual(arm.state_frames[-1]["aggregates"]["evacuated"], arm.observations[-1]["evacuated"])
        self.assertEqual(len(arm.state_frames[-1]["entities"]), 101)

    def test_information_changes_behavior_and_flood_changes_exposure(self):
        params = {**self.params, "preparation_delay": 2., "initial_rumor_fraction": 1., "information_rate": 0.}
        high_rumor = run_model_full("CPL001", params, ticks=60, dt=.1, seed=7)
        informed = run_model_full("CPL001", {**params, "information_rate": 1.}, ticks=60, dt=.1, seed=7)
        self.assertLess(informed.observations[-1]["rumor_mean"], high_rumor.observations[-1]["rumor_mean"])
        self.assertGreater(informed.observations[-1]["evacuated"], high_rumor.observations[-1]["evacuated"])
        dry = run_model_full("CPL001", {**self.params, "flood_severity": 0.}, ticks=60, dt=.1, seed=7)
        self.assertEqual(dry.observations[-1]["exposure"], 0.)
        self.assertGreater(high_rumor.observations[-1]["exposure"], 0.)

    def test_elderly_speed_actually_changes_walking(self):
        # Use geographically distributed hypothetical origins for this walking check.
        params = {**self.params, "population_dataset_id": "", "elderly_fraction": 1., "bus_capacity": 0}
        slow = run_model_full("CPL001", {**params, "elderly_speed_factor": .2}, ticks=10, dt=.1, seed=7, capture_state=True)
        fast = run_model_full("CPL001", {**params, "elderly_speed_factor": 1.}, ticks=10, dt=.1, seed=7, capture_state=True)
        self.assertNotEqual(slow.state_frames[-1]["entities"], fast.state_frames[-1]["entities"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
