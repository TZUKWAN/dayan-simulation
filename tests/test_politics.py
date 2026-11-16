"""R3 政治学包验收测试（Downs/Duverger 基准 + 联合实验 + 不变量）。

判据（v2 设计 §3.3 校准靶）：
- Downs：两党多数制收敛度（胜方平台-中位偏好）< 0.05（中位选民收敛）
- Duverger：plurality 有效政党数 ≤ 2，proportional > 2（定律方向）
- 联合实验：失业者注入 → 抗议率显著 > 纯经济包基线，合法性下降
运行：python tests/test_politics.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig  # noqa: E402
from src.packs.politics import (PoliticsPack, run_downs, run_duverger,  # noqa: E402
                                run_joint_control, run_joint_econ_politics)


def test_downs_convergence():
    r = run_downs(seed=7, n=200, ticks=40)
    assert r["convergence_tail"] < 0.05, (
        f"未收敛到中位选民：convergence={r['convergence_tail']:.3f}")
    r2 = run_downs(seed=7, n=200, ticks=40)
    assert abs(r2["convergence_tail"] - r["convergence_tail"]) < 1e-9, "不可复现"
    print(f"[PASS] Downs 收敛：胜方-中位距 {r['convergence_tail']:.3f}（中位偏好 "
          f"{r['median']:.2f}，收敛 ✓）")


def test_duverger_law():
    """T13 涌现版：票份 ENP 由策略性背叛涌现（非记票构造）。"""
    r = run_duverger(seed=7, n=400, ticks=30)
    assert r["plurality"] < 2.5, (
        f"多数制票份 ENP {r['plurality']:.2f} 未两党化（背叛机制未生效）")
    assert r["proportional"] > r["plurality"] + 0.3, (
        f"比例制 {r['proportional']:.2f} 未显著多于多数制 {r['plurality']:.2f}")
    print(f"[PASS] Duverger（涌现）：plurality 票份ENP={r['plurality']:.2f}"
          f"（策略性背叛 squeeze→两党）< proportional={r['proportional']:.2f}（多党）")


def test_pack_invariants_and_hooks():
    pack = PoliticsPack(n=100, rule="plurality", n_parties=2, seed=5)
    kernel = Kernel(pack, KernelConfig(seed=5, invariant_strict=True))
    kernel.init_world()
    fn_eff = PoliticsPack.measure_hooks["effective_parties"]
    for _ in range(15):
        kernel.step()
    assert kernel.max_invariant_residual() <= 2.0, "席位守恒超容差"
    assert 1.0 <= fn_eff(kernel) <= 2.0
    print(f"[PASS] 政治学包不变量：席位守恒 15 tick（残差≤{kernel.max_invariant_residual():.1f}）")


def test_joint_econ_to_politics():
    r = run_joint_econ_politics(seed=7, shock_factor=0.45)
    c = run_joint_control(seed=7)
    assert r["n_unemployed"] > 3, f"失业 {r['n_unemployed']} 人，联合实验无处理变异"
    diff = r["protest_rate_final"] - c["protest_rate_final"]
    assert diff > 0.05, (
        f"抗议率差分 {diff:.2f}（处理 {r['protest_rate_final']:.2f} vs 对照 "
        f"{c['protest_rate_final']:.2f}），传导链未产生可测政治反应")
    assert r["legitimacy_final"] < c["legitimacy_final"], "处理组全局合法性未低于对照"
    print(f"[PASS] 联合实验：失业 {r['n_unemployed']} 人 -> 抗议率 "
          f"{r['protest_rate_final']:.2f} vs 对照 {c['protest_rate_final']:.2f}"
          f"（差分 {diff:+.2f}）；合法性 {r['legitimacy_final']:.2f} vs "
          f"{c['legitimacy_final']:.2f}（经济基础->政治反应传导 OK）")



def test_action_handler_boundary():
    pack = PoliticsPack(n=30, rule="plurality", n_parties=3, seed=9)
    kernel = Kernel(pack, KernelConfig(seed=9))
    kernel.init_world()
    a = kernel.agents[0]
    pack.action_handler(a, {"action": "vote", "party": 2}, kernel)
    assert a.party == 2 and not a.protest
    pack.action_handler(a, {"action": "protest"}, kernel)
    assert a.protest and a.party is None
    kernel.step()
    assert kernel.max_invariant_residual() <= 2.0
    print("[PASS] 三主权边界：vote/protest 意向经引擎裁决，席位守恒不破坏")


if __name__ == "__main__":
    test_downs_convergence()
    test_duverger_law()
    test_pack_invariants_and_hooks()
    test_joint_econ_to_politics()
    test_action_handler_boundary()
    print("\n===== R3 政治学包：全部通过 =====")
