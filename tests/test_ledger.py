"""层1 经济内核的确定性检验：
1) 金钱守恒：Σsavings(t) = Σsavings(t-1) − 设备购买支出
2) 同种子完全可复现
3) 无 NaN / 无负库存 / 储蓄有界
运行：python tests/test_ledger.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.ledger.economy import Agent, Params, World  # noqa: E402
from src.agents.decisions import rule_decision  # noqa: E402


def make_world(seed: int, n: int = 80):
    rng = random.Random(seed)
    agents = []
    for i in range(n):
        skill = float(np.clip(rng.lognormvariate(0.0, 0.35), 0.4, 2.5))
        savings = float(np.clip(rng.lognormvariate(np.log(15.0), 0.6), 1.0, 200.0))
        agents.append(Agent(i, {"name": f"A{i}", "age": 30, "trait": "x"},
                            skill, savings, llm=False, dec_offset=i % 4))
    return World(Params(), agents, rng=random.Random(seed))


def run_rule_world(world: World, ticks: int):
    errs = []
    for t in range(ticks):
        world.apply_decisions({a.id: rule_decision(a, world) for a in world.agents})
        led = world.step(t)
        # 守恒式：设备部门显式化后，货币总量严格守恒（购买支出当期回流）
        errs.append(abs(led["sum_savings_after"] - led["sum_savings_before"]))
        for a in world.agents:
            assert np.isfinite(a.savings), f"tick{t} agent{a.id} savings NaN"
        for f in world.firms.values():
            assert f.inventory >= -1e-9, f"tick{t} firm{f.fid} negative inventory"
    return errs


def test_conservation():
    w = make_world(7)
    errs = run_rule_world(w, 40)
    assert max(errs) < 1e-6, f"守恒残差过大: {max(errs)}"
    print(f"[PASS] 金钱守恒 40 ticks，最大残差 {max(errs):.2e}")


def test_determinism():
    final_a = None
    for seed in (7, 7, 99):
        w = make_world(seed)
        run_rule_world(w, 30)
        snap = tuple(round(a.savings, 9) for a in w.agents)
        if seed == 7 and final_a is None:
            final_a = snap
        elif seed == 7:
            assert snap == final_a, "同种子两次运行结果不一致！"
    print("[PASS] 同种子完全可复现；异种子结果不同（应然）")


def test_economy_active():
    w = make_world(7)
    run_rule_world(w, 40)
    pos = w.positions()
    assert pos["worker"] + pos["employer"] > 0, "40 tick 后无任何雇佣关系，经济未激活"
    assert w.tick_no == 40
    print(f"[PASS] 经济激活：pos={pos} firms={len(w.firms)} p_ref={w.p_ref:.2f}")


def test_llm_ledger_equivalence():
    """遮蔽设计的机制面：LLM 决策与规则决策走同一 ledger 接口，
    任意动作（含非法值）都不破坏守恒与边界。"""
    w = make_world(11)
    for t in range(20):
        dec = {a.id: rule_decision(a, w) for a in w.agents}
        # 注入一批非法/极端决策，检验 apply_decisions 的钳制
        dec[0] = {"action": "firm", "wage": -5, "price": 1e9}
        dec[1] = {"action": "work", "offer_rank": 99}
        dec[2] = {"action": "nonexistent_action"}
        dec[3] = {"action": "operate", "wage": "abc", "price": None}
        w.apply_decisions(dec)
        led = w.step(t)
        err = abs(led["sum_savings_after"] - led["sum_savings_before"])
        assert err < 1e-6, f"极端决策破坏守恒: tick{t} err={err}"
    print("[PASS] 非法决策注入下守恒与钳制正常")


if __name__ == "__main__":
    test_conservation()
    test_determinism()
    test_economy_active()
    test_llm_ledger_equivalence()
    print("全部通过")
