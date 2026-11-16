import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dayan.server import app


class ResumeTests(unittest.TestCase):
    def test_http_exact_continuation_and_same_source_frames(self):
        with tempfile.TemporaryDirectory() as td, patch.dict(os.environ, {"DAYAN_DATA_DIR": td}):
            client = TestClient(app)
            common = {"model_id": "NET106", "seed": 7, "parameters": {"cells": 100, "density": .3, "p": .2}}
            first = client.post("/api/run", json={**common, "ticks": 20}).json()
            self.assertTrue(first["manifest"]["checkpoint"]["resumable"])
            continued = client.post(f"/api/runs/{first['run_id']}/resume", json={"ticks": 40})
            self.assertEqual(continued.status_code, 200, continued.text)
            continued = continued.json()
            whole = client.post("/api/run", json={**common, "ticks": 60}).json()
            self.assertEqual(first["observations"] + continued["observations"][1:], whole["observations"])
            frames = client.get(continued["state_url"]).json()["frames"]
            self.assertEqual(len(frames), 41)
            self.assertEqual(frames[0]["sim_t"], 2.)
            self.assertEqual(frames[-1]["sim_t"], 6.)
            self.assertEqual(continued["manifest"]["parent_run_id"], first["run_id"])
            sis = client.post("/api/run", json={"model_id": "NET052", "ticks": 3}).json()
            bad = client.post(f"/api/runs/{sis['run_id']}/resume", json={"ticks": 3})
            self.assertEqual(bad.status_code, 400)


if __name__ == "__main__":
    unittest.main(verbosity=2)
