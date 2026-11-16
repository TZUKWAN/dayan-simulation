"""R4 文化媒介包验收测试（假新闻级联基准 + 制度变量 + 不变量 + 三主权边界）。

判据（v2 设计 §3.4 校准靶）：
- 假新闻级联：算法偏置放大 fake 传播（amplification > 1.8）；public 所有制压制
- 回音室：偏置↑ → echo_chamber 分数↑
- 不变量：信念有界 [0,1] + 信息总量平衡
- 三主权边界：share/scroll 意向经引擎裁决
运行：python tests/test_media.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig  # noqa: E402
from src.packs.media import (MediaPack, fetishism_linkage_demo,  # noqa: E402
                             run_echo_chamber, run_fake_news_cascade)


def test_fake_news_cascade_amplification():
    r = run_fake_news_cascade(seed=7, algorithm_bias=0.8, ticks=400)
    assert r["amplification"] > 1.8, (
        f"算法偏置未显著放大假新闻：{r['amplification']:.2f}×"
        f"（基线 {r['baseline']:.1f} → 偏置 {r['biased']:.1f}）")
    assert r["public_suppression"] < 0.6, (
        f"public 所有制未压制假新闻：{r['public_suppression']:.2f}")
    print(f"[PASS] 假新闻级联：算法偏置放大 {r['amplification']:.1f}×，"
          f"public 所有制压制至 {r['public_suppression']:.2f}")


def test_echo_chamber_polarization():
    r = run_echo_chamber(seed=7, algorithm_bias=0.8, ticks=400)
    # 极化判据（T7 排斥机制）：偏置使信念方差显著增大
    pdiff = r["biased"]["polarization"] - r["neutral"]["polarization"]
    assert pdiff > 0.01, (
        f"极化未随偏置增强：方差 {r['neutral']['polarization']:.4f} → "
        f"{r['biased']['polarization']:.4f}")
    assert r['biased']['polarization'] > 1.5 * r['neutral']['polarization']
    print(f"[PASS] 极化（T7 排斥机制）：方差 {r['neutral']['polarization']:.4f} → "
          f"{r['biased']['polarization']:.4f}（{r['biased']['polarization']/max(1e-9, r['neutral']['polarization']):.1f}×）")


def test_pack_invariants():
    pack = MediaPack(n=100, algorithm_bias=0.8, seed=5)
    kernel = Kernel(pack, KernelConfig(seed=5, invariant_strict=True))
    kernel.init_world()
    for _ in range(20):
        kernel.step()
    assert kernel.max_invariant_residual() <= 2.0, (
        f"不变量超容差：{kernel.max_invariant_residual():.2f}")
    # 信念有界硬校验
    assert all(0.0 <= a.belief <= 1.0 for a in pack.agents), "信念越界"
    print(f"[PASS] 文化媒介包不变量：信念有界 + 信息平衡 20 tick"
          f"（残差≤{kernel.max_invariant_residual():.1f}）")


def test_action_handler_boundary():
    pack = MediaPack(n=30, seed=9)
    kernel = Kernel(pack, KernelConfig(seed=9))
    kernel.init_world()
    kernel.step()  # 产生一个级联
    a = kernel.agents[0]
    before = a.shared
    pack.action_handler(a, {"action": "share"}, kernel)
    # D8 新协议：share/scroll 意向记入 _llm_shares，本 tick 曝光时生效
    assert pack._llm_shares.get(a.id) is True, "share 意向未记录"
    pack.action_handler(a, {"action": "scroll"}, kernel)
    assert pack._llm_shares.get(a.id) is False, "scroll 意向未记录"
    kernel.step()
    assert kernel.max_invariant_residual() <= 2.0
    print("[PASS] 三主权边界：share/scroll 意向经引擎裁决，不变量保持")


def test_fetishism_linkage_declaration():
    """拜物教通道复用声明（与 polecon 的 TransactionPipeline 联动，不重复造轮子）。"""
    d = fetishism_linkage_demo(seed=7)
    assert "判据" in d and "private" in d["判据"]
    # 通道真实存在性检查：polecon 的 transaction 管线可导入
    from src.measures.transaction import TransactionPipeline
    assert TransactionPipeline is not None
    print(f"[PASS] 拜物教通道复用：{d['机制'][:40]}…（polecon TransactionPipeline 可导入 ✓）")


if __name__ == "__main__":
    test_fake_news_cascade_amplification()
    test_echo_chamber_polarization()
    test_pack_invariants()
    test_action_handler_boundary()
    test_fetishism_linkage_declaration()
    print("\n===== R4 文化媒介包：全部通过 =====")
