"""R1 基准复现套件①：Sugarscape 财富分布（Epstein & Axtell 1996）。

自证题（平台纪律：新主张之前先复现经典）：
- 250 个 agent 在 50×50 糖域按视野/代谢觅食
- 自下而上涌现高度偏斜的财富分布（定性靶：与真实财富数据同形态）
运行：python tests/test_benchmarks.py::test_sugarscape 或 python -m pytest
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Invariant, Kernel, KernelConfig, TheoryPack  # noqa: E402
from src.measures.metrics import gini, top_shares  # noqa: E402


class SugarAgent:
    __slots__ = ("id", "wealth", "metabolism", "vision", "x", "y")

    def __init__(self, aid, wealth, metabolism, vision, x, y):
        self.id = aid
        self.wealth = wealth
        self.metabolism = metabolism
        self.vision = vision
        self.x, self.y = x, y


class SugarscapePack:
    """Sugarscape 基准包：七件套声明（无 LLM，纯规则）。"""

    name = "基准·Sugarscape财富分布"
    version = "1.0"
    description = "Epstein & Axtell 1996 财富分布涌现（平台基准复现题）"
    benchmark_reproductions = ["本包即基准题"]
    N = 250
    GRID = 50
    TICKS = 200

    def __init__(self, seed=7):
        self.seed = seed
        self.agents: list[SugarAgent] = []
        self.rng = np.random.RandomState(seed)
        # 双峰糖域（两个富矿）
        self.sugar = np.zeros((self.GRID, self.GRID))
        for i in range(self.GRID):
            for j in range(self.GRID):
                d1 = min(abs(i - 12), self.GRID - abs(i - 12)) + \
                    min(abs(j - 12), self.GRID - abs(j - 12))
                d2 = min(abs(i - 37), self.GRID - abs(i - 37)) + \
                    min(abs(j - 37), self.GRID - abs(j - 37))
                self.sugar[i, j] = max(0, 4 - min(d1, d2)) ** 2

    def init_world(self, kernel):
        rng = self.rng
        self.agents = []
        for i in range(self.N):
            x, y = int(rng.randint(0, self.GRID)), int(rng.randint(0, self.GRID))
            self.agents.append(SugarAgent(
                i, wealth=float(rng.randint(5, 25)),
                metabolism=float(rng.randint(1, 4)),
                vision=float(rng.randint(1, 6)), x=x, y=y))
        return self.agents

    def step(self, kernel, ledger):
        rng = self.rng
        alive = []
        for a in self.agents:
            # 视野内找最甜的格子（含原地）
            best_x, best_y, best_s = a.x, a.y, self.sugar[a.x, a.y]
            for dx in range(-int(a.vision), int(a.vision) + 1):
                for dy in range(-int(a.vision), int(a.vision) + 1):
                    if dx == 0 and dy == 0:
                        continue
                    nx = (a.x + dx) % self.GRID
                    ny = (a.y + dy) % self.GRID
                    if self.sugar[nx, ny] > best_s:
                        best_s, best_x, best_y = self.sugar[nx, ny], nx, ny
            a.x, a.y = best_x, best_y
            a.wealth += self.sugar[a.x, a.y]
            self.sugar[a.x, a.y] = 0.0
            a.wealth -= a.metabolism
            if a.wealth >= 0:
                alive.append(a)
            # 糖再生
        self.sugar = np.minimum(self.sugar + 1.0, self._cap)
        self.agents = alive
        ledger["alive"] = len(alive)

    @property
    def _cap(self):
        if not hasattr(self, "_cap_cache"):
            c = np.zeros((self.GRID, self.GRID))
            for i in range(self.GRID):
                for j in range(self.GRID):
                    d1 = min(abs(i - 12), self.GRID - abs(i - 12)) + \
                        min(abs(j - 12), self.GRID - abs(j - 12))
                    d2 = min(abs(i - 37), self.GRID - abs(i - 37)) + \
                        min(abs(j - 37), self.GRID - abs(j - 37))
                    c[i, j] = max(0, 4 - min(d1, d2)) ** 2
            self._cap_cache = c
        return self._cap_cache

    invariants = []
    measure_hooks = {
        "gini": lambda k: gini([a.wealth for a in k.pack.agents]),
        "top10": lambda k: top_shares([a.wealth for a in k.pack.agents])["top10"],
        "alive": lambda k: len(k.pack.agents),
    }
    calibration_targets = {"形态": "高度偏斜，top10≥0.3（真实财富同形态）"}
    action_handler = None


def run_sugarscape(seed=7, ticks=200):
    pack = SugarscapePack(seed)
    kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
    kernel.init_world()
    for _ in range(ticks):
        kernel.step()
    w = [a.wealth for a in pack.agents]
    return {"alive": len(w), "gini": gini(w), "top10": top_shares(w)["top10"],
            "max": max(w), "median": float(np.median(w))}




# ---- 平台基准登记（T2：基准套件入注册表）----
def _register_benchmark():
    from ..kernel.core import TheoryPack, register_pack
    register_pack(TheoryPack(
        name="基准·Sugarscape财富分布",
        description=SugarscapePack.description,
        invariants=list(getattr(SugarscapePack, "invariants", []) or []),
        calibration_targets=dict(getattr(SugarscapePack, "calibration_targets", {}) or {}),
        benchmark_reproductions=list(getattr(SugarscapePack, "benchmark_reproductions", []) or []),
    ))


_register_benchmark()


if __name__ == "__main__":
    r = run_sugarscape()
    print(f"Sugarscape 200tick: alive={r['alive']} gini={r['gini']:.3f} "
          f"top10={r['top10']:.3f} max={r['max']:.0f} median={r['median']:.1f}")
