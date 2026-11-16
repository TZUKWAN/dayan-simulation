"""层0 核心运行时（学科中立内核）。

职责（v2 设计 §2）：
- 世界状态与事件溯源：一切状态变更经由 apply(events)，可回放、可审计
- 种子纪律：世界与包共享同一 Random，可比特级复现
- 不变量校验器：每 tick 后逐条执行包声明的不变量，超标即中止
- 全量日志：JSONL 事件流；响应缓存在认知层（层2）配置

设计要点（从 v0/v1 教训抽象）：
- 内核**不 import 任何 LLM 代码、不含任何学科概念**；
- 理论包通过注册表注入实体/制度/不变量/测量钩子；
- LLM 只发"意向"，由包提供的 action_handler 裁决执行（三主权边界·决策1）。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np


@dataclass
class Invariant:
    """学科不变量：每 tick 后校验，residual>tol 即中止。

    expected: 期望值函数（稳态值，如守恒量=0、席位=1）。
    提供时零副作用捕获（无静默 tick）；缺省时回退为基线捕获
    （init_world 后跑一个静默 tick 取值——有隐含状态突变，包应避免依赖）。
    """
    name: str
    fn: Callable[["Kernel"], float]   # 返回实测值（与 expected 比对）
    tol: float = 1e-6
    description: str = ""
    expected: Optional[Callable[["Kernel"], float]] = None


@dataclass
class DivergenceWatch:
    """发散监测（v2 设计·决策5 内建件）：指标越限并持续 patience 期 → 记录。

    fn(kernel)->float；direction: above=越上限 / below=破下限。
    """
    name: str
    fn: Callable[[Kernel], float]
    threshold: float
    direction: str = "above"
    patience: int = 10


@dataclass
class KernelConfig:
    seed: int = 42
    log_path: Optional[Path] = None      # 事件流 JSONL
    cache_path: Optional[Path] = None    # LLM 响应缓存
    invariant_strict: bool = True        # True=残差超标即抛异常；False=只记录


class Kernel:
    """学科中立的世界运行时。理论包通过 pack 参数注入。"""

    def __init__(self, pack, config: KernelConfig | None = None):
        import random as _random
        self.pack = pack
        self.config = config or KernelConfig()
        self.rng = _random.Random(self.config.seed)
        self.tick_no = 0
        self.invariants: list[Invariant] = list(pack.invariants)
        self.invariant_log: list[dict] = []
        self.agents: list[Any] = []        # 包定义的实体（透传）
        # 事件溯源：apply 的每个事件 append 到 _events
        self._events: list[dict] = []
        # 不变量快照基准（在包 init_world 后由 capture_baseline 捕获）
        self._baseline: dict[str, float] = {}
        # 发散监测（T9）
        self.divergence_watches: list[DivergenceWatch] = []
        self._div_streak: dict[str, int] = {}
        self.divergences: dict[str, int] = {}  # name -> 触发 tick

    # ---------- 生命周期 ----------
    def init_world(self):
        """委托包初始化世界（创建 agents/网络/制度状态），随后捕获不变量基准。"""
        self.agents = self.pack.init_world(self)
        self.capture_baseline()
        self.log_event("init", {"pack": self.pack.name,
                                "n_agents": len(self.agents)})

    def add_divergence_watch(self, name: str, fn, threshold: float,
                             direction: str = "above", patience: int = 10):
        self.divergence_watches.append(DivergenceWatch(
            name, fn, threshold, direction, patience))

    def _check_divergences(self):
        for w in self.divergence_watches:
            if w.name in self.divergences:
                continue
            try:
                val = float(w.fn(self))
            except Exception:
                self._div_streak[w.name] = 0
                continue
            hit = val > w.threshold if w.direction == "above" else val < w.threshold
            self._div_streak[w.name] = self._div_streak.get(w.name, 0) + 1 if hit else 0
            if self._div_streak[w.name] >= w.patience:
                self.divergences[w.name] = self.tick_no
                self.log_event("divergence", {"name": w.name,
                                              "value": f"{val:.4f}",
                                              "threshold": w.threshold})

    def capture_baseline(self):
        """捕获不变量基准（T12）。

        全部不变量提供 expected 时：零副作用，直接记期望值；
        否则回退旧行为（跑一个静默 tick 取值——有隐含状态突变，
        init_world 后的世界已是 tick 1 状态，包与测试须知）。
        """
        needs_warm = any(inv.expected is None for inv in self.invariants)
        if needs_warm and self.invariants:
            try:
                self.pack.step(self, {})
            except Exception:
                pass
        for inv in self.invariants:
            try:
                if inv.expected is not None:
                    self._baseline[inv.name] = float(inv.expected(self))
                else:
                    self._baseline[inv.name] = float(inv.fn(self))
            except Exception:
                self._baseline[inv.name] = 0.0

    # ---------- 事件 ----------
    def log_event(self, kind: str, payload: dict):
        rec = {"tick": self.tick_no, "t": time.time(), "kind": kind, **payload}
        self._events.append(rec)
        if self.config.log_path:
            self.config.log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config.log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def replay_events(self) -> list[dict]:
        return list(self._events)

    # ---------- 主循环 ----------
    def step(self) -> dict:
        """一个 tick：决策注入 → 包执行 → 不变量校验 → 记账。"""
        ledger = {"tick": self.tick_no}
        self.pack.step(self, ledger)      # 包驱动的全部状态转移（确定性）
        self.check_invariants()
        self._check_divergences()
        self.tick_no += 1
        return ledger

    def check_invariants(self):
        for inv in self.invariants:
            try:
                expected = (float(inv.expected(self))
                            if inv.expected is not None
                            else self._baseline.get(inv.name, 0.0))
                residual = abs(float(inv.fn(self)) - expected)
            except Exception as e:  # noqa: BLE001
                residual = float("inf")
                err = str(e)
            else:
                err = ""
            self.invariant_log.append({"tick": self.tick_no, "name": inv.name,
                                       "residual": residual, "err": err})
            self.log_event("invariant", {"name": inv.name,
                                         "residual": f"{residual:.3e}"})
            if residual > inv.tol and self.config.invariant_strict:
                raise AssertionError(
                    f"不变量 {inv.name} 残差 {residual:.3e} 超容差 {inv.tol}"
                    f"（tick {self.tick_no}）{err}")

    def max_invariant_residual(self) -> float:
        if not self.invariant_log:
            return 0.0
        return max(r["residual"] for r in self.invariant_log)


@dataclass
class TheoryPack:
    """理论包七件套（v2 设计·决策3）。空包骨架可注册即通过验收。

    factory: 场景工厂 create_pack(population, institutions, seed, intervention) -> pack 实例。
    有 factory 的包才能被场景规约（run_spec）实例化。
    """
    name: str
    version: str = "0.1"
    description: str = ""
    factory: Optional[Callable[[dict, dict, int, dict], Any]] = None
    # 1-3: 实体/制度/动作空间
    init_world: Callable[[Kernel], list] = lambda k: []
    step: Callable[[Kernel, dict], None] = lambda k, ledger: None
    action_handler: Optional[Callable[[Any, dict, Kernel], None]] = None
    # 4: 不变量（可空，但马理论等包必填）
    invariants: list[Invariant] = field(default_factory=list)
    # 5: 测量钩子（引擎提供，包注册）
    measure_hooks: dict[str, Callable[[Kernel], Any]] = field(default_factory=dict)
    # 6: 校准靶（声明）
    calibration_targets: dict[str, Any] = field(default_factory=dict)
    # 7: 基准复现题（本包自证）
    benchmark_reproductions: list[str] = field(default_factory=list)


# ---------- 注册表 ----------
_REGISTRY: dict[str, TheoryPack] = {}


def register_pack(pack: TheoryPack) -> None:
    # 幂等覆盖：模块可能被双重导入（python -m 场景 __main__ 与包路径各一次）。
    # 注册表是按名字键的配置，后注册覆盖先注册。
    _REGISTRY[pack.name] = pack


def get_pack(name: str) -> TheoryPack:
    if name not in _REGISTRY:
        raise KeyError(f"未注册的理论包：{name}（已注册：{sorted(_REGISTRY)}）")
    return _REGISTRY[name]


def list_packs() -> list[str]:
    return sorted(_REGISTRY)
