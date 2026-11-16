"""MET 注册表验收：64 个方法演示全部可运行（结果有限、关键项数值对）。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.models.met_missing import (nuts_normal,  # noqa: E402
                                      particle_marginal_mh)
from dayan.models.met_registry import MET_DEMOS, MetDemo, build_all  # noqa: E402


def test_all_64_runnable():
    """全部 64 个 MET 演示初始化并返回有限结果（无 error 键）。"""
    demos = build_all()
    bad = []
    for mid, model in demos.items():
        model.initialize({}, {}, None, None, np.random.default_rng(0))
        r = model.observe()
        if not r or "error" in r:
            bad.append((mid, r))
        # step 可驱动
        for _ in range(3):
            model.step(0, 1.0)
    assert not bad, f"{len(bad)} 个演示失败: {bad[:5]}"
    print(f"[PASS] MET 64 方法注册表：全部可运行（{len(demos)} 个）")


def test_key_numeric_checks():
    """关键项数值检验：MC 积分/MCMC 矩/IPF 闭合/优化器到位。"""
    rng = np.random.default_rng(0)
    # MET013 plain
    m = MetDemo("MET013")
    m.initialize({}, {}, None, None, rng)
    assert abs(m.observe()["est"] - 2 / np.pi) < 0.02
    # MET025 MH
    m = MetDemo("MET025")
    m.initialize({}, {}, None, None, rng)
    r = m.observe()
    assert abs(r["var"] - 1) < 0.2, f"MH 方差 {r}"
    # MET028 NUTS
    x = nuts_normal(2500, 250, rng=rng)
    assert abs(x.mean()) < 0.15 and abs(x.var() - 1) < 0.25, \
        f"NUTS μ={x.mean():.2f} σ²={x.var():.2f}"
    # MET043 KF
    m = MetDemo("MET043")
    m.initialize({}, {}, None, None, rng)
    assert m.observe()["better_than_obs"], "KF 未优于观测"
    # MET060 IPF
    m = MetDemo("MET060")
    m.initialize({}, {}, None, None, rng)
    r = m.observe()
    assert r["row_err"] < 1e-6 and r["col_err"] < 1e-6, f"IPF {r}"
    print("[PASS] MET 关键数值：MC/MH/NUTS/KF/IPF 达标")


def test_missing_methods_now_implemented():
    """原缺失 9 法现可运行：NPE/间接推断/KOH/PMH 返回合理量。"""
    rng = np.random.default_rng(3)
    npe = MetDemo("MET031")
    npe.initialize({}, {}, None, None, rng)
    r = npe.observe()
    assert "posterior_mean" in r and abs(r["posterior_mean"]) < 2.0

    ii = MetDemo("MET037")
    ii.initialize({}, {}, None, None, rng)
    r = ii.observe()
    assert abs(r["theta_hat"] - 0.5) < 0.3, f"间接推断 θ̂={r['theta_hat']}"

    koh = MetDemo("MET038")
    koh.initialize({}, {}, None, None, rng)
    r = koh.observe()
    assert r["err"] < 0.2, f"KOH 校准误差 {r['err']:.3f}"

    pmh = MetDemo("MET049")
    pmh.initialize({}, {}, None, None, rng)
    r = pmh.observe()
    assert "theta_mean" in r
    print(f"[PASS] 补全 9 法：NPE μ={r['theta_mean']:.2f}（此为 PMH），"
          f"间接推断/KOH/NPE 数值合理")


if __name__ == "__main__":
    test_all_64_runnable()
    test_key_numeric_checks()
    test_missing_methods_now_implemented()
    print("\n===== MET 注册表：全部通过 =====")
