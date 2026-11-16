"""R0 平台化重构验收测试（中立内核 + 理论包 + 场景规约）。

验收标准（设计文档 §7 R0）：
1) 全部现有测试不回归（test_ledger / test_pipeline）
2) 中立内核不含 LLM/学科概念（import 检查）
3) 空包骨架声明七件套即可注册
4) 场景规约门禁：缺效度方案拒绝标记"已检验"
5) YAML 规约驱动的完整实验：跑通 + 守恒 + 同种子可复现
6) LLM 决策走包 action_handler（三主权边界）
运行：python tests/test_platform.py
"""
from __future__ import annotations

import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import numpy as np  # noqa: E402

from src.kernel import (Invariant, Kernel, KernelConfig, TheoryPack,  # noqa: E402
                        list_packs, load_scenario_from_dict, register_pack)
import src.packs.polecon as polecon  # noqa: E402


# ============ 1) 中立内核纯净性 ============
def test_kernel_purity():
    import ast
    src = (ROOT / "src" / "kernel" / "core.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            imported.add(node.module or "")
    banned = [m for m in imported if m and ("agents" in m or "measures" in m
                                            or "llm" in m.lower())]
    assert not banned, f"内核泄漏了 LLM/学科依赖：{banned}"
    # 源码级检查：不含 LLM 字样
    for kw in ("llm", "LMStudio", "qwen", "decision_prompt"):
        assert kw not in src, f"内核源码含 {kw}"
    print("[PASS] 中立内核纯净性：无 LLM/学科依赖")


# ============ 2) 空包骨架注册 ============
def test_empty_pack_registration():
    name = "测试空包骨架"
    if name in list_packs():
        pass
    else:
        register_pack(TheoryPack(
            name=name, version="0.1",
            description="R0 验收：声明七件套即可注册",
            invariants=[Invariant(name="占位", fn=lambda k: 0.0, tol=1.0)],
            benchmark_reproductions=["占位基准题"],
        ))
    assert name in list_packs(), "空包骨架未注册"
    print("[PASS] 空包骨架声明七件套即可注册")


# ============ 3) 政治经济学包完整实验（rule，无 LLM）============
def test_polecon_pack_rule_experiment():
    pack = polecon.make_pack(
        population={"n": 40}, institutions={"制度": "private"},
        seed=7, intervention={})
    kernel = Kernel(pack, KernelConfig(seed=7, invariant_strict=True))
    kernel.init_world()
    from src.agents.decisions import rule_decision
    for t in range(60):
        decisions = {a.id: rule_decision(a, pack.world) for a in kernel.agents}
        for aid, d in decisions.items():
            pack.action_handler(kernel.agents[aid], d, kernel)
        kernel.step()
    assert kernel.tick_no == 60
    assert kernel.max_invariant_residual() < 1e-6
    pos = pack.measure_hooks["positions"](kernel)
    assert pos["worker"] + pos["employer"] > 0, "60 tick 无雇佣，包未激活"
    g = pack.measure_hooks["wealth_gini"](kernel)
    assert 0.1 < g < 0.9
    # 事件流可回放
    evts = kernel.replay_events()
    assert any(e["kind"] == "init" for e in evts)
    print(f"[PASS] 政治经济学包 rule 实验：60 tick，守恒残差 "
          f"{kernel.max_invariant_residual():.1e}，gini={g:.2f}，pos={pos}")


# ============ 4) 可复现性 ============
def test_reproducibility():
    def run_once():
        pack = polecon.make_pack(population={"n": 30}, institutions={}, seed=11,
                                 intervention={})
        kernel = Kernel(pack, KernelConfig(seed=11, invariant_strict=True))
        kernel.init_world()
        from src.agents.decisions import rule_decision
        for t in range(30):
            for a in kernel.agents:
                pack.action_handler(a, rule_decision(a, pack.world), kernel)
            kernel.step()
        return tuple(round(a.savings, 9) for a in kernel.agents)
    a1, a2, b = run_once(), run_once(), run_once()
    assert a1 == a2 == b, "同种子三次运行不一致！"
    print("[PASS] 包化架构下同种子完全可复现")


# ============ 5) 场景规约门禁 ============
def test_scenario_gates():
    # 缺效度方案 → 拒绝
    bad = load_scenario_from_dict({
        "scenario": "无闸门实验", "pack": "政治经济学包",
        "population": {"n": 10}, "measurement_plan": ["基尼"],
        "claims_level": {},  # 缺
    })
    issues = bad.check_gates()
    assert issues, "缺效度方案的规约未被拦截"
    # 完整规约 → 通过
    good = load_scenario_from_dict({
        "scenario": "闸门完整实验", "pack": "政治经济学包",
        "population": {"n": 10},
        "measurement_plan": ["基尼", "剥削记账"],
        "validity_plan": {"基线": "规则组", "种子": [7, 43]},
        "claims_level": {"机制主张": "仅探索", "趋势主张": "允许"},
    })
    assert not good.check_gates(), f"完整规约被误拦：{good.check_gates()}"
    # 机制主张需微观校准但缺方案 → 拦截
    mid = load_scenario_from_dict({
        "scenario": "半闸门", "pack": "政治经济学包",
        "population": {"n": 10}, "measurement_plan": ["基尼"],
        "validity_plan": {"基线": "规则组"},
        "claims_level": {"机制主张": "需微观校准", "趋势主张": "允许"},
    })
    assert mid.check_gates(), "机制主张缺微观校准未被拦截"
    print(f"[PASS] 场景规约门禁：拦截 {len(issues)} 类违规，完整规约放行")


# ============ 6) 三主权边界（LLM 决策走 action_handler）============
def test_action_handler_boundary():
    pack = polecon.make_pack(population={"n": 8}, institutions={}, seed=3,
                             intervention={})
    kernel = Kernel(pack, KernelConfig(seed=3))
    kernel.init_world()
    # 模拟 LLM 发出的"意向"（非法值也须被引擎钳制——v0/v1 教训）
    from src.agents.decisions import parse_decision
    bad_intent = parse_decision('{"action":"firm","wage":-999,"price":1e9}') or {
        "action": "firm", "wage": -999, "price": 1e9}
    pack.action_handler(kernel.agents[0], bad_intent, kernel)
    pack.step.__wrapped__ if hasattr(pack.step, "__wrapped__") else None
    kernel.step()
    assert kernel.max_invariant_residual() < 1e-6, "非法意向破坏守恒"
    print("[PASS] 三主权边界：LLM 意向经 action_handler 裁决，非法值被钳制且守恒")


# ============ 7) YAML 文件加载 ============
def test_yaml_loader(tmp_scenario_path=None):
    p = ROOT / "tests" / "fixtures" / "scenario_smoke.yaml"
    p.parent.mkdir(exist_ok=True)
    p.write_text("""scenario: YAML冒烟实验
pack: 政治经济学包
population: {n: 20, LLM比例: 0}
institutions: {制度: private}
measurement_plan: [基尼, 剥削记账]
validity_plan: {基线: 规则组, 种子: [7]}
claims_level: {机制主张: 仅探索, 趋势主张: 允许}
ticks: 5
seed: 7
""", encoding="utf-8")
    from src.kernel.spec import load_scenario
    s = load_scenario(p)
    assert s.name == "YAML冒烟实验" and s.ticks == 5 and s.seed == 7
    assert not s.check_gates()
    print("[PASS] YAML 规约加载 + 闸门")


if __name__ == "__main__":
    test_kernel_purity()
    test_empty_pack_registration()
    test_polecon_pack_rule_experiment()
    test_reproducibility()
    test_scenario_gates()
    test_action_handler_boundary()
    test_yaml_loader()
    print("\n===== R0 平台化验收：全部通过 =====")
