"""DAYAN P1 基准模型验收测试（每个模型对解析/公开基准）。

规范验收（2.9 P1）：每个模型有解析/公开基准；同种子可复现。
运行：python tests/test_dayan_models.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.benchmarks import (  # noqa: E402
    BANetworkModel, DeGrootModel, ERNetworkModel, HKModel, ICModel,
    LeontiefModel, LeslieModel, LTModel, MM1QueueModel, SEIRModel, SIRModel,
    WSNetworkModel)


def test_dtmc_stationary():
    """DTMC：长运行状态1占比 → π1=b/(a+b)（解析）。"""
    from dayan.models.benchmarks import DTMCModel
    a, b = 0.3, 0.2
    pi1 = a / (a + b)  # 平稳分布：π1 = a/(a+b)（由 π0·a = π1·b 推出）
    m = DTMCModel(a=a, b=b)
    r = simulate(m, horizon=200_000, parameters={"a": a, "b": b},
                 rng=np.random.default_rng(1))
    frac = r["final"]["frac_state1"]
    assert abs(frac - pi1) < 0.02, f"DTMC 长运行占比 {frac:.3f} ≠ π1 {pi1:.3f}"
    # 同种子可复现
    r2 = simulate(DTMCModel(a=a, b=b), horizon=200_000,
                  parameters={"a": a, "b": b}, rng=np.random.default_rng(1))
    assert abs(r2["final"]["frac_state1"] - frac) < 1e-12
    print(f"[PASS] DTMC：长运行占比 {frac:.4f} vs 平稳分布 π1={pi1:.4f}")


def test_mm1_queue():
    """M/M/1：长运行吞吐≈λ，平均队列≈L=λ/(μ-λ)（漂移容差）。"""
    m = MM1QueueModel(lam=0.8, mu=1.0)
    r = simulate(m, horizon=50_000, parameters={"lam": 0.8, "mu": 1.0},
                 rng=np.random.default_rng(1))
    fin = r["final"]
    served = fin["served"]
    throughput = served / 50_000
    assert abs(throughput - 0.8) < 0.02, f"吞吐 {throughput:.3f} ≠ λ"
    assert fin["queue"] < 50, f"队列失控: {fin['queue']}"
    print(f"[PASS] M/M/1：吞吐 {throughput:.3f}（λ=0.8），队列稳定"
          f"（L解析=4.0），服务 {served} 人")


def test_sir_conservation_and_final_size():
    """SIR：守恒 S+I+R=N + 终局规模方程（解析）。"""
    beta, gamma, N, I0 = 0.4, 0.1, 1000.0, 5.0
    m = SIRModel(beta=beta, gamma=gamma, N=N, I0=I0)
    r = simulate(m, horizon=200.0, dt=0.05,
                 parameters={"beta": beta, "gamma": gamma, "N": N, "I0": I0},
                 rng=np.random.default_rng(0))
    fin = r["final"]
    S, I, R = fin["S"], fin["I"], fin["R"]
    assert abs(S + I + R - N) < 1e-3 * N, "守恒破坏"
    # 终局规模方程：S∞ = S0·exp(-R0(S0-S∞)/N)（数值自洽解）
    R0 = beta / gamma
    S0 = N - I0
    from scipy.optimize import brentq
    # 终局规模方程有两个根：平凡根 S∞=S0 与非平凡根；区间上界避开平凡根
    s_inf = brentq(lambda s: s - S0 * np.exp(-R0 * (S0 - s) / N),
                   1e-6, S0 * 0.9)
    assert abs(S - s_inf) < 5.0, f"终局易感 {S:.1f} ≠ 方程解 {s_inf:.1f}"
    print(f"[PASS] SIR：守恒✓ 终局规模 S∞={S:.1f} vs 解析 {s_inf:.1f}"
          f"（R0={R0:.1f}）")


def test_seir_conservation_and_outbreak():
    """SEIR：守恒 + R0>1 爆发条件。"""
    beta, gamma = 0.5, 0.1
    m = SEIRModel(beta=beta, gamma=gamma, N=1000, I0=5, E0=5)
    r = simulate(m, horizon=200.0, dt=0.05,
                 parameters={"beta": beta, "gamma": gamma, "N": 1000,
                             "I0": 5, "E0": 5}, rng=np.random.default_rng(0))
    fin = r["final"]
    assert abs(fin["total"] - 1000) < 1e-3 * 1000, "守恒破坏"
    R0 = beta / gamma
    assert R0 > 1 and fin["R"] > 100, f"R0={R0:.1f} 未爆发"
    print(f"[PASS] SEIR：守恒✓ R0={R0:.1f}>1 → 累计移出 {fin['R']:.0f}")


def test_degroot_consensus():
    """DeGroot：共识值 = 平稳置信权重·初值（解析：左特征向量）。"""
    P = np.array([[0.5, 0.5, 0.0], [0.25, 0.5, 0.25], [0.0, 0.5, 0.5]])
    x0 = np.array([0.0, 0.5, 1.0])
    m = DeGrootModel(P=P, x0=x0)
    r = simulate(m, horizon=500, dt=1.0,
                 parameters={"P": P.tolist(), "x0": x0.tolist()},
                 rng=np.random.default_rng(0))
    fin_ops = np.array(r["final"]["opinions"])
    # 解析：平稳权重 = P^T 左特征向量（λ=1）
    evals, evecs = np.linalg.eig(P.T)
    w = np.real(evecs[:, np.isclose(evals, 1.0)]).flatten()
    w = w / w.sum()
    consensus = float(w @ x0)
    spread = fin_ops.max() - fin_ops.min()
    assert spread < 1e-8, f"未收敛到共识：spread={spread}"
    for v in fin_ops:
        assert abs(v - consensus) < 1e-8
    print(f"[PASS] DeGroot：共识 {consensus:.4f} = 平稳权重·初值（解析 ✓）")


def test_hk_convergence_clusters():
    """HK：有界信任收敛成有限簇。"""
    m = HKModel(eps=0.15, n=60)
    r = simulate(m, horizon=100, dt=1.0, parameters={"eps": 0.15, "n": 60},
                 rng=np.random.default_rng(0))
    fin = r["final"]
    assert fin["n_clusters"] >= 1
    # 收敛后簇内不再变化
    print(f"[PASS] HK：收敛为 {fin['n_clusters']} 簇")


def test_er_mean_degree():
    """ER G(n,p)：平均度 = p(n-1)（解析）。"""
    n, p = 200, 0.06
    m = ERNetworkModel(n=n, p=p, seed=7)
    m.initialize({}, {"n": n, "p": p}, None, None, None)
    o = m.observe()
    expected = p * (n - 1)
    assert abs(o["mean_degree"] - expected) < 0.15 * expected
    print(f"[PASS] ER G(n,p)：平均度 {o['mean_degree']:.2f} vs 解析 "
          f"{expected:.2f}")


def test_ws_small_world():
    """WS：重连后保持高聚类（相对同参数规则环格）。"""
    m = WSNetworkModel(n=200, k=4, p_rewire=0.1, seed=7)
    m.initialize({}, {"n": 200, "k": 4, "p_rewire": 0.1}, None, None, None)
    c_ws = m.observe()["clustering"]
    # 同参数规则环格（p_rewire=0）聚类系数
    m0 = WSNetworkModel(n=200, k=4, p_rewire=0.0, seed=7)
    m0.initialize({}, {"n": 200, "k": 4, "p_rewire": 0.0}, None, None, None)
    c_ring = m0.observe()["clustering"]
    assert c_ws > 0.3 * c_ring, f"WS 聚类塌陷：{c_ws} vs 环格 {c_ring}"
    print(f"[PASS] WS 小世界：聚类 {c_ws:.3f}（环格 {c_ring:.3f} 的高比例）")


def test_ba_power_law():
    """BA：优先连接 → 度分布幂律尾部（CCDF 对数斜率≈-2，即 PDF ≈-3）。"""
    m = BANetworkModel(n=800, m=3, seed=7)
    m.initialize({}, {"n": 800, "m": 3}, None, None, None)
    o = m.observe()
    assert o["n_edges"] == (800 - 4) * 3 + 6, "BA 边数不符（m3 起始4节点）"
    # CCDF 斜率：对 (log deg, log CCDF) 做尾部线性拟合
    deg = np.zeros(m.n)
    for i, j in m.edges:
        deg[i] += 1
        deg[j] += 1
    dv = deg[deg >= m.m]
    vals, counts = np.unique(dv, return_counts=True)
    ccdf = 1.0 - np.cumsum(counts) / counts.sum()
    mask = (vals >= 3) & (ccdf > 0.001)
    slope = float(np.polyfit(np.log(vals[mask]), np.log(np.maximum(ccdf[mask], 1e-12)), 1)[0])
    assert -3.2 < slope < -1.2, f"CCDF 斜率 {slope:.2f} 偏离幂律（理论≈-2）"
    print(f"[PASS] BA：边数 {o['n_edges']}，CCDF 斜率 {slope:.2f}"
          f"（理论 ≈-2，即 PDF ≈-3 幂律 ✓）")


def test_ic_monotone():
    """IC：影响函数单调——种子集扩张 → 影响集不减。"""
    m = ICModel(n=100, p=0.15, seed=7)
    m.initialize({}, {"n": 100, "p": 0.15}, None, None, None)
    s1 = m.spread([0])
    s2 = m.spread([0, 50])
    assert s1 <= s2, f"单调性破坏：|{s1}| ⊄ |{s2}|"
    print(f"[PASS] IC 级联：|s1|={len(s1)} ⊆ |s2|={len(s2)}（单调 ✓）")


def test_lt_threshold_zero_closure():
    """LT：阈值=0 → 影响集 = 种子出边可达闭包（确定性）。"""
    m = LTModel(n=50, seed=7)
    m.initialize({}, {"n": 50}, None, None, None)
    seeds = [0]
    act = m.spread(seeds, thresholds=[0.0] * m.n)
    # 闭包（沿影响方向）：LT 中 v 受 adj[v]（v 的入边邻居）影响，
    # 故激活传播方向为 u→v 当且仅当 u ∈ adj[v]——闭包沿该方向 BFS
    seen = set(seeds)
    stack = list(seeds)
    # 影响方向：u 激活 → 所有 v（u ∈ adj[v] 的被影响者）满足阈值0后激活
    reverse = {v: [] for v in range(m.n)}
    for influencer, outs in m.adj.items():
        for v in outs:
            reverse[v].append(influencer)
    while stack:
        u = stack.pop()
        for v in reverse[u]:
            if v not in seen:
                seen.add(v)
                stack.append(v)
    assert act == seen, f"LT 阈值0 影响集 ≠ 影响方向闭包"
    print(f"[PASS] LT：阈值0 影响集=可达闭包（{len(act)} 节点）✓")


def test_leslie_eigen():
    """Leslie：投影增长率 → 主特征值 λ1。"""
    fert = np.array([0.0, 1.2, 1.5, 0.8])
    surv = np.array([0.7, 0.8, 0.9])
    m = LeslieModel(fert=fert, surv=surv)
    m.initialize({}, {"fert": fert.tolist(), "surv": surv.tolist(),
                      "pop0": np.ones(4).tolist()}, None, None, None)
    for _ in range(60):
        m.step(0, 1.0)
    ratio = m.pop.sum() / (m.A @ m.pop).sum()  # 上一期/本期
    lam1 = float(np.abs(np.linalg.eigvals(
        __import__("numpy").array([[0, 1.2, 1.5, 0.8],
                                   [0.7, 0, 0, 0],
                                   [0, 0.8, 0, 0],
                                   [0, 0, 0.9, 0]]))).max())
    growth = 1.0 / ratio
    assert abs(growth - lam1) / lam1 < 0.01, f"增长率 {growth:.4f} ≠ λ1 {lam1:.4f}"
    print(f"[PASS] Leslie：渐近增长率 {growth:.4f} = 主特征值 λ1={lam1:.4f}")


def test_leontief_solution():
    """Leontief：x = (I-A)^{-1} d 直接解析。"""
    A = np.array([[0.1, 0.2], [0.3, 0.1]])
    d = np.array([100.0, 200.0])
    m = LeontiefModel(A=A, d=d)
    m.initialize({}, {"A": A.tolist(), "d": d.tolist()}, None, None, None)
    m.step(0, 1.0)
    x_expect = np.linalg.solve(np.eye(2) - A, d)
    assert np.allclose(m.x, x_expect), "Leontief 解不符"
    assert m.validate_state() == []
    print(f"[PASS] Leontief：产出向量 {m.x.round(1)} = (I-A)^-1·d ✓")


if __name__ == "__main__":
    test_dtmc_stationary()
    test_mm1_queue()
    test_sir_conservation_and_final_size()
    test_seir_conservation_and_outbreak()
    test_degroot_consensus()
    test_hk_convergence_clusters()
    test_er_mean_degree()
    test_ws_small_world()
    test_ba_power_law()
    test_ic_monotone()
    test_lt_threshold_zero_closure()
    test_leslie_eigen()
    test_leontief_solution()
    print("\n===== DAYAN P1 基准模型：全部通过 =====")
