"""Targeted regression tests for chronological selection and scene source roles."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.research.calibration import grid_search_calibrate
from dayan.collection.connectors import worldbank_data360
from dayan.collection.spatial import _normalize_blocks


class VNextEvidence(unittest.TestCase):
    def test_validation_selects_from_training_shortlist_and_tests_only_winner(self):
        calls = []

        def predict(params, dates):
            calls.append((params["slope"], dates))
            return [params["slope"] * t for t in dates]

        def rows(dates, values):
            return [{"date":t,"value":v} for t,v in zip(dates,values)]

        result = grid_search_calibrate(model_fn=predict, param_grid={"slope":[0,1,-1,2]},
            observations=rows([0,1,2],[0,0,0]), validation_observations=rows([3,4],[3,4]),
            holdout_observations=rows([5,6],[0,0]), selection_top=3, tolerance=1)
        self.assertEqual(result["best_params"], {"slope":1})
        self.assertEqual(result["status"], "failed_holdout")
        self.assertEqual([s for s,t in calls if t == [5,6]],[1])
        self.assertEqual(result["selection"]["validation"]["rmse"],0)
        self.assertEqual(result["holdout"]["baseline_last_training_rmse"],0)
        self.assertEqual(result["uncertainty"]["holdout_coverage"],0)

    def test_validation_dates_must_precede_and_exclude_test(self):
        obs = [{"date":1,"value":1}]
        val = [{"date":2,"value":2}]
        with self.assertRaisesRegex(ValueError, "独立"):
            grid_search_calibrate(model_fn=lambda p,t:t, param_grid={"x":[1]},
                observations=obs, validation_observations=val, holdout_observations=val)

    def test_provider_metadata_cannot_substitute_a_different_scope(self):
        # Protocol validation fixture, not an empirical data source.
        row={"DATABASE_ID":"WB_WDI","INDICATOR":"WB_WDI_SL_UEM_TOTL_ZS","REF_AREA":"CAN",
             "FREQ":"A","TIME_FORMAT":"P1Y","SEX":"_T","AGE":"_T","URBANISATION":"_T",
             "COMP_BREAKDOWN_1":"_Z","COMP_BREAKDOWN_2":"_Z","COMP_BREAKDOWN_3":"_Z",
             "UNIT_MEASURE":"PT","UNIT_MULT":0,"TIME_PERIOD":"2000","OBS_VALUE":"7"}
        with patch("dayan.collection.connectors._get", return_value=(json.dumps({"count":1,"value":[row]}).encode(),"wire-fixture")):
            with self.assertRaisesRegex(ValueError,"单位"):
                list(worldbank_data360({"country":"CAN","indicator":"SL.UEM.TOTL.ZS","date":"2000:2001"},1))

    def test_census_counts_whole_blocks_by_internal_point_and_duplicate_guard(self):
        def f(id,lon,lat,pop):
            return {"attributes":{"GEOID":id,"INTPTLON":lon,"INTPTLAT":lat,"POP100":pop}}
        contained=f("000000000000001",-80,40,50)
        outside=f("000000000000002",-79.7,40,60)
        bbox=(-80.1,39.9,-79.9,40.1)
        self.assertEqual(_normalize_blocks([contained,outside],bbox),[{"geoid":"000000000000001","lon":-80.,"lat":40.,"population":50}])
        with self.assertRaisesRegex(ValueError,"普查区标识"):
            _normalize_blocks([contained,contained],bbox)


if __name__ == "__main__":
    unittest.main(verbosity=2)
