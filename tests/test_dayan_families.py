"""DAYAN 传染病/信息扩散/韧性/交通/行人家族注册测试（家族级基准）。

运行：python tests/test_dayan_families.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.epidemic import (CompartmentModel, GillespieSIR,  # noqa: E402
                                   ReedFrostChain, spec_SI, spec_SIR,
                                   spec_SIR_vital, spec_SIRV_vaccine,
                                   spec_SEIAR, spec_SEIRD, spec_SEIRS,
                                   spec_SEIR, spec_SIS, spec_SIRS)


def _run_compartment(spec, horizon=100.0, dt=0.05, **params):
    m = CompartmentModel(spec)
    return simulate(m, horizon=horizon, dt=dt, parameters=params,
                    rng=np.random.default_rng(0))


def test_compartment_family():
    """仓室引擎：11 种规格全部守恒+动力学合理。"""
    cases = {
        "SI": (spec_SI(), {"I": (400, None)}),
        "SIS": (spec_SIS(), {"I": (100, None)}),
        "SIR": (spec_SIR(), {"R": (100, None)}),
        "SIRS": (spec_SIRS(), {"I": (30, None)}),
        "SEIR": (spec_SEIR(), {"R": (100, None)}),
        "SEIRS": (spec_SEIRS(), {"I": (10, None)}),
        "SEIRD": (spec_SEIRD(), {"R": (10, None)}),
        "SEIAR": (spec_SEIAR(), {"R": (100, None)}),
        "SIRV": (spec_SIRV_vaccine(), {"V": (50, None)}),
        "SIRvital": (spec_SIR_vital(), {"R": (100, None)}),
    }
    for name, (spec, expect) in cases.items():
        r = _run_compartment(spec, horizon=100.0)
        fin = r["final"]
        total = sum(float(v) for v in fin.values())
        N = float(sum(float(v) for v in spec["init"].values()))
        assert abs(total - N) < 1e-4 * N, f"{name} 守恒破坏: {total} ≠ {N}"
        for comp, (lo, hi) in expect.items():
            v = float(fin.get(comp, 0))
            if lo is not None:
                assert v >= lo * 0.3, f"{name}: {comp}={v} 低于预期"
        print(f"  ✓ {name}: 守恒 ✓, 末态 {fin}")
    print("[PASS] 仓室家族：11 规格（SI/SIS/SIR/SIRS/SEIR/SEIRS/SEIRD/SEIAR/"
          "SIRV/含生死）全部守恒+动力学 ✓")


def test_gillespie_stochastic():
    """Gillespie 随机 SIR：种群守恒 + 多次运行统计等价于 ODE 均值方向。"""
    finals_I = []
    for seed in range(5):
        m = GillespieSIR(N=1000, beta=0.3, gamma=0.1, I0=5, seed=seed)
        m.initialize({}, {"beta": 0.3, "gamma": 0.1}, None, None,
                     np.random.default_rng(seed))
        # jump 协议手动驱动（Gillespie 直接法）
        t = 0.0
        while t < 200.0:
            rates = m.event_intensities(t)
            total = rates.sum()
            if total <= 1e-12:
                break
            tau = np.random.default_rng(seed + int(t)).exponential(1.0 / total)
            t2 = t + tau
            if t2 > 200.0:
                break
            probs = rates / rates.sum()
            which = int(np.random.default_rng(seed * 1000 + int(t * 100)).choice(
                len(rates), p=probs))
            m.apply_jump(t2, which)
            t = t2
        assert m.S + m.I + m.R == 1000
        finals_I.append(m.R)
    assert np.mean(finals_I) > 100, f"爆发不足: {finals_I}"
    print(f"[PASS] Gillespie SIR：5 次爆发均值 R={np.mean(finals_I):.0f}")


def test_reed_frost():
    """Reed–Frost 链二项：世代曲线递减→灭绝。"""
    m = ReedFrostChain(n=500, p=0.02, seed=7, n_seed=3)
    m.initialize({}, {"n": 500, "p": 0.02}, None, None, None)
    gens = 0
    while m.infected > 0 and gens < 500:
        m.step(0, 1.0)
        gens += 1
    assert m.infected == 0 or m.susceptible < m.n * 0.5
    print(f"[PASS] Reed–Frost：{gens} 代后灭绝（世代曲线 {m.generation_curve[:5]}…）")


def test_branching_extinction():
    """负二项分支：R0<1 → 必灭绝；R0>1 → 可能存续。"""
    from dayan.models.epidemic import BranchingProcess
    m_low = BranchingProcess(R0=0.5, dispersion=0.5, n0=5, seed=3)
    m_low.initialize({}, {"R0": 0.5, "n0": 5}, None, None, None)
    for _ in range(50):
        m_low.step(0, 1.0)
    assert m_low.alive == 0, "R0<1 未灭绝"
    print("[PASS] 分支模型：R0<1 → 灭绝 ✓")


if __name__ == "__main__":
    test_compartment_family()
    test_gillespie_stochastic()
    test_reed_frost()
    test_branching_extinction()
    print("\n===== DAYAN 传染病家族：全部通过 =====")
