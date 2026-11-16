"""Wave-2 目录模型（每个对应 DAYAN 目录 ID，带解析基准）。

- ECO015 Solow–Swan 增长（稳态 k* 解析）
- NET052 SIS 地方病均衡（I* = 1-1/R0）
- BEH020 选民模型（共识概率=初始份额）
- BEH024 Galam 局部多数（多数侧收敛）
- NET074 Bass 创新扩散（解析 F(t)）
- BEH082 复制动态（鹰鸽混合均衡）
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class SolowModel(DayanModel):
    """Solow–Swan（ODE 人均形式，A=1, n=0）：dk/dt = s·k^α − δ·k。
    稳态 k* = (s/δ)^{1/(1-α)}（解析）。"""

    model_id = "ECO015"
    clock_type = "ode"

    def __init__(self, s=0.25, alpha=0.3, delta=0.05, k0=1.0):
        self.s, self.alpha, self.delta = s, alpha, delta
        self.x = np.array([k0])

    def initialize(self, context, parameters, population, topology, rng):
        self.s = parameters.get("s", self.s)
        self.alpha = parameters.get("alpha", self.alpha)
        self.delta = parameters.get("delta", self.delta)
        self.x = np.array([parameters.get("k0", 1.0)])

    def derivatives(self, t, x):
        k = max(x[0], 1e-12)
        return np.array([self.s * k ** self.alpha - self.delta * k])

    def observe(self):
        return {"k": float(self.x[0]),
                "k_star": float((self.s / self.delta) ** (1 / (1 - self.alpha)))}

    def validate_state(self):
        return [] if self.x[0] > 0 else ["k≤0"]


class SISModel(DayanModel):
    """SIS 可重复感染（ODE）：地方病均衡 I* = 1 − 1/R0（占比）。"""

    model_id = "NET052"
    clock_type = "ode"

    def __init__(self, beta=0.5, gamma=0.2, i0=0.1, N=1.0):
        self.beta, self.gamma, self.i0, self.N = beta, gamma, i0, N
        self.x = np.array([i0 * N])

    def initialize(self, context, parameters, population, topology, rng):
        self.beta = parameters.get("beta", self.beta)
        self.gamma = parameters.get("gamma", self.gamma)
        self.i0 = parameters.get("i0", self.i0)
        self.N = parameters.get("N", self.N)
        self.x = np.array([self.i0 * self.N])

    def derivatives(self, t, x):
        I = x[0]
        S = self.N - I
        inf = self.beta * I * S / self.N
        return np.array([inf - self.gamma * I])

    def observe(self):
        return {"I": float(self.x[0]),
                "I_frac": float(self.x[0] / self.N),
                "I_star": float(1 - self.gamma / self.beta)}

    def validate_state(self):
        return [] if self.x[0] >= 0 else ["I<0"]


class VoterModel(DayanModel):
    """选民模型（BEH020，异步随机对、完全图）。共识概率=初始 1 份额（解析）。"""

    model_id = "BEH020"
    clock_type = "fixed_step"

    def __init__(self, n=100, frac1_0=0.4, seed=0):
        self.n, self.frac1_0, self.seed = n, frac1_0, seed
        self.opinions = np.zeros(n)
        self.rng = np.random.default_rng(seed)
        self.consensus = None

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        self.frac1_0 = parameters.get("frac1_0", self.frac1_0)
        self.rng = rng
        self.opinions = (rng.random(self.n) < self.frac1_0).astype(float)
        self.consensus = None

    def step(self, t, dt):
        if self.consensus is not None:
            return
        i, j = self.rng.integers(0, self.n, 2)
        while j == i:
            j = self.rng.integers(0, self.n)
        self.opinions[i] = self.opinions[j]  # 异步：立即影响
        u = np.unique(self.opinions)
        if len(u) == 1:
            self.consensus = float(u[0])

    def observe(self):
        frac1 = float(self.opinions.mean())
        return {"frac1": frac1,
                "consensus": self.consensus,
                "consensus_value": self.consensus}


VOTER_RECORD = {"model_id": "BEH020", "name": "选民模型",
                "reference_cases": ["共识值期望=初始1份额"]}


class BassModel(DayanModel):
    """Bass 创新扩散（NET074，ODE）。
    解析：F(t) = (1 − e^{−(p+q)t}) / (1 + (q/p)·e^{−(p+q)t})。"""

    model_id = "NET074"
    clock_type = "ode"

    def __init__(self, p=0.03, q=0.38, m=1.0):
        self.p, self.q, self.m = p, q, m
        self.x = np.array([p * m])

    def initialize(self, context, parameters, population, topology, rng):
        self.p = parameters.get("p", self.p)
        self.q = parameters.get("q", self.q)
        self.m = parameters.get("m", self.m)
        self.x = np.array([self.p * self.m])

    def derivatives(self, t, x):
        A = x[0]
        remain = self.m - A
        adopt = (self.p + self.q * A / self.m) * remain
        return np.array([adopt])

    def observe(self):
        t_equiv = None
        return {"adopted": float(self.x[0]),
                "frac": float(self.x[0] / self.m)}


BASS_RECORD = {"model_id": "NET074", "name": "Bass 创新扩散",
               "reference_cases": ["F(t) 解析式"]}


def replicator_hawk_dove(V=4.0, C=6.0, x0=0.9, steps=2000, dt=0.01):
    """复制动态收敛到鹰鸽混合均衡 x_H = V/C（BEH082）。"""
    A = np.array([[(V - C) / 2.0, V], [0.0, V / 2.0]])
    x = np.array([x0, 1 - x0])
    for _ in range(steps):
        fit = A @ x
        avg = float(x @ fit)
        x = x + dt * x * (fit - avg)
        x = np.clip(x, 0.0, None)
        x = x / x.sum()
    return x
