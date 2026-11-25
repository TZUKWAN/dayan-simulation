"""Structural and execution checks for the three-party CA–ABM game."""

import numpy as np
import pytest

from dayan.agent.scenario_tools import modeling_guide
from dayan.agent.verification import _check_audit_lattice
from dayan.lattice import imitate_best, periodic_neighbors
from dayan.models.spatial_audit import GreenSubsidyAuditGame
from dayan.run_store import state_stream
from dayan.runtime import run_model_full


def test_same_role_best_neighbor_is_local_and_periodic():
    four = periodic_neighbors(5, 5, 4)
    eight = periodic_neighbors(5, 5, 8)
    assert four[0].tolist() == [20, 5, 4, 1]
    assert set(eight[0]) == {20, 5, 4, 1, 24, 21, 9, 6}
    state = np.zeros(25, np.uint8)
    gains = np.zeros(25)
    state[[20, 12]] = 1
    gains[[20, 12]] = [0.0, 1.0]
    rng = np.random.default_rng(7)
    assert imitate_best(state, gains, state, gains, four, 1, rng)[0] == 0
    lagged = gains.copy()
    lagged[20] = 1
    next_state = imitate_best(state, gains, state, lagged, four, 1, rng)
    assert next_state[0] == 1
    assert state[0] == 0


def test_all_payoff_branches_and_the_published_discrepancy():
    game = GreenSubsidyAuditGame()
    expected = [
        [-.703, .353, 3.95], [-.003, .003, .2],
        [0., 0., 3.6], [0., 0., .2],
        [3.8501, -.02, -.25], [.0001, -.0005, .2],
        [.0001, 0., .1], [.0001, 0., .2],
    ]
    np.testing.assert_allclose(game.payoff_table(), expected, atol=1e-12)
    expected[2][2] = .1
    np.testing.assert_allclose(GreenSubsidyAuditGame(fine_without_audit=1).payoff_table(),
                               expected, atol=1e-12)


def test_independent_schedules_lattice_and_conservation():
    settings = dict(grid_side=6, audit_window=2, audit_gap=1, audit_mode=2,
                    regulator_period=2, farm_period=3, audit_period=2, farm_lag=2)
    actual = run_model_full("NET122", settings, ticks=9, seed=42, capture_state=True,
                            strict=True, interventions=[{"at_t": 4, "params": {"audit_max": .2}}])
    rows = actual.observations
    assert [o["sim_t"] for o in rows] == list(range(10))
    assert all(o["audited_cells"] == 0 for o in rows[3::3])
    assert all(r["audit_target"] <= .2 for r in rows[5:])
    assert all(o["regulator_switches"] == 0 for o in rows[1::2])
    assert all(o["farm_switches"] == 0 for i, o in enumerate(rows) if i % 3)
    checks = {"issues": []}
    _check_audit_lattice(actual.state_frames, {o["sim_t"]: o for o in rows}, settings, checks)
    assert checks["issues"] == []
    assert checks["lattice"]["matched_frames"] == 10
    stream = state_stream({"model_id": "NET122", "run_id": actual.manifest["run_id"],
                           "state_frames": actual.state_frames, "manifest": actual.manifest,
                           "observations": rows}, sample_every=4)
    assert stream["lattice_cells"] == 36 and stream["provenance"] == "lattice"
    assert [f["sim_t"] for f in stream["frames"]] == [0, 4, 8, 9]
    with pytest.raises(ValueError, match="整数"):
        run_model_full("NET122", settings, ticks=5, interventions=[{"at_t": 2.5, "params": {"audit_max": .6}}])


def test_large_default_and_agent_routing():
    guide = modeling_guide("构建农业绿色补贴审计三方演化博弈，融合元胞自动机和多主体仿真。")["payload"]
    assert guide["design_first"] and guide["models"] == [] and guide["eligible_models"] == []
    assert guide["next_tools"]["custom_model"] == "build_model" and guide["next_tools"]["existing_model"] is None
    native = modeling_guide("用 NET122 运行农业绿色补贴审计三方演化博弈，融合元胞自动机和多主体仿真。")["payload"]
    assert not native["design_first"] and native["eligible_models"] == ["NET122"]
    assert native["next_tools"]["existing_model"] == "reviewed_run"
    independent = modeling_guide("构建农业绿色补贴审计三方演化博弈，使用100×100格的元胞自动机和多主体仿真。")["payload"]
    assert independent['design_first'] and independent['eligible_models']==[]
    assert independent['next_tools']['custom_model']=='build_model'
    assert independent['next_tools']['existing_model'] is None
    assert "NET122" not in modeling_guide("两个产业的技术竞争演化博弈。")["payload"]["eligible_models"]
    assert "NET122" not in modeling_guide("农业绿色补贴审计，要求真实县域数据用于独立留出验证。")["payload"]["eligible_models"]
    first = run_model_full("NET122", ticks=17, seed=42, capture_state=True, strict=True)
    second = run_model_full("NET122", ticks=17, seed=42, capture_state=True, strict=True)
    assert first.observations == second.observations
    assert len(first.state_frames[0]["lattice"]["layers"][0]["values"]) == 10000
    assert first.manifest["actual"]["time_unit"] == "蒙特卡洛步（MCS）"
    assert first.manifest["model_method"]["equations"]
