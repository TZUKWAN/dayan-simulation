"""Report facts are derived from an actual archived run, never client overrides."""
import json
import os
import sys
import tempfile
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
EVIDENCE = ROOT / ".claude/repair_all_20261112/report_validation"
os.environ["DAYAN_REPORTS_DIR"] = str(EVIDENCE)
from fastapi.testclient import TestClient
from docx import Document
from dayan.server import app
from dayan.report_gen import _stats


class ReportTests(unittest.TestCase):
    def test_actual_report(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"DAYAN_DATA_DIR": td}):
            client = TestClient(app)
            run = client.post("/api/run", json={"model_id": "NET106", "ticks": 60, "seed": 61}).json()
            self.assertEqual(len(run["observations"]), 61)
            with warnings.catch_warnings(record=True) as caught:
                report = client.post("/api/report", json={"model_id": "NET106", "run_id": run["run_id"],
                    "observations": [{"sim_t": 0, "fake_metric": 123456}],
                    "manifest": {"actual": {"n_steps": 99999}},
                    "analysis": {"metric": "fake_metric", "baseline": {"window_mean": {"mean": 99999}}},
                    "intent": "实际交通流运行结果"})
            self.assertEqual(report.status_code, 200, report.text)
            result = report.json()
            text = "\n".join(p.text for p in Document(result["path"]).paragraphs)
            self.assertIn("实际推进 60 步，保存 61 条观测", text)
            self.assertNotIn("fake_metric", text)
            self.assertNotIn("99999", text)
            stats = _stats(run["observations"])
            for field, stat in stats.items():
                self.assertIn(f"上升 {stat['increases']} 次、下降 {stat['decreases']} 次", text)
            self.assertFalse(any("Glyph" in str(w.message) and "missing" in str(w.message) for w in caught))
            EVIDENCE.mkdir(parents=True, exist_ok=True)
            (EVIDENCE / "verification.json").write_text(json.dumps({"run_id": run["run_id"], "report": result,
                "stats": stats, "n_steps": 60, "n_observations": 61, "missing_glyph_warnings": 0}, ensure_ascii=False, indent=2), encoding="utf-8")
            self.assertEqual(client.get(result["facts_url"]).status_code, 200)
            bad = client.post("/api/report", json={"model_id": "NET052", "run_id": run["run_id"]})
            self.assertEqual(bad.status_code, 400)

    def test_shape_and_window(self):
        s = _stats([{"x": v} for v in [3, 2, 4, 1, 1]])["x"]
        self.assertEqual((s["increases"], s["decreases"], s["unchanged"]), (1, 2, 1))
        from dayan.research.experiment import analyze_observations
        self.assertIn("error", analyze_observations([{"sim_t": 0, "x": 2}], "x", window=[5, 6]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
