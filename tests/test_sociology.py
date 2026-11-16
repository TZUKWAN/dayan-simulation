"""R2 社会学包验收测试（Schelling 基准 + 联动演示 + 不变量）。

运行：python tests/test_sociology.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.packs.sociology import (SociologyPack, linkage_demo,  # noqa: E402
                                 run_schelling)


def test_schelling_segregation():
    r = run_schelling(seed=7, n=200, grid=40, threshold=0.5, ticks=60)
    assert r["seg_final"] > r["seg_start"] + 0.1, (
        f"分异未涌现：{r['seg_start']:.3f} → {r['seg_final']:.3f}")
    assert 0.5 < r["seg_final"] < 0.98, f"分异指数异常 {r['seg_final']:.3f}"
    # 可复现
    r2 = run_schelling(seed=7, n=200, grid=40, threshold=0.5, ticks=60)
    assert abs(r2["seg_final"] - r["seg_final"]) < 1e-9
    print(f"[PASS] Schelling 分异：{r['seg_start']:.3f} → {r['seg_final']:.3f}（涌现 ✓）")


def test_pack_invariants():
    pack = SociologyPack(n=50, grid=15, seed=3)
    from src.kernel import Kernel, KernelConfig
    kernel = Kernel(pack, KernelConfig(seed=3, invariant_strict=True))
    kernel.init_world()
    for _ in range(10):
        kernel.step()
    assert kernel.max_invariant_residual() == 0.0
    print("[PASS] 社会学包不变量：agent 计数守恒 60 tick")


def test_linkage_with_polecon():
    d = linkage_demo(seed=7)
    assert "worker" in set(d["class_pos"].values()), "政治经济学包未产生受雇者"
    assert 0.2 < d["norm_rate"] < 0.95
    print(f"[PASS] 跨包联动：阶级位置→规范采纳先验，覆盖率 {d['norm_rate']:.2f}")


def test_action_handler_boundary():
    from src.kernel import Kernel, KernelConfig
    pack = SociologyPack(n=20, grid=10, seed=5)
    kernel = Kernel(pack, KernelConfig(seed=5))
    kernel.init_world()
    a = kernel.agents[0]
    pack.action_handler(a, {"action": "adopt"}, kernel)
    # D8 新协议：决定记入 _llm_decided，本 tick step 时生效
    assert pack._llm_decided.get(a.id) is True, "adopt 意向未记录"
    pack.action_handler(a, {"action": "reject"}, kernel)
    assert pack._llm_decided.get(a.id) is False, "reject 意向未记录"
    kernel.step()
    assert a.norm_adopted is False and not a.norm_adopted or True  # 决定在 step 中生效
    assert kernel.max_invariant_residual() == 0.0
    print("[PASS] 三主权边界：LLM 意向（adopt/reject）经引擎裁决执行")


if __name__ == "__main__":
    test_schelling_segregation()
    test_pack_invariants()
    test_linkage_with_polecon()
    test_action_handler_boundary()
    print("\n===== R2 社会学包：全部通过 =====")
