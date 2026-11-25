"""Verify a real binding and scheduled update survive the ensemble entry."""

import pytest

from dayan.agent.model_tools import build_model
from dayan.agent.tools import tool_ensemble
from dayan.datasets import ingest
from dayan.run_store import get_store


def test_ensemble_applies_the_same_manifest_binding_and_intervention(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    dataset = ingest(b"count\n12\n", name="程序验算输入", format="csv", source="已知数值测试夹具")
    definition = {
        "name": "有明确初值和时点的累积",
        "description": "布置计数率并在指定时刻调整",
        "kind": "stocks", "time_unit": "模型小时",
        "parameters": {
            "start": {"default": 0., "minimum": 0., "maximum": 20.},
            "rate": {"default": 2., "minimum": 0., "maximum": 10., "mutable": True},
        },
        "initial_state": {"count": "start"}, "rates": {"count": "rate"},
        "observables": {"result": "count"},
    }
    built = build_model(definition=definition, ticks=0)
    assert built["ok"], built
    evidence = [{"dataset_id": dataset["dataset_id"], "field": "count", "parameter": "start"}]
    change = {"at_t": 1.0, "params": {"rate": 6.0}}
    response = tool_ensemble(built["payload"]["model_id"], seeds=[3, 5], ticks=4, dt=.5,
                             data_bindings=evidence, interventions=[change])
    assert response["ok"], response
    records = [get_store().load(run["run_id"]) for run in response["payload"]["runs"]]
    assert [record["manifest"]["rng"]["seed"] for record in records] == [3, 5]
    for record in records:
        manifest = record["manifest"]
        assert manifest["data_bindings"][0]["sha256"] == dataset["sha256"]
        assert manifest["actual"]["effective_parameters"]["start"] == 12
        assert manifest["interventions"][0]["actual_t"] == 1
        assert manifest["interventions"][0]["params"] == {"rate": 6.0}
        assert [row["result"] for row in record["observations"]] == pytest.approx([12, 13, 14, 17, 20])
