"""T16 跨包正式实验：经济基础 → 上层建筑（共享时钟，YAML 规约）。

设计（v2 设计 §3.2/§3.3 联动接口的正式化——替代 demo 级 linkage_demo）：
- 共享时钟：window w 内 polecon 跑 W ticks → 提取阶级位置/失业名单
  → 社会学包重建（失业/受雇者的规范采纳先验差异化）→ 跑 W ticks
- 传导变量：失业率（经济）→ 规范覆盖率与分异（上层建筑）
- 规约：experiments/scenarios/cross_pack_basis_superstructure.yaml
- 判据：失业率上升的窗口之后，规范采纳的结构性差异（受雇/失业 vs 自营）可测

用法：python experiments/run_cross_pack.py [--windows 4 --window-ticks 30]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig, default_registry  # noqa: E402
from src.packs import create_pack  # noqa: E402
from src.agents.decisions import rule_decision  # noqa: E402
from src.measures.metrics import gini  # noqa: E402


def run_cross_pack(windows: int = 4, window_ticks: int = 30, n: int = 60,
                   seed: int = 7, shock_at_window: int = 2):
    """共享时钟交替：polecon W ticks → 社会学 W ticks，逐窗口推进。"""
    pe = create_pack("政治经济学包", population={"n": n}, institutions={},
                     seed=seed, intervention={})
    k1 = Kernel(pe, KernelConfig(seed=seed, invariant_strict=True))
    k1.init_world()
    soc = create_pack("社会学包", population={"n": n, "grid": 20,
                                              "阈值": 0.4}, seed=seed)
    k2 = Kernel(soc, KernelConfig(seed=seed, invariant_strict=True))
    k2.init_world()

    rows = []
    tick = 0
    for w in range(windows):
        # --- 经济窗：W ticks（窗口 2 起施加需求冲击）---
        if w >= shock_at_window:
            pe.world.params.shock_tick = 0
            pe.world.params.shock_factor = 0.55
        for _ in range(window_ticks):
            for a in k1.agents:
                pe.action_handler(a, pe.rule_decision(a), k1)
            k1.step()
            tick += 1
        pos = pe.world.positions()
        n_unemp = pos["unemployed"] + sum(
            1 for a in k1.agents if a.savings < 3.0)
        gini_v = gini(pe.world.wealth_vector())

        # --- 传导：经济状态 → 社会学规范先验（重建社会学世界）---
        class_pos = {a.id: a.position for a in k1.agents}
        poor = {a.id for a in k1.agents if a.savings < 3.0}
        soc2 = create_pack("社会学包", population={"n": n, "grid": 20,
                                                   "阈值": 0.4}, seed=seed + w)
        k2 = Kernel(soc2, KernelConfig(seed=seed + w, invariant_strict=True))
        k2.init_world()
        for a in k2.agents:
            cp = class_pos.get(a.id)
            # 先验：失业/贫困者更可能采纳"互助规范"（处境→取向，遮蔽措辞）
            if cp in ("worker", "member") or a.id in poor:
                if soc2.rng.rand() < 0.6:
                    a.norm_adopted = True
        for _ in range(window_ticks):
            k2.step()
        norm_rate = sum(a.norm_adopted for a in k2.agents) / n
        # 分异：按经济阶层分组的规范采纳差异（结构对应）
        adopt_worker = [a.norm_adopted for a in k2.agents
                        if class_pos.get(a.id) in ("worker", "member", "unemployed")
                        or a.id in poor]
        adopt_other = [a.norm_adopted for a in k2.agents
                       if not (class_pos.get(a.id) in ("worker", "member", "unemployed")
                               or a.id in poor)]
        gap = (np.mean(adopt_worker) if adopt_worker else 0) - \
              (np.mean(adopt_other) if adopt_other else 0)

        rows.append({"window": w, "tick": tick, "gini": round(gini_v, 3),
                     "n_unemp_proxy": n_unemp, "norm_rate": round(norm_rate, 3),
                     "class_norm_gap": round(float(gap), 3)})
        print(f"[窗 {w}] 失业代理={n_unemp} 基尼={gini_v:.2f} "
              f"规范覆盖率={norm_rate:.2f} 阶层规范差={gap:+.2f}", flush=True)
    return rows


def register_scenario(windows, window_ticks, seed):
    scenario = {
        "scenario": "基础-上层建筑跨包联动",
        "pack": "政治经济学包+社会学包",
        "windows": windows, "window_ticks": window_ticks,
        "measurement_plan": ["gini", "norm_rate", "class_norm_gap"],
        "validity_plan": {"基线": "窗口内对照（冲击前后）", "种子": [seed]},
        "claims_level": {"机制主张": "仅探索（传导为先验注入型）",
                         "趋势主张": "允许"},
    }
    entry = default_registry().register(scenario, author="cross_pack",
                                        tags=["联动", "基础-上层建筑"])
    default_registry().record_experiment(entry.handle)
    return entry


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--windows", type=int, default=4)
    ap.add_argument("--window-ticks", type=int, default=30)
    ap.add_argument("--agents", type=int, default=60)
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()

    rows = run_cross_pack(windows=args.windows, window_ticks=args.window_ticks,
                          n=args.agents, seed=args.seed)
    out = ROOT / "results" / "cross_pack_basis_superstructure"
    out.mkdir(parents=True, exist_ok=True)
    import pandas as pd
    pd.DataFrame(rows).to_csv(out / "trajectory.csv", index=False)

    # 规约登记（T4 联动）
    entry = register_scenario(args.windows, args.window_ticks, args.seed)
    (out / "spec_handle.txt").write_text(entry.cite(), encoding="utf-8")
    print(f"规约登记：{entry.cite()}；结果：{out}")


if __name__ == "__main__":
    main()
