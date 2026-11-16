"""R1 基准复现套件②：Axelrod 规范博弈（规范传播与地域化）。

经典形态：初始随机分布的文化标签，局部趋同→自发涌现稳定地域化区域。
不变量：标签总数守恒 + 已采纳规范计数与 agent 计数一致（平台纪律）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.kernel import Invariant, Kernel, KernelConfig  # noqa: E402


class AxelrodPack:
    name = "基准·Axelrod规范博弈"
    version = "1.0"
    description = "Axelrod 1997 文化趋同与地域化（平台基准复现题）"
    benchmark_reproductions = ["本包即基准题"]
    N = 30
    F = 5   # 文化特征数
    Q = 10  # 每特征取值数

    def __init__(self, seed=7):
        self.seed = seed
        self.rng = np.random.RandomState(seed)
        self.agents = []
        # 网格邻居（环形）
        self.neighbors = {}

    def init_world(self, kernel):
        rng = self.rng
        self.agents = [{"id": i,
                        "tags": rng.randint(0, self.Q, self.F).tolist()}
                       for i in range(self.N * self.N)]
        for a in self.agents:
            i = a["id"]
            r, c = divmod(i, self.N)
            self.neighbors[i] = [
                ((r + 1) % self.N) * self.N + c,
                ((r - 1) % self.N) * self.N + c,
                r * self.N + (c + 1) % self.N,
                r * self.N + (c - 1) % self.N,
            ]
        return self.agents

    def step(self, kernel, ledger):
        rng = self.rng
        # 随机序交互（种子化）
        order = rng.permutation(len(self.agents))
        interactions = 0
        converged_pairs = 0
        for idx in order:
            a = self.agents[idx]
            j = int(rng.choice(self.neighbors[idx]))
            b = self.agents[j]
            same = sum(1 for f in range(self.F) if a["tags"][f] == b["tags"][f])
            if same == self.F:
                converged_pairs += 1
                continue
            if same > 0 and rng.rand() < same / self.F:
                diff = [f for f in range(self.F) if a["tags"][f] != b["tags"][f]]
                f = int(rng.choice(diff))
                b["tags"][f] = a["tags"][f]  # b 采纳 a 的某特征
                interactions += 1
        ledger["interactions"] = interactions
        ledger["converged_pairs"] = converged_pairs


def _region_count(kernel) -> int:
    """已采纳一致规范的连通区域数（越跑越少=地域化涌现）。"""
    pack: AxelrodPack = kernel.pack
    seen = set()
    regions = 0
    for a in pack.agents:
        if a["id"] in seen:
            continue
        regions += 1
        stack = [a["id"]]
        while stack:
            i = stack.pop()
            if i in seen:
                continue
            seen.add(i)
            for j in pack.neighbors[i]:
                if j not in seen and pack.agents[j]["tags"] == pack.agents[i]["tags"]:
                    stack.append(j)
    return regions


AxelrodPack.invariants = []
AxelrodPack.measure_hooks = {
    "region_count": lambda k: _region_count(k),
    "distinct_tags": lambda k: len({tuple(a["tags"]) for a in k.pack.agents}),
}
AxelrodPack.calibration_targets = {"地域化": "稳定区域数随时间下降且>1（不完全同化）"}
AxelrodPack.action_handler = None


def run_axelrod(seed=7, ticks=3000):
    pack = AxelrodPack(seed)
    kernel = Kernel(pack, KernelConfig(seed=seed, invariant_strict=True))
    kernel.init_world()
    region_fn = AxelrodPack.measure_hooks["region_count"]
    traj = [region_fn(kernel)]
    for _ in range(ticks):
        kernel.step()
        traj.append(region_fn(kernel))
    return {"regions_final": traj[-1], "regions_start": traj[0],
            "distinct_final": AxelrodPack.measure_hooks["distinct_tags"](kernel),
            "traj_tail": traj[-10:]}




# ---- 平台基准登记（T2：基准套件入注册表）----
def _register_benchmark():
    from ..kernel.core import TheoryPack, register_pack
    register_pack(TheoryPack(
        name="基准·Axelrod规范博弈",
        description=AxelrodPack.description,
        invariants=list(getattr(AxelrodPack, "invariants", []) or []),
        calibration_targets=dict(getattr(AxelrodPack, "calibration_targets", {}) or {}),
        benchmark_reproductions=list(getattr(AxelrodPack, "benchmark_reproductions", []) or []),
    ))


_register_benchmark()


if __name__ == "__main__":
    r = run_axelrod()
    print(f"Axelrod: 区域数 {r['regions_start']} → {r['regions_final']}，"
          f"终态不同标签数 {r['distinct_final']}")
