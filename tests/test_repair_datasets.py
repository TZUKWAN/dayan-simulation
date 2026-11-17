"""Dataset import, validation and actual model parameter consumption."""
import io
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api_client import local_client as TestClient
from dayan.server import app
from dayan import datasets
from dayan.runtime import run_model_full


class DatasetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {"DAYAN_DATA_DIR": self.tmp.name})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def test_http_import_run_and_bundle(self):
        # A unit fixture tests mapping mechanics; live World Bank evidence is separate.
        client = TestClient(app)
        source = "density\n0.2\n0.4\n"
        ds = client.post("/api/datasets/import", json={"name": "unit fixture", "content": source, "format": "csv"}).json()
        did = ds["dataset_id"]
        binding = {"dataset_id": did, "field": "density", "aggregate": "mean", "parameter": "density"}
        response = client.post("/api/run", json={"model_id": "NET106", "ticks": 20, "seed": 7,
                                                 "parameters": {"cells": 100}, "data_bindings": [binding]})
        self.assertEqual(response.status_code, 200, response.text)
        run = response.json()
        expected = run_model_full("NET106", {"cells": 100, "density": .3}, ticks=20, seed=7)
        self.assertEqual(run["observations"], expected.observations)
        self.assertEqual(run["manifest"]["data_bindings"][0]["sha256"], ds["sha256"])
        bundle = client.get(f"/api/runs/{run['run_id']}/bundle.zip")
        archive = zipfile.ZipFile(io.BytesIO(bundle.content))
        self.assertEqual(archive.read(f"datasets/{did}/original").decode(), source)
        self.assertEqual(client.get(ds["data_url"]).content.decode(), source)
        conflicting = client.post("/api/run", json={"model_id": "NET106", "parameters": {"density": .9}, "data_bindings": [binding]})
        self.assertEqual(conflicting.status_code, 400)

    def test_missing_values_not_silently_dropped(self):
        ds = datasets.ingest(b"value\n2\nunknown\n", name="unit", format="csv", source="unit fixture")
        with self.assertRaisesRegex(ValueError, "缺失或非数值"):
            datasets.bind_parameters([{"dataset_id": ds["dataset_id"], "field": "value", "parameter": "p"}])

    def test_original_integrity_and_input_boundaries(self):
        ds = datasets.ingest(b"value\n2\n", name="unit", format="csv", source="unit fixture")
        (datasets.dataset_dir() / ds["dataset_id"] / "original").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "哈希"):
            datasets.load(ds["dataset_id"])
        for url in ("file:///etc/passwd", "https://127.0.0.1/a", "https://localhost/a", "https://user:pw@example.org/a"):
            with self.assertRaises(ValueError):
                datasets.fetch(url)


if __name__ == "__main__":
    unittest.main(verbosity=2)
