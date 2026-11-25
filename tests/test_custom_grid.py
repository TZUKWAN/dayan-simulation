"""Reproducible bounded-DSL grid and multi-seed execution checks."""

import pytest

from dayan.agent.model_tools import build_model
from dayan.agent.scenario_tools import modeling_guide
from dayan.custom_models import validate_definition
from dayan.run_store import get_store
from dayan.runtime import resume_from_checkpoint, run_model_full


def definition():
    return {
        "name": "周期网格传播验算",
        "description": "仅从真实邻居的滞后状态传播",
        "kind": "agents",
        "time_unit": "MCS",
        "agents": {
            "grid": {
                "rows": 5, "columns": 5, "degree": 4,
                "reductions": {"peer": {"op": "pick_max", "field": "active", "by": "active", "lag": 1}},
            },
            "initial": {"active": "1 if id == 0 else 0"},
            "update": {"active": "max(active, peer)"},
            "type": "cell", "color_by": "active",
        },
        "observables": {"active_count": "sum_active"},
    }


def test_lagged_grid_reaches_only_local_cells_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    response = build_model(definition=definition(), ticks=3, seed=7)
    assert response["ok"], response
    run = get_store().load(response["payload"]["run_id"])
    assert [o["active_count"] for o in run["observations"]] == [1, 5, 5, 13]
    assert {e["id"] for e in run["state_frames"][1]["entities"] if e["active"]} == {0, 1, 4, 5, 20}
    assert {e["id"] for e in run["state_frames"][0]["entities"] if e["x"] == .5 and e["y"] == .5} == {0}
    partial = run_model_full(run["model_id"], ticks=2, seed=7, checkpoint_at=2)
    continued = resume_from_checkpoint(partial.checkpoint, steps=1, dt=1)
    assert continued.observations[-1] == run["observations"][-1]


def test_grouped_observation_reads_the_same_cells_and_time_as_the_frame(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    model = definition()
    model["agents"]["measures"] = {"active_first_row": "active if row == 0 else 0"}
    model["observables"]["first_row_count"] = "sum_active_first_row"
    result = build_model(definition=model, ticks=3, seed=7)
    assert result["ok"], result
    saved = get_store().load(result["payload"]["run_id"])
    counted = [sum(entity["active"] for entity in frame["entities"] if entity["y"] < 1)
               for frame in saved["state_frames"]]
    assert counted == [1, 3, 3, 5]
    assert counted == [row["first_row_count"] for row in saved["observations"]]
    model["agents"]["measures"]["active_first_row"] = "uniform(0,1)"
    with pytest.raises(ValueError, match="agents.measures.active_first_row"):
        validate_definition(model)


def test_grid_contract_rejects_fictional_or_unused_local_sources():
    invalid = definition()
    invalid["agents"]["update"]["active"] = "max(active, mean_active)"
    with pytest.raises(ValueError, match="参与主体更新"):
        validate_definition(invalid)
    invalid = definition()
    invalid["agents"]["update"]["x"] = "x + 1"
    with pytest.raises(ValueError, match="位置"):
        validate_definition(invalid)
    assert modeling_guide("用周期边界和真实四邻域元胞自动机建模湿地扩散")["payload"]["custom_engine"] == "fixed_periodic_grid"
    expanded = modeling_guide("用 100×100 格的元胞自动机建模湿地扩散")["payload"]
    assert expanded["next_tools"]["custom_model"] == "build_model"
    assert expanded["execution_scale"]["request"]["entities"] == 10_000


def test_grid_capability_comes_from_the_update_rules_not_a_literal_label():
    from dayan.agent.model_tools import _checked_definition
    from dayan.research.requirements import extract_request

    source = "新建元胞自动机，使用真实局部邻域传播"
    draft = definition()
    draft["mechanisms"] = ["四邻周期性传播"]
    draft["scenario"] = {"title": "周期网格", "setting": "行列环绕的固定格点", "agent_label": "格点",
                         "requirements": [{"quote": "真实局部邻域传播",
                                           "model_refs": ["agents.update.active", "agents.grid.reductions.peer"],
                                           "visual_refs": ["agents.initial.active", "space"]}]}
    checked = _checked_definition(draft, source, extract_request(source), {})
    assert checked["mechanisms"] == ["四邻周期性传播", "网格局部交互"]
    draft["agents"]["update"]["active"] = "max(active, mean_active)"
    with pytest.raises(ValueError, match="参与主体更新"):
        _checked_definition(draft, source, extract_request(source), {})
