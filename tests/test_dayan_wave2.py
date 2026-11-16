"""Wave-2 目录模型验收测试（Solow/SIS/选民/Bass/复制动态）。

运行：python tests/test_dayan_wave2.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.wave2 import (BassModel, SISModel, SolowModel,  # noqa: E402
                                VoterModel, replicator_hawk_dove)


def test_solow_steady_state():
    """Solow：k(t) 收敛到 k*=(s/δ)^{1/(1-α)}（解析）。"""
    s, alpha, delta = 0.25, 0.3, 0.05
    k_star = (s / delta) ** (1 / (1 - alpha))
    m = SolowModel(s=s, alpha=alpha, delta=delta, k0=1.0)
    r = simulate(m, horizon=300.0, dt=0.1,
                 parameters={"s": s, "alpha": alpha, "delta": delta, "k0": 1.0},
                 rng=np.random.default_rng(0))
    k_final = r["final"]["k"]
    assert abs(k_final - k_star) / k_star < 0.01, (
        f"k_final {k_final:.2f} ≠ k* {k_star:.2f}")
    print(f"[PASS] Solow：k 收敛 {k_final:.2f} ≈ k*={k_star:.2f}")


def test_sis_endemic():
    """SIS：地方病均衡 I* = 1 − 1/R0（占比，ODE）。"""
    beta, gamma = 0.5, 0.2
    R0 = beta / gamma
    i_star = 1 - 1 / R0
    m = SISModel(beta=beta, gamma=gamma, i0=0.1, N=1.0)
    r = simulate(m, horizon=100.0, dt=0.1,
                 parameters={"beta": beta, "gamma": gamma, "i0": 0.1},
                 rng=np.random.default_rng(0))
    i_final = r["final"]["I_frac"]
    assert abs(i_final - i_star) < 0.02, (
        f"I_frac {i_final:.3f} ≠ I* {i_star:.3f}")
    print(f"[PASS] SIS：地方病均衡 I_frac={i_final:.3f} ≈ I*={i_star:.3f}"
          f"（R0={R0:.1f}）")


def test_voter_consensus_probability():
    """选民模型：共识值期望 ≈ 初始 1 份额（多次重复）。"""
    frac0 = 0.4
    outcomes = []
    for seed in range(20):
        m = VoterModel(n=100, frac1_0=frac0, seed=seed)
        m.initialize({}, {"n": 100, "frac1_0": frac0}, None, None,
                     np.random.default_rng(seed))
        for _ in range(20_000):
            m.step(0, 1.0)
            if m.consensus is not None:
                break
        if m.consensus is not None:
            outcomes.append(m.consensus)
    mean_c = float(np.mean(outcomes))
    assert abs(mean_c - frac0) < 0.12, (
        f"共识期望 {mean_c:.2f} 偏离初始份额 {frac0}")
    print(f"[PASS] 选民模型：20 次共识均值 {mean_c:.2f} ≈ 初始份额 {frac0}"
          f"（吸收性马尔可夫 ✓）")


def test_bass_analytic():
    """Bass：F(t) 对解析式（p=0.03, q=0.38 经典参数）。"""
    p, q = 0.03, 0.38
    m = BassModel(p=p, q=q, m=1.0)
    m.initialize({}, {"p": p, "q": q, "m": 1.0}, None, None, None)
    for t_check in (5.0, 15.0, 30.0):
        # 步进到 t_check
        pass
    # ODE 积分用 simulate
    m2 = BassModel(p=p, q=q, m=1.0)
    m2.initialize({}, {"p": p, "q": q, "m": 1.0}, None, None, None)
    from dayan import simulate as _sim
    r = _sim(m2, horizon=30.0, dt=0.05,
             parameters={"p": p, "q": q, "m": 1.0}, rng=np.random.default_rng(0))
    frac_30 = r["final"]["frac"]
    t = 30.0
    F = (1 - np.exp(-(p + q) * t)) / (1 + (q / p) * np.exp(-(p + q) * t))
    assert abs(frac_30 - F) < 0.02, f"采纳率 {frac_30:.3f} ≠ 解析 {F:.3f}"
    print(f"[PASS] Bass 扩散：F(30)={frac_30:.3f} ≈ 解析 {F:.3f}")


def test_replicator_hawk_dove():
    """复制动态（BEH082）：鹰鸽收敛到混合均衡 x_H = V/C。"""
    x = replicator_hawk_dove(V=4.0, C=6.0, x0=0.9, steps=2000, dt=0.01)
    assert abs(x[0] - 4.0 / 6.0) < 0.02, f"x_H {x[0]:.3f} ≠ 2/3"
    print(f"[PASS] 复制动态：x_H 收敛到 {x[0]:.3f} = V/C={4/6:.3f}")


if __name__ == "__main__":
    test_solow_steady_state()
    test_sis_endemic()
    test_voter_consensus_probability()
    test_bass_analytic()
    test_replicator_hawk_dove()
    print("\n===== Wave-2 目录模型：全部通过 =====")
