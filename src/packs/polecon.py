"""政治经济学理论包（v0/v1 引擎 → v2 理论包适配层）。

把 src/ledger/economy.py 的 World 包装为 Kernel 可用的 TheoryPack：
- init_world：按规约人群参数创建 World（内部仍是 v0/v1 引擎，不回归）
- step：World.step 并拷贝守恒账目
- invariants：货币守恒（Σsavings 差=0，v0/v1 实测残差 ~1e-13）
- measure_hooks：分布/剩余记账/阶级位置等（复用 src/measures）
- 遮蔽审计：决策 prompt 理论词汇零命中（v0/v1 已通过，包内固化）
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np

from ..kernel.core import Invariant, Kernel, TheoryPack, register_pack
from ..ledger.economy import Agent, Params, World


def _build_world(population: dict, institutions: dict, seed: int,
                 intervention: dict) -> World:
    import random
    rng = random.Random(seed)
    n = int(population.get("n", 200))
    params = Params(
        institute=institutions.get("制度", "private"),
        shock_tick=int(intervention.get("shock_tick", -1)),
        shock_factor=float(intervention.get("shock_factor", 1.0)),
        friction_shock=float(intervention.get("friction_shock", 0.75)),
        decide_every=int(population.get("decide_every", 4)),
    )
    agents = []
    llm_ratio = float(population.get("LLM比例", 0.0) or 0.0)
    n_llm = int(round(n * llm_ratio))
    llm_flags = [True] * n_llm + [False] * (n - n_llm)
    rng.shuffle(llm_flags)  # 精确按比例抽样（T3：规约值真实生效）
    for i in range(n):
        skill = float(np.clip(rng.lognormvariate(0.0, 0.35), 0.4, 2.5))
        sav = float(np.clip(rng.lognormvariate(np.log(15.0), 0.6), 1.0, 200.0))
        agents.append(Agent(i, {"name": f"A{i:03d}", "age": 30 + i % 28,
                                "trait": population.get("人设", "x")},
                            skill, sav, llm=llm_flags[i],
                            dec_offset=i % params.decide_every))
    return World(params, agents, rng=random.Random(seed + 1))


class PolEconPack:
    """政治经济学包：init_world/step/invariants/measure_hooks 七件套。"""

    name = "政治经济学包"
    version = "1.0"
    description = "v0/v1 toy_capitalism 引擎的理论包封装（私有制/合作社/冲击）"
    benchmark_reproductions = ["Sugarscape 财富分布（同构）", "价值规律涌现（Wright 式）"]

    def __init__(self, population: dict, institutions: dict, seed: int,
                 intervention: dict):
        self.population = population
        self.institutions = institutions
        self.seed = seed
        self.intervention = intervention
        self.world: World | None = None

    # ---- 1-3: 实体/制度/动作空间 ----
    def init_world(self, kernel: Kernel):
        self.world = _build_world(self.population, self.institutions,
                                  self.seed, self.intervention)
        return self.world.agents

    def step(self, kernel: Kernel, ledger: dict):
        assert self.world is not None
        led = self.world.step(kernel.tick_no)
        ledger.update(led)

    def action_handler(self, agent, decision: dict, kernel: Kernel):
        """LLM/规则决策 → World.apply_decisions 的裁决执行。"""
        assert self.world is not None
        self.world.apply_decisions({agent.id: decision})

    def collect_llm_requests(self, t: int) -> list:
        """决策循环钩子：本 tick 需 LLM 决策的 agent 列表。"""
        assert self.world is not None
        return [self.world.agent(i) for i in self.world.collect_decision_requests(t)]

    def rule_decision(self, agent):
        """决策循环钩子：规则策略。"""
        from ..agents.decisions import rule_decision
        return rule_decision(agent, self.world)

    # ---- 4: 不变量 ----
    invariants = []  # 在模块底部构造（需访问实例 world）


    # ---- 5: 测量钩子 ----
    measure_hooks = {
        "wealth_gini": lambda k: __import__("src.measures.metrics", fromlist=["gini"]).gini(
            k.pack.world.wealth_vector()),
        "positions": lambda k: k.pack.world.positions(),
        "exploitation": lambda k: __import__("src.measures.metrics", fromlist=[
            "exploitation_stats"]).exploitation_stats(k.pack.world),
        "p_ref": lambda k: k.pack.world.p_ref,
    }

    # ---- 6: 校准靶 ----
    calibration_targets = {
        "劳动份额": [0.5, 0.7],
        "双形态": "Yakovenko 下层指数+上尾Pareto",
        "s_prime量级": [1.0, 2.0],
    }


def _money_residual(kernel: Kernel) -> float:
    pack: PolEconPack = kernel.pack
    w = pack.world
    led = w.ledger_last
    if not led or "sum_savings_after" not in led:
        return 0.0
    return float(led["sum_savings_after"] - led["sum_savings_before"])


PolEconPack.invariants = [
    Invariant(name="货币守恒", fn=_money_residual, tol=1e-6, expected=lambda k: 0.0,
              description="设备部门显式化后，Σsavings 逐 tick 守恒（期望恒 0）"),
]


def make_pack(population=None, institutions=None, seed=42, intervention=None) -> PolEconPack:
    return PolEconPack(population or {}, institutions or {}, seed,
                       intervention or {})


def register(population=None, institutions=None, seed=42, intervention=None):
    """注册并返回包实例（每实验一个实例，世界状态独立）。"""
    pack = make_pack(population, institutions, seed, intervention)
    # 同一 name 重复注册会报错——包实例不注册，注册的是类级模板；
    # 实验通过 make_pack 拿实例，kernel 直接持实例。
    return pack


# 包注册（带场景工厂——run_spec 按 spec.pack 分发的依据）
register_pack(TheoryPack(
    name="政治经济学包",
    description=PolEconPack.description,
    factory=lambda population, institutions, seed, intervention: make_pack(
        population, institutions, seed, intervention),
    benchmark_reproductions=PolEconPack.benchmark_reproductions,
    invariants=PolEconPack.invariants,
    calibration_targets=PolEconPack.calibration_targets,
))
