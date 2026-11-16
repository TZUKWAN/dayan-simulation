"""R1 基准复现套件验收测试。

平台纪律：新主张之前先复现经典。本套件常驻回归——任何内核改动后必跑全绿。
判据（定性靶，见各包 calibration_targets）：
- Sugarscape：财富分布高度偏斜（gini>0.4, top10>0.25），存活者显著少于初始
- Axelrod：稳定区域数随时间下降且 >1（地域化而非完全同化）
运行：python tests/test_benchmarks.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.packs.benchmark_sugarscape import run_sugarscape  # noqa: E402
from src.packs.benchmark_axelrod import run_axelrod  # noqa: E402


def test_sugarscape():
    r = run_sugarscape(seed=7, ticks=200)
    assert r["alive"] < 250 * 0.5, f"存活率过高（{r['alive']}/250），分布未分化"
    assert r["gini"] > 0.4, f"gini={r['gini']} 未达偏斜形态"
    assert r["top10"] > 0.25, f"top10={r['top10']} 未达集中形态"
    assert r["max"] > 5 * r["median"], "富者财富未显著拉开"
    # 可复现
    r2 = run_sugarscape(seed=7, ticks=200)
    assert abs(r2["gini"] - r["gini"]) < 1e-9, "同种子不可复现"
    print(f"[PASS] Sugarscape：存活 {r['alive']}/250，gini={r['gini']:.3f}，"
          f"top10={r['top10']:.3f}（高度偏斜 ✓，与真实财富同形态）")


def test_axelrod():
    r = run_axelrod(seed=7, ticks=3000)
    assert r["regions_final"] < r["regions_start"] * 0.7, "区域数未显著下降"
    assert r["regions_final"] > 1, "完全同化（区域数=1），未地域化"
    assert r["distinct_final"] > 1, "完全同质化"
    print(f"[PASS] Axelrod：区域 {r['regions_start']} → {r['regions_final']}，"
          f"不同标签 {r['distinct_final']}（地域化涌现 ✓，非完全同化）")


if __name__ == "__main__":
    test_sugarscape()
    test_axelrod()
    print("\n===== R1 基准复现套件：全部通过 =====")
