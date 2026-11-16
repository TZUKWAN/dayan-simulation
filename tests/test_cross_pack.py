"""T16 跨包正式实验验收：共享时钟、经济→规范传导、规约登记。

判据：
- 4 窗口轨迹完整；冲击窗口（w>=2）后失业代理上升
- 规范采纳的阶层结构差（class_norm_gap）在冲击后窗口可测
- 规约已登记（msim://spec/）
运行：python tests/test_cross_pack.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel.registry import default_registry  # noqa: E402
from experiments.run_cross_pack import (register_scenario,  # noqa: E402
                                        run_cross_pack)


def test_cross_pack_coupling():
    rows = run_cross_pack(windows=4, window_ticks=20, n=60, seed=7,
                          shock_at_window=2)
    assert len(rows) == 4, "窗口数不完整"
    # 冲击后失业代理上升（经济窗传导）
    pre = rows[1]["n_unemp_proxy"]
    post = max(rows[2]["n_unemp_proxy"], rows[3]["n_unemp_proxy"])
    assert post >= pre, f"冲击后失业代理未上升：{pre} → {post}"
    # 上层建筑变量被产出且在界内
    for r in rows:
        assert 0.0 <= r["norm_rate"] <= 1.0
        assert -1.0 <= r["class_norm_gap"] <= 1.0
    # 冲击后窗口存在非零阶层规范差（结构对应可测；方向不预设）
    assert any(abs(r["class_norm_gap"]) > 0.02 for r in rows[2:]), (
        f"冲击后无阶层规范差：{[r['class_norm_gap'] for r in rows]}")
    # 规约登记（直接调用登记函数——与 main() 同路径）
    entry = register_scenario(4, 20, 7)
    e = default_registry().find(keyword="基础-上层建筑")
    assert len(e) >= 1 and entry.n_experiments >= 1, "跨包规约未登记/未计数"
    print(f"[PASS] 跨包联动：失业代理 {pre}→{post}，规范覆盖率轨迹 "
          f"{[r['norm_rate'] for r in rows]}，阶层规范差 "
          f"{[r['class_norm_gap'] for r in rows]}（规约 {entry.cite()}）")


if __name__ == "__main__":
    test_cross_pack_coupling()
    print("\n===== T16 跨包正式实验：通过 =====")
