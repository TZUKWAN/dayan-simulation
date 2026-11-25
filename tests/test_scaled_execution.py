import numpy as np
import pytest

from dayan.agent.model_tools import build_model
from dayan.agent.scenario_tools import modeling_guide
from dayan.population import decode_column
from dayan.run_store import get_store, state_stream
from dayan.runtime import resume_from_checkpoint, run_model_full
from dayan.scaling import ARRAY_KERNEL, check_scale, scale_intent


def grid(rows, cols, backend, stochastic=False):
    update = "1 if active > 0 or peer > 0 and uniform(0,1) < rate else 0" if stochastic else "max(active,peer)"
    return {
        "name": "真实周期邻域试验",
        "description": "周期邻域传播与同步状态",
        "kind": "agents", "time_unit": "MCS",
        "parameters": {"rate": {"default": .45, "type": "float"}} if stochastic else {},
        "agents": {"backend": backend, "grid": {"rows": rows, "columns": cols, "degree": 4,
                   "reductions": {"peer": {"op": "max", "field": "active", "lag": 1}}},
                   "initial": {"active": "1 if id == 0 else 0"}, "update": {"active": update},
                   "measures": {"margin": "active if row == 0 else 0"}, "type": "cell", "color_by": "active"},
        "observables": {"active": "sum_active", "edge": "sum_margin", "population": "n_agents"},
    }


def test_explicit_scale_is_kept_and_only_that_shape_can_build():
    source = "用 1,024×2,048 的固定周期元胞网格做四邻域仿真，运行 40 步。每步保存逐格状态。"
    expected = {"rows":1024, "columns":2048}
    request = scale_intent(source)
    assert request["grid"] == expected and request["entities"] == 2_097_152 and request["all_frames"]
    assert scale_intent("用 100 万个主体实际模拟")["entities"] == 1_000_000
    assert scale_intent("用 1,000,000 名居民参与仿真")["entities"] == 1_000_000
    assert modeling_guide(source)["payload"]["execution_scale"]["request"]["grid"] == expected
    with pytest.raises(ValueError, match="实际定义"):
        check_scale(request, {"grid": {"rows":2048, "columns":1024}, "entities": 2_097_152})
    with pytest.raises(ValueError, match="实际定义为8邻域"):
        check_scale(request, {"grid": expected, "grid_degree":8, "entities": 2_097_152})


def test_scalar_and_columnar_agree_on_local_rules_and_group_observations(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    runs = [build_model(definition=grid(9, 8, backend), ticks=8, dt=1, seed=31) for backend in ("scalar","array")]
    assert all(run["ok"] for run in runs), runs
    scalar, array = [run["payload"] for run in runs]
    assert scalar["observations"] == array["observations"]
    records = [get_store().load(result["run_id"]) for result in (scalar,array)]
    for orig, compiled in zip(*(r["state_frames"] for r in records)):
        values = decode_column(compiled["population"]["columns"]["active"], 72)
        assert values.tolist() == [entity["active"] for entity in orig["entities"]]


def test_large_archive_retains_all_cells_and_continues_exact_random_state(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    model = grid(83, 71, "auto", stochastic=True)
    first = build_model(definition=model, ticks=6, dt=1, seed=51)
    assert first["ok"], first
    payload = first["payload"]
    saved = get_store().load(payload["run_id"])
    count = 83*71
    assert saved["manifest"]["scale"]["entities"] == count
    assert saved["manifest"]["scale"]["kernel"] == ARRAY_KERNEL
    assert len(saved["state_frames"]) == 7 and saved["manifest"]["scale"]["all_steps_archived"]
    playback = state_stream(saved)
    assert playback["n_entities_max"] == count and playback["lattice_cells"] == count
    assert len(playback["frames"]) == 7
    assert all(frame["population"]["count"] == count and "columns" not in frame["population"]
               for frame in playback["frames"])
    from dayan.view_analysis import analyze_view
    stats = analyze_view([saved], saved["run_id"], "active")["lattice"]
    assert (stats["width"], stats["height"]) == (71, 83)
    assert stats["layers"][0]["count"] == saved["observations"][-1]["active"]
    continued = resume_from_checkpoint(saved["checkpoint"], 6, 1, capture_state=True)
    full = run_model_full(saved["model_id"], ticks=12, dt=1, seed=51, capture_state=True, strict=True)
    assert continued.observations == full.observations[7:]
    np.testing.assert_array_equal(
        decode_column(continued.state_frames[-1]["population"]["columns"]["active"], count),
        decode_column(full.state_frames[-1]["population"]["columns"]["active"], count))


def test_float_columns_round_trip_without_losing_signed_zero():
    from dayan.population import encode_column
    raw = np.array([-0.0, 0.0, 1.0/3, -17.25])
    recovered = decode_column(encode_column(raw), len(raw))
    np.testing.assert_array_equal(recovered.view(np.uint64), raw.view(np.uint64))


def test_variadic_extrema_share_the_same_arity_in_both_kernels():
    from dayan.array_agents import ArrayExpression
    from dayan.custom_models import Expression

    rule = "max(a, 0, 2, 3, 4)"
    np.testing.assert_array_equal(ArrayExpression(rule, {"a"}).evaluate({"a": np.array([1., 8.])}, 2),
                                  [Expression(rule, {"a"}).value({"a": value}) for value in (1., 8.)])
    with pytest.raises(ValueError, match="需要 2 至 9 个数值参数"):
        Expression("max(a)", {"a"})


def test_array_expression_releases_previous_columns_without_waiting_for_gc():
    import weakref
    from dayan.array_agents import ArrayExpression

    value = np.arange(4., dtype=float)
    reference = weakref.ref(value)
    result = ArrayExpression("state + 1", {"state"}).evaluate({"state": value}, 4)
    del value
    np.testing.assert_array_equal(result, [1, 2, 3, 4])
    assert reference() is None
