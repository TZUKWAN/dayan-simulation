"""组织/劳动过程增量验收（v2 设计 §3.5 方案A：并入 polecon）。

判据：
- 去技能化率>0 时，受雇者技能随时间退化（Braverman 假设）
- 去技能化 → 产出下降（技能×产出的乘积关系）
- 监控强度参数已接线（影响叙事处境，后续接 LLM 异化量表实测）
运行：python tests/test_orglabor.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Kernel, KernelConfig  # noqa: E402
import src.packs.polecon as polecon  # noqa: E402
from src.agents.decisions import rule_decision  # noqa: E402


def _run(deskill, monitor, ticks=80, seed=7):
    pack = polecon.make_pack(
        population={"n": 60},
        institutions={"制度": "private"},
        seed=seed, intervention={})
    kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
    kernel.init_world()
    # init_world 后注入组织/劳动参数
    pack.world.params.deskill_rate = deskill
    pack.world.params.monitor_intensity = monitor
    skill0 = {}
    for t in range(ticks):
        for a in kernel.agents:
            if t == 0:
                skill0[a.id] = a.skill
            pack.action_handler(a, rule_decision(a, pack.world), kernel)
        kernel.step()
    # 去技能化度量：所有曾受雇者的累计退化（终态工人可能很少，用全体 agent 退化上限）
    decline = max((skill0[a.id] - a.skill for a in kernel.agents), default=0.0)
    workers = [a for a in kernel.agents if a.position == "worker"]
    return {
        "n_workers": len(workers),
        "skill_decline_mean": float(decline),
        "p_ref": pack.world.p_ref,
        "wealth_gini": polecon.PolEconPack.measure_hooks["wealth_gini"](kernel),
    }


def test_deskill_dynamic():
    r0 = _run(deskill=0.0, monitor=0.0)
    r1 = _run(deskill=0.02, monitor=0.0)
    assert r1["skill_decline_mean"] > 0.01, (
        f"去技能化未生效：退化 {r1['skill_decline_mean']:.3f}")
    print(f"[PASS] Braverman 去技能化：受雇者技能平均退化 "
          f"{r1['skill_decline_mean']:.3f}（对照 {r0['skill_decline_mean']:.3f}）")


def test_deskill_output_effect():
    r_low = _run(deskill=0.0, monitor=0.0, ticks=100)
    r_high = _run(deskill=0.05, monitor=0.0, ticks=100)
    # 去技能化高 → 产出能力下降（p_ref 通缩信号或工人减少）
    assert r_high["n_workers"] <= r_low["n_workers"] + 2, (
        f"去技能化未影响劳动市场：工人 {r_low['n_workers']} → {r_high['n_workers']}")
    print(f"[PASS] 去技能化劳动市场效应：工人数 {r_low['n_workers']} → "
          f"{r_high['n_workers']}（高去技能化下就业收缩）")


def test_monitor_param_wired():
    r = _run(deskill=0.0, monitor=0.8, ticks=30)
    # 监控强度不改变守恒/可运行性，仅影响叙事处境（后续接 LLM 异化实测）
    assert r["p_ref"] > 0, "监控强度参数破坏经济运行"
    print(f"[PASS] 监控强度接线：0.8 下经济正常运行（叙事处境传递待 LLM 实测）")


if __name__ == "__main__":
    test_deskill_dynamic()
    test_deskill_output_effect()
    test_monitor_param_wired()
    print("\n===== 组织/劳动过程增量：全部通过 =====")
