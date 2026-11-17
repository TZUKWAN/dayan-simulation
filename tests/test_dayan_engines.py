"""R7 引擎验收测试（EquationEngine / GameEngine / OREngine）+ Wave-2 模型。

运行：python tests/test_dayan_engines.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.engines.sd import StockFlowSystem, teacup_spec  # noqa: E402
from dayan.engines.games import (MatrixGame, hawk_dove_matrix,  # noqa: E402
                                 prisoners_dilemma_matrix,
                                 replicator_dynamics)
from dayan.engines.or_lp import (check_feasible, optimality_gap,  # noqa: E402
                                 solve_lp, solve_transportation)


# ============ R7-a EquationEngine ============
def test_sd_teacup_analytic():
    """茶杯冷却：RK4 数值解 vs 解析解 T(t)=Tenv+(T0-Tenv)e^{-kt}。"""
    k, t_env, t0 = 0.07, 20.0, 90.0
    m = StockFlowSystem(teacup_spec(k=k, t_env=t_env, t0=t0))
    r = simulate(m, horizon=60.0, dt=0.25, parameters={"k": k, "Tenv": t_env},
                 rng=np.random.default_rng(0))
    T_final = r["final"]["T"]
    T_analytic = t_env + (t0 - t_env) * np.exp(-k * 60.0)
    assert abs(T_final - T_analytic) < 0.05, (
        f"茶杯冷却 {T_final:.4f} ≠ 解析 {T_analytic:.4f}")
    print(f"[PASS] SD 茶杯冷却：T(60)={T_final:.3f} vs 解析 {T_analytic:.3f}")


def test_sd_causal_graph():
    spec = teacup_spec()
    m = StockFlowSystem(spec)
    g = m.causal_graph_mermaid()
    assert "graph LR" in g and "--->" in g
    print("[PASS] 因果图 mermaid 渲染")


def test_sd_goodwin_bounded_cycle():
    """Goodwin 工资份额-就业周期（马理论宏观 SD 基准）：有界振荡。

    经典参数 v=1, α=0.025, γ=0.02, φ(λ)=−0.025+2λ：
    均衡 ω*=0.98, λ*=0.025，围绕均衡的闭轨道（保守系统）。
    经由统一编排器 ODE 分支（RK4）验证引擎内核。"""
    spec = {
        "stocks": {"omega": {"init": 0.95}, "emp": {"init": 0.03}},
        "flows": [
            {"name": "wage_growth", "expr": "omega * (2 * emp - 0.05)",
             "net_stock": "omega"},
            {"name": "lambda_growth",
             "expr": "emp * ((1 - omega) / 1.0 - 0.02)", "net_stock": "emp"},
        ],
        "params": {},
        "links": [{"from": "emp", "to": "omega", "polarity": "+"},
                  {"from": "omega", "to": "emp", "polarity": "-"}],
    }
    m = StockFlowSystem(spec)
    r = simulate(m, horizon=200.0, dt=0.05, rng=np.random.default_rng(0))
    omegas = [o["omega"] for o in r["observations"]]
    lambdas = [o["emp"] for o in r["observations"]]
    assert 0.9 < min(omegas) and max(omegas) < 1.04, (
        f"工资份额越界：{min(omegas):.3f}~{max(omegas):.3f}")
    assert 0.015 < min(lambdas) and max(lambdas) < 0.04, (
        f"就业越界：{min(lambdas):.4f}~{max(lambdas):.4f}")
    assert np.std(omegas) > 0.01, "无振荡（不成周期）"
    print(f"[PASS] Goodwin 周期：工资份额 {min(omegas):.3f}~{max(omegas):.3f}，"
          f"就业 {min(lambdas):.4f}~{max(lambdas):.4f}（有界闭轨道 ✓）")


# ============ R7-b GameEngine ============
def test_pd_unique_nash():
    g = prisoners_dilemma_matrix()
    ne = g.pure_nash()
    assert ne == [(1, 1)], f"PD 纳什 {ne}"
    print("[PASS] PD：唯一纯纳什 (背叛,背叛)")


def test_hawk_dove_mixed():
    g = hawk_dove_matrix(V=4.0, C=6.0)
    pures = g.pure_nash()
    assert set(pures) == {(0, 1), (1, 0)}, f"鹰鸽纯纳什 {pures}"
    mixed = g.mixed_nash_2x2()
    assert mixed is not None
    x_h = mixed[0][0]
    assert abs(x_h - 4.0 / 6.0) < 1e-9, f"混合均衡 x_H={x_h}"
    # 复制动态收敛到 x_H=V/C（BEH082）
    x = replicator_dynamics(g.A, x0=[0.9, 0.1], steps=3000, dt=0.01)
    assert abs(x[0] - 4.0 / 6.0) < 0.05, f"复制动态未收敛：{x}"
    print(f"[PASS] 鹰鸽：纯 {(pures)} + 混合 x_H=V/C={x_h:.2f}；"
          f"复制动态收敛到 {x[0]:.2f}")


def test_battle_of_sexes():
    A = np.array([[2.0, 0.0], [0.0, 1.0]])
    B = np.array([[1.0, 0.0], [0.0, 2.0]])
    g = MatrixGame(A, B, actions=["足球", "芭蕾"])
    pures = g.pure_nash()
    assert (0, 0) in pures and (1, 1) in pures, f"协调纯均衡 {pures}"
    mixed = g.mixed_nash_2x2()
    assert mixed is not None
    print(f"[PASS] 性别战：2 纯均衡 + 1 混合均衡（p={mixed[0][0]:.2f}）")


def _lmstudio_up(url="http://127.0.0.1:1234/v1") -> bool:
    try:
        import requests
        return requests.get(f"{url}/models", timeout=2).ok
    except Exception:
        return False


def test_game_llm_player_live():
    """LLM 玩家（真实 LM Studio）：遮蔽博弈名，动作合法即通过。
    LM Studio 未运行时自动 SKIP（回归测试不依赖服务在线）。"""
    import os
    if os.environ.get('DAYAN_TEST_LLM') != '1':
        print('[SKIP] 真实LLM测试未显式启用；未调用外部服务')
        return
    if not _lmstudio_up():
        print("[SKIP] LM Studio 未运行——该测试仅在服务在线时执行")
        return
    from src.agents.llm_client import LMStudioClient
    g = prisoners_dilemma_matrix()
    client = LMStudioClient(base_url="http://127.0.0.1:1234/v1",
                            model="qwen3.5-4b",
                            cache_path="results/smoke_games/cache.jsonl",
                            max_workers=2, default_max_tokens=120)
    from dayan.engines.games import llm_game_action
    from dayan.core import RngStreams
    game_rng = RngStreams(7).stream('game', 'player0')
    acts = set()
    for h in [None, [(0, 1), (1, 1)], [(1, 1)]]:
        acts.add(llm_game_action(client, g, my_index=0, history=h,
                                 rng=game_rng))
    assert acts <= {0, 1}, f"LLM 动作越界：{acts}"
    print(f"[PASS] LLM 玩家（遮蔽 PD）：动作分布 {sorted(acts)}（真实在环 ✓）")


# ============ R7-c OREngine ============
def test_lp_textbook():
    """教科书 LP：min -3x-2y s.t. x+y≤4, x+3y≤6 → 最优 (4,0)，值 12。"""
    r = solve_lp(c=[-3, -2], A_ub=[[1, 1], [1, 3]], b_ub=[4, 6],
                 bounds=[(0, None), (0, None)])
    assert r["ok"]
    assert abs(r["cost"] - (-12.0)) < 1e-6, f"LP 最优 {r['cost']} ≠ -12"
    print(f"[PASS] LP：最优值 12 @ x={tuple(round(v,3) for v in r['x'])}")


def test_transportation_and_propose_dispose():
    supplies = [20.0, 30.0]
    demands = [10.0, 25.0, 15.0]
    costs = [[8, 6, 10], [9, 12, 13]]
    r = solve_transportation(supplies, demands, costs)
    assert r["ok"]
    opt = r["cost"]
    # 可行提案（非最优）：单位成本高的路线承载更多
    x_bad = np.zeros((2, 3))
    x_bad[0, 0], x_bad[0, 1], x_bad[0, 2] = 10.0, 0.0, 10.0
    x_bad[1, 1], x_bad[1, 2] = 25.0, 5.0
    ok, why = check_feasible(x_bad, supplies, demands)
    assert ok, f"提案不可行：{why}"
    gap = optimality_gap(x_bad, costs, opt)
    assert gap > 0, f"非最优提案 gap={gap}"
    # 不可行提案被拒绝
    x_neg = np.array([[30.0, -10.0, 0.0], [0.0, 35.0, 15.0]])
    ok2, why2 = check_feasible(x_neg, supplies, demands)
    assert not ok2
    print(f"[PASS] 运输问题：最优 {opt:.1f}；提案可行且 gap={gap:.1f}>0；"
          f"不可行方案被拒（{why2}）")


if __name__ == "__main__":
    test_sd_teacup_analytic()
    test_sd_causal_graph()
    test_sd_goodwin_bounded_cycle()
    test_pd_unique_nash()
    test_hawk_dove_mixed()
    test_battle_of_sexes()
    test_game_llm_player_live()
    test_lp_textbook()
    test_transportation_and_propose_dispose()
    print("\n===== R7 引擎：全部通过 =====")
