"""Precise integrity regressions; generated fixtures are labelled and never research evidence."""
import importlib
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest


class CollectionLifecycle(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.previous = os.environ.get("DAYAN_DATA_DIR")
        os.environ["DAYAN_DATA_DIR"] = self.temp.name
        from dayan.collection import engine, registry, connectors
        self.engine, self.registry, self.connectors = engine, registry, connectors
        importlib.reload(registry); importlib.reload(engine)
        self.old = dict(connectors.CONNECTORS)
        self.old_source = dict(connectors.CONNECTOR_SOURCE)

    def tearDown(self):
        self.connectors.CONNECTORS.clear(); self.connectors.CONNECTORS.update(self.old)
        self.connectors.CONNECTOR_SOURCE.clear(); self.connectors.CONNECTOR_SOURCE.update(self.old_source)
        if self.previous is None:
            os.environ.pop("DAYAN_DATA_DIR", None)
        else:
            os.environ["DAYAN_DATA_DIR"] = self.previous
        importlib.reload(self.registry); importlib.reload(self.engine)
        self.temp.cleanup()

    def fixture(self, name, fn):
        self.connectors.CONNECTORS[name] = fn
        self.connectors.CONNECTOR_SOURCE[name] = "wb_indicators"

    def test_unknown_total_partial_and_resume(self):
        def pages(params, budget):
            start = (params.get("_cursor") or {}).get("page", 0)
            for i in range(start, min(start + budget, 3)):
                yield self.connectors.Page(f"fixture://{i}", str(i).encode(), [{"value": i}],
                    {"has_more": i < 2, "cursor": {"page": i + 1}})
        self.fixture("unit_fixture", pages)
        first = self.engine.run_collection("unit_fixture", {}, page_budget=1)
        self.assertEqual(first["status"], "partial")
        final = self.engine.run_collection("unit_fixture", {}, page_budget=2, collection_id=first["collection_id"])
        self.assertEqual(final["status"], "done")
        self.assertEqual([p["url"] for p in final["pages"]], [f"fixture://{i}" for i in range(3)])
        self.assertEqual(len(self.engine.records_preview(final["collection_id"], 10)), 3)
        with self.assertRaises(ValueError):
            self.engine.run_collection("unit_fixture", {"changed": 1}, collection_id=first["collection_id"])

    def test_failed_and_directory_not_green(self):
        def broken(params, budget):
            raise ValueError("intentional fixture failure")
            yield
        self.fixture("unit_broken", broken)
        t = self.engine.run_collection("unit_broken", {}, page_budget=1)
        self.assertEqual(t["status"], "failed")
        self.assertEqual(next(s for s in self.registry.matrix() if s["source_id"] == "wb_indicators")["state"], "down")
        from dayan.collection.evidence import artifact_role
        self.assertEqual(artifact_role("huggingface_datasets", [{"id": "x"}]), "catalog_only")
        self.assertEqual(artifact_role("web_page", [{"type": "doc", "text": "portal menu"}]), "catalog_only")
        self.assertEqual(artifact_role("crossref", [{"doi": "x"}]), "bibliographic_metadata")

    def test_cancellation_is_observed_and_concurrent_ledger_retains_both(self):
        entered, release = threading.Event(), threading.Event()
        def slow(params, budget):
            entered.set(); release.wait(3)
            yield self.connectors.Page("fixture://slow", b"[]", [{"value": 9}], {"has_more": False})
        self.fixture("unit_slow", slow)
        outcomes = []
        worker = threading.Thread(target=lambda: outcomes.append(self.engine.run_collection(
            "unit_slow", {}, collection_id="UNIT-cancel", page_budget=1, allow_new_id=True)))
        worker.start(); self.assertTrue(entered.wait(2))
        self.assertTrue(self.engine.cancel("UNIT-cancel")["cancel_requested"])
        release.set(); worker.join(4)
        self.assertFalse(worker.is_alive())
        self.assertEqual(outcomes[0]["status"], "cancelled")
        self.assertEqual(outcomes[0]["n_records"], 0)
        def simple(params, budget):
            yield self.connectors.Page("fixture://one", b"[]", [{"value": 1}], {"has_more": False})
        self.fixture("unit_simple", simple)
        workers = [threading.Thread(target=lambda i=i: self.engine.run_collection(
            "unit_simple", {}, collection_id=f"UNIT-concurrent-{i}", allow_new_id=True)) for i in range(2)]
        for w in workers: w.start()
        for w in workers: w.join(4)
        self.assertTrue(all(self.engine.get_task(f"UNIT-concurrent-{i}")["status"] == "done" for i in range(2)))


class NativeRequirementIntegrity(unittest.TestCase):
    def test_standalone_planner_cannot_rewrite_research_scope(self):
        from dayan.agent.intent import _constrain
        original = "德国2010至2015年失业率线性趋势，slope=[-1,0]，末尾2年留出，阈值1.0"
        request = {"original_text": original, "reuse": False, "parameters": {},
                   "options": {}, "interventions": [], "model_ids": []}
        plan = {"plan": [{"tool": "research_create", "args": {
            "question": "被改写的问题", "model_family": "linear", "param_grid": {"slope": [-1,0]},
            "holdout_years": 2, "tolerance": 1}}]}
        self.assertEqual(_constrain(plan, request, None)["plan"][0]["args"]["question"], original)
        with self.assertRaises(ValueError):
            _constrain({"plan": [{"tool": "collect_source", "args": {"connector": "worldbank",
                "params": {"country": "CHN", "indicator": "SP.POP.TOTL", "date": "2018:2024"}}}]}, request, None)

    def test_indicator_components_are_not_countries(self):
        from dayan.research.request_contract import parse_data_request
        r=parse_data_request("世界银行德国DEU 2010-2015年失业率SL.UEM.TOTL.ZS ILO估计，线性趋势")
        self.assertFalse(r["errors"])
        self.assertEqual(r["country"], "DEU")

    def test_original_grid_threshold_and_split_are_preserved(self):
        from dayan.research.native_contract import protect
        original="德国2010至2015年失业率线性趋势，参数网格slope=[-1,-0.75,0]，末尾2年留出，事前阈值均为1.0，预算最多3次"
        args={"question":"改写", "model_family":"linear", "param_grid":{"slope":[-1,-.75,0]}, "holdout_years":2,"tolerance":1}
        result=protect("research_create",args,original)
        self.assertEqual(result["question"],original)
        self.assertEqual(result["budget"],3)
        for change in ({"param_grid":{"slope":[0]}},{"tolerance":2},{"holdout_years":1}):
            with self.assertRaises(ValueError):protect("research_create",{**args,**change},original)
        with self.assertRaises(ValueError):protect("run_preset",{"preset_id":"pop_employment_wb","values":{"indicator":"SP.POP.TOTL","country":"中国","year_from":2018,"year_to":2024}},original)
        with self.assertRaises(ValueError):protect("collect_source",{"connector":"worldbank","params":{"country":"CHN","indicator":"SP.POP.TOTL","date":"2018:2024"}},original)


class ArchiveResourceSafety(unittest.TestCase):
    def test_zip_csv_is_parsed_in_memory_with_audited_member(self):
        import io,zipfile
        from unittest.mock import patch
        from dayan.collection.connectors import _file_page
        content=io.BytesIO()
        with zipfile.ZipFile(content,"w") as z:z.writestr("unit_fixture.csv","year,value\n2020,3\n")
        with patch("dayan.collection.connectors._get",return_value=(content.getvalue(),"https://example.org/unit_fixture.csv.zip")):
            page=_file_page("https://example.org/unit_fixture.csv.zip","csv")
        self.assertEqual(page.records,[{"year":"2020","value":"3"}])
        self.assertEqual(page.raw,content.getvalue())
        self.assertEqual(page.meta["provenance"]["archive_member"],"unit_fixture.csv")

    def test_ambiguous_archive_is_not_silently_substituted(self):
        import io,zipfile
        from unittest.mock import patch
        from dayan.collection.connectors import _file_page
        content=io.BytesIO()
        with zipfile.ZipFile(content,"w") as z:
            z.writestr("country_a.csv","year,value\n2020,3\n")
            z.writestr("country_b.csv","year,value\n2020,4\n")
        with patch("dayan.collection.connectors._get",return_value=(content.getvalue(),"https://example.org/unit_fixture.zip")):
            with self.assertRaisesRegex(ValueError,"archive_member"):_file_page("https://example.org/unit_fixture.zip","csv")


class CalibrationIntegrity(unittest.TestCase):
    def test_interpretation_does_not_reverse_decline_direction(self):
        from dayan.research.studies import interpretation
        fixture = {"records": [{"date": 1, "value": 7}, {"date": 2, "value": 5}],
                   "holdout": [{"date": 2, "value": 5}],
                   "predictions": [{"date": 1, "predicted": 7}, {"date": 2, "predicted": 3}]}
        result = interpretation(fixture)
        self.assertEqual(result["direction"], "model_underpredicts_all_holdout")
        self.assertEqual(result["holdout_comparisons"][0]["observed_minus_predicted"], 2)
        self.assertIn("模型预测下降过快", result["interpretation_text"])
        fixture["predictions"][1]["predicted"] = 6
        result = interpretation(fixture)
        self.assertEqual(result["direction"], "model_overpredicts_all_holdout")
        self.assertIn("模型预测下降过慢", result["interpretation_text"])

    def calibrate(self, fn, **kw):
        from dayan.research.calibration import grid_search_calibrate
        return grid_search_calibrate(model_fn=fn, param_grid={"a": [0, 1]},
            observations=[{"date": 1, "value": 1}, {"date": 2, "value": 999}], **kw)

    def test_truncated_and_nonfinite_predictions_cannot_pass(self):
        for fn in (lambda p,y: [1], lambda p,y: [1, float("nan")]):
            r = self.calibrate(fn, tolerance=.01)
            self.assertEqual(r["status"], "failed")
            self.assertTrue(all(e.get("error") for e in r["evaluations"]))

    def test_holdout_failure_and_leakage(self):
        from dayan.research.calibration import grid_search_calibrate as calibrate
        r = calibrate(model_fn=lambda p,y: [1 for _ in y], param_grid={"a": [1]},
            observations=[{"date": 1, "value": 1}], holdout_observations=[{"date": 2, "value": 100}], tolerance=1)
        self.assertEqual(r["status"], "failed_holdout")
        self.assertFalse(r["tolerance_met"])
        with self.assertRaises(ValueError):
            self.calibrate(lambda p,y: y, holdout_observations=[{"date": 2, "value": 2}])

    def test_zero_ties_full_audit_and_no_false_identifiability(self):
        from dayan.research.calibration import grid_search_calibrate as calibrate
        r = calibrate(model_fn=lambda p,y: [1]*len(y), param_grid={"a": list(range(40))},
            observations=[{"date": 1, "value": 1}], tolerance=0,
            holdout_observations=[{"date": 2, "value": 1}])
        self.assertEqual(len(r["evaluations"]), 40)
        self.assertEqual(r["near_min_count"], 40)
        self.assertTrue(r["non_identifiable"])
        self.assertEqual(r["status"], "pass")
        self.assertEqual(r["identifiability_status"], "not_established_by_grid_search")

    def test_expression_boundary_and_transform_hash(self):
        from dayan.research.safe_expression import compile_model_expression
        fn = compile_model_expression("lambda params, years: [params['a'] * math.exp(.01*(y-2018)) for y in years]")
        self.assertEqual(fn({"a": 5}, [2018]), [5])
        for s in ("lambda params, years: ().__class__.__base__.__subclasses__()", "lambda params, years: [x for x in range(999999999)]"):
            with self.assertRaises(ValueError): compile_model_expression(s)
        from dayan.research.quality import clean_transform, check_role_leakage
        rows = [{"date": 1, "value": 2}]
        cleaned, log = clean_transform(rows, [{"op": "scale", "factor": 2}])
        self.assertEqual(rows[0]["value"], 2)
        _, other = clean_transform([{"date": 1, "value": 3}], [{"op": "scale", "factor": 2}])
        self.assertNotEqual(log["chain_hash"], other["chain_hash"])
        self.assertFalse(check_role_leakage(["same"], ["same"], rows, [{"date": 2, "value": 3}])["has_leakage"])


if __name__ == "__main__":
    unittest.main()
