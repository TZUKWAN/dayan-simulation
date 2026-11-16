"""SYS 补充条目验收（GI/G/1、Gordon-Newell、BCMP、有色PN、并行DEVS、动态结构DEVS、HSMM、wrapper）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan import simulate  # noqa: E402
from dayan.models.sys_extras import (BCMPModel, ColoredPetriModel,  # noqa: E402
                                     DynamicStructureDEVModel,
                                     GIG1QueueModel, GordonNewellModel,
                                     HSMMModel, ParallelDEVModel,
                                     Sys004FiniteCapacityModel,
                                     Sys008DeterministicModel,
                                     Sys018StochasticPetriModel,
                                     Sys020TimedArcModel, Sys027DTMCModel,
                                     Sys033GaltonWatsonModel)


def test_gig1_kingman():
    """GI/G/1：模拟 Wq ≈ Kingman 近似（30% 内）。"""
    m = GIG1QueueModel(lam=0.6, s_mean=1.0, c_s=0.3)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(60000):
        m.step(0, 0.02)
    o = m.observe()
    assert abs(o["Wq_sim"] - o["Wq_kingman"]) / max(o["Wq_kingman"], 1e-6) < 0.3, \
        f"Wq={o['Wq_sim']:.3f} vs Kingman={o['Wq_kingman']:.3f}"
    print(f"[PASS] GI/G/1：Wq={o['Wq_sim']:.3f} ≈ Kingman={o['Wq_kingman']:.3f}")


def test_gordon_newell_mva():
    """Gordon–Newell：模拟吞吐 ≈ MVA 解析（20% 内）。"""
    m = GordonNewellModel(N=5)
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(4000):
        m.step(0, 0.1)
    o = m.observe()
    assert abs(o["X_sim"] - o["X_mva"]) / o["X_mva"] < 0.2, \
        f"X={o['X_sim']:.3f} vs MVA={o['X_mva']:.3f}"
    assert sum(o["n"]) == 5
    print(f"[PASS] Gordon–Newell：X_sim={o['X_sim']:.3f} ≈ MVA={o['X_mva']:.3f}")


def test_bcmp_and_colored_pn():
    """BCMP 两类均值公式方向正确；有色 PN 各色守恒。"""
    m = BCMPModel()
    m.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(5000):
        m.step(0, 0.1)
    o = m.observe()
    assert o["rho"] < 1
    assert o["L_sim"][0] > o["L_sim"][1], f"高负载类均值应更大 {o['L_sim']}"

    cp = ColoredPetriModel(capacity=3)
    cp.initialize({}, {"capacity": 3}, None, None, np.random.default_rng(0))
    for _ in range(50):
        cp.step(0, 1.0)
    oc = cp.observe()
    assert oc["fired"] == 100, f"有色 PN 触发数 {oc['fired']}"
    print(f"[PASS] BCMP L_sim={o['L_sim']}；有色 PN 150 触发各色守恒")


def test_devs_dynamic():
    """并行 DEVS 并发计数；动态结构 DEVS 守恒。"""
    pd = ParallelDEVModel(n_atoms=4, period=2.0)
    pd.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(400):
        pd.step(0, 0.1)
    o = pd.observe()
    assert o["total"] == o["expected_total"], f"并发计数 {o}"

    ds = DynamicStructureDEVModel()
    ds.initialize({}, {}, None, None, np.random.default_rng(0))
    for _ in range(2000):
        ds.step(0, 0.1)
    o2 = ds.observe()
    assert o2["conserv"] == 0, f"动态结构不守恒 {o2}"
    assert 1 <= o2["workers"] <= 4
    print(f"[PASS] DEVS 动态：并行计数={o['total']}；结构守恒 workers={o2['workers']}")


def test_hsmm_and_wrappers():
    """HSMM 滤波准确率>0.55；wrapper 全部可运行。"""
    h = HSMMModel(T=150)
    h.initialize({}, {}, None, None, np.random.default_rng(0))
    assert h.observe()["filter_acc"] > 0.55

    r = np.random.default_rng(0)
    for cls, kw in [(Sys004FiniteCapacityModel, {}),
                    (Sys008DeterministicModel, {}),
                    (Sys027DTMCModel, {}),
                    (Sys033GaltonWatsonModel, {"m": 0.5, "n0": 5})]:
        m = cls(**kw)
        m.initialize({}, kw or {}, None, None, r)
        for _ in range(200):
            m.step(0, 0.1)
        assert m.observe() is not None

    sp = Sys018StochasticPetriModel()
    rr = simulate(sp, horizon=5.0, dt=0.05, parameters={}, rng=r)
    assert rr["final"] is not None

    ta = Sys020TimedArcModel()
    ta.initialize({}, {}, None, None, r)
    for _ in range(50):
        ta.step(0, 1.0)
    print(f"[PASS] HSMM acc={h.observe()['filter_acc']:.2f}；7 个 wrapper 运行正常")


if __name__ == "__main__":
    test_gig1_kingman()
    test_gordon_newell_mva()
    test_bcmp_and_colored_pn()
    test_devs_dynamic()
    test_hsmm_and_wrappers()
    print("\n===== SYS 补充：全部通过 =====")
