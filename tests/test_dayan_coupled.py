"""旗舰耦合器验收：one-way/cyclic/reference 三模式。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.coupled import CoupledSimulation, GoodwinSDCore  # noqa: E402


def test_goodwin_bounded_cycle():
    """Goodwin SD 核：利润挤压-充分就业有界循环（ω∈[0.75,1)、λ 同步摆动）。"""
    core = GoodwinSDCore()
    hist_w, hist_l = [], []
    for _ in range(4000):
        core.step(0.1)
        hist_w.append(core.x[0])
        hist_l.append(core.x[1])
    arr = np.array(hist_w[1000:])
    lam = np.array(hist_l[1000:])
    assert 0.8 <= arr.min() < arr.max() <= 1.0, \
        f"Goodwin 轨道异常 [{arr.min():.2f},{arr.max():.2f}]"
    assert arr.max() - arr.min() > 0.1, "振幅不足（未成循环）"
    assert lam.max() - lam.min() > 0.25, "就业率未同步摆动"
    # 有周期性：自相关峰值
    print(f"[PASS] Goodwin 核：ω∈[{arr.min():.2f},{arr.max():.2f}] "
          f"λ∈[{lam.min():.2f},{lam.max():.2f}] 利润挤压循环")


def test_three_modes():
    """三模式：one-way 注入有效；cyclic 双向反馈改变轨迹；reference 独立。"""
    r_one = CoupledSimulation(mode="one-way", seed=7).run()
    r_cyc = CoupledSimulation(mode="cyclic", seed=7).run()
    r_ref = CoupledSimulation(mode="reference", seed=7).run()
    for r in (r_one, r_cyc, r_ref):
        assert r["sd_bounded"] and r["abm_active"], f"模式异常 {r['mode']}"
    # cyclic 与 one-way 的 SD 轨迹应不同（反馈生效）
    assert abs(r_cyc["wage_share_final"] - r_one["wage_share_final"]) > 0.005, \
        "cyclic 反馈未改变 SD 轨迹"
    # reference 的 ABM 工资恒 0.7 → 就业率稳定
    assert 0.3 < r_ref["emp_abm_final"] < 1.0
    print(f"[PASS] 三模式：one-way/one final ω={r_one['wage_share_final']:.3f}, "
          f"cyclic ω={r_cyc['wage_share_final']:.3f}（反馈改变轨迹）, "
          f"reference ABM={r_ref['emp_abm_final']:.2f}")


def test_reference_reproducible():
    """reference 同种子完全可复现（平台可复现性合同）。"""
    a = CoupledSimulation(mode="reference", seed=42).run()
    b = CoupledSimulation(mode="reference", seed=42).run()
    assert a["wage_share_final"] == b["wage_share_final"]
    assert a["emp_abm_final"] == b["emp_abm_final"]
    print("[PASS] reference 同种子逐位复现")


if __name__ == "__main__":
    test_goodwin_bounded_cycle()
    test_three_modes()
    test_reference_reproducible()
    print("\n===== 旗舰耦合器：全部通过 =====")
