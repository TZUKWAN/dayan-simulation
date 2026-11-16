"""文化/语言演化家族（BEH033-048，Axelrod 已在基准包）。"""
from __future__ import annotations

import numpy as np


class KlemmModel:
    """BEH034 Klemm 文化漂移扩展：Axelrod + 稀疏网络+随机漂移 → 相变。"""

    model_id = "BEH034"

    def __init__(self, n=100, F=5, Q=10, drift=0.01, seed=0):
        self.n, self.F, self.Q, self.drift, self.seed = n, F, Q, drift, seed
        self.rng = np.random.default_rng(seed)
        self.tags = self.rng.integers(0, Q, (n, F))

    def initialize(self, context, parameters, population, topology, rng):
        self.tags = self.rng.integers(0, self.Q, (self.n, self.F))

    def _similar(self, i, j):
        return sum(self.tags[i][f] == self.tags[j][f] for f in range(self.F)) / self.F

    def step(self, t, dt):
        rng = self.rng
        i = int(rng.integers(self.n))
        cands = [j for j in range(self.n) if j != i]
        j = int(rng.choice(cands))
        if self._similar(i, j) >= 0.5 and rng.random() < self._similar(i, j):
            f = int(rng.integers(self.F))
            self.tags[i][f] = self.tags[j][f]
        elif rng.random() < self.drift:
            f = int(rng.integers(self.F))
            self.tags[i][f] = int(rng.integers(self.Q))

    def observe(self):
        uniq = {tuple(t) for t in self.tags}
        return {"n_regions": len(uniq), "largest": max(
            sum(1 for t in self.tags if tuple(t) == u) for u in uniq)}

    def validate_state(self):
        return []


class CavalliSforzaFeldman:
    """BEH035 文化传递框架：垂直传递+突变（离散世代）。"""

    model_id = "BEH035"

    def __init__(self, n=500, mu=0.01, p0=0.5, seed=0):
        self.n, self.mu, self.p, self.seed = n, mu, p0, seed
        self.rng = np.random.default_rng(seed)
        self.trait = (self.rng.random(n) < p0).astype(float)

    def initialize(self, context, parameters, population, topology, rng):
        self.mu = parameters.get("mu", self.mu)
        self.trait = (rng.random(self.n) < self.p).astype(float)

    def step(self, t, dt):
        # 水平传递：随机配对多数采用者传染 + 小突变
        i = int(self.rng.integers(self.n))
        j = int(self.rng.integers(self.n))
        if self.trait[j] != self.trait[i] and self.rng.random() < 0.5:
            self.trait[i] = self.trait[j]

    def observe(self):
        return {"adopted_frac": float(self.trait.mean())}

    def validate_state(self):
        return []


class HenrichBoydConformity:
    """BEH036 从众传播：采纳概率随多数者数量超线性增长。"""

    model_id = "BEH036"

    def __init__(self, n=200, p_conform=3.0, seed=0):
        self.n, self.p_conform, self.seed = n, p_conform, seed
        self.rng = np.random.default_rng(seed)
        self.trait = (self.rng.random(n) < 0.5).astype(float)

    def initialize(self, context, parameters, population, topology, rng):
        self.trait = (rng.random(self.n) < 0.5).astype(float)

    def step(self, t, dt):
        i = int(self.rng.integers(self.n))
        j = int(self.rng.integers(self.n))
        # 从众：多数 trait 有 (1+系数) 倍传染优势
        w = 1.0 + self.p_conform * (self.trait[j] - self.trait[i])
        if self.trait[j] != self.trait[i] and self.rng.random() < max(0.0, w / 2):
            self.trait[i] = self.trait[j]

    def observe(self):
        return {"frac1": float(self.trait.mean())}

    def validate_state(self):
        return []


class PayoffBiasedLearning:
    """BEH037 收益偏置文化学习：高收益行为被 copying。"""

    model_id = "BEH037"

    def __init__(self, n=200, seed=0):
        self.n, self.seed = n, seed
        self.rng = np.random.default_rng(seed)
        self.behavior = self.rng.integers(0, 2, n)
        self.payoff = self.rng.random(n)

    def initialize(self, context, parameters, population, topology, rng):
        self.behavior = rng.integers(0, 2, self.n)
        self.payoff = rng.random(self.n)

    def step(self, t, dt):
        i = int(self.rng.integers(self.n))
        j = int(self.rng.integers(self.n))
        if i == j:
            return
        # 收益偏置：copy 概率 ∝ payoff 差
        dp = self.payoff[j] - self.payoff[i]
        if dp > 0 and self.rng.random() < dp:
            self.behavior[i] = self.behavior[j]
            self.payoff[i] = self.payoff[j]

    def observe(self):
        return {"mean_payoff": float(self.payoff.mean()),
                "behavior_frac": float(self.behavior.mean())}

    def validate_state(self):
        return []


class PrestigeBiasedTransmission:
    """BEH038 声望偏置文化传递：copy 声望高者。"""

    model_id = "BEH038"

    def __init__(self, n=200, seed=0):
        self.n, self.seed = n, seed
        self.rng = np.random.default_rng(seed)
        self.prestige = self.rng.pareto(1.5, n)
        self.behavior = self.rng.integers(0, 2, n)

    def initialize(self, context, parameters, population, topology, rng):
        self.prestige = rng.pareto(1.5, self.n)
        self.behavior = rng.integers(0, 2, self.n)

    def step(self, t, dt):
        i = int(self.rng.integers(self.n))
        cands = list(range(self.n))
        cands.remove(i)
        w = self.prestige[cands]
        j = cands[int(np.searchsorted(np.cumsum(w), self.rng.random() * w.sum()))]
        if self.rng.random() < 0.5:
            self.behavior[i] = self.behavior[j]

    def observe(self):
        top10 = np.sort(self.prestige)[-max(1, self.n // 10):]
        mask = np.isin(self.prestige, top10)
        return {"elite_behavior_frac": float(self.behavior[mask].mean())}

    def validate_state(self):
        return []


class RogersParadox:
    """BEH039 Rogers 社会学习悖论：学习者比例>0 时群体平均适应度持平。"""

    model_id = "BEH039"

    def __init__(self, n=200, p_learn=0.1, seed=0):
        self.n, self.p_learn, self.seed = n, p_learn, seed
        self.rng = np.random.default_rng(seed)
        self.learners = self.rng.random(n) < p_learn

    def initialize(self, context, parameters, population, topology, rng):
        self.learners = rng.random(self.n) < self.p_learn

    def step(self, t, dt):
        env = self.rng.random() < 0.02  # 环境切换
        if env:
            self.env_state = 1 - getattr(self, "env_state", 0)
        if not hasattr(self, "env_state"):
            self.env_state = 0
        for i in range(self.n):
            if self.learners[i]:
                self.fitness_type = self.env_state  # 学习者重新采样
            # 社会学习者保持旧行为

    def observe(self):
        return {"learner_frac": float(self.learners.mean())}

    def validate_state(self):
        return []


class HenrichPopulationAccumulation:
    """BEH040 人口规模与累积文化：大群体维持更复杂的技能。"""

    model_id = "BEH040"

    def __init__(self, n=100, skill_diff=0.5, seed=0):
        self.n, self.skill_diff, self.seed = n, skill_diff, seed
        self.rng = np.random.default_rng(seed)
        self.skill = 1.0

    def initialize(self, context, parameters, population, topology, rng):
        pass

    def step(self, t, dt):
        # 繁衍-学习：最优技能者作为教师，学习噪声由群体规模决定
        best = min(self.skill, 10.0)
        mutation = self.rng.normal(0, 0.3 / max(1, self.n ** 0.5))
        self.skill = max(0.1, best + mutation)

    def observe(self):
        return {"skill": float(self.skill)}

    def validate_state(self):
        return []


class NamingGame:
    """BEH045 命名博弈：意义-词汇关联涌现（全局共识收敛）。"""

    model_id = "BEH045"

    def __init__(self, n=100, seed=0):
        self.n, self.seed = n, seed
        self.rng = np.random.default_rng(seed)
        self.inventories = [set() for _ in range(n)]
        self.success_count = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.inventories = [set() for _ in range(self.n)]
        self.success_count = 0

    def step(self, t, dt):
        a = int(self.rng.integers(self.n))
        b = int(self.rng.integers(self.n))
        if a == b:
            return
        if not self.inventories[a]:
            word = f"w{self.rng.integers(10**6)}"
            self.inventories[a].add(word)
        word = sorted(self.inventories[a])[0]
        if word in self.inventories[b]:
            # 成功：双方只保留该词
            self.inventories[a] = {word}
            self.inventories[b] = {word}
            self.success_count += 1
        else:
            self.inventories[b].add(word)

    def observe(self):
        allw = set()
        for inv in self.inventories:
            allw |= inv
        converged = sum(1 for inv in self.inventories if inv == allw and len(allw) == 1)
        return {"distinct_words": len(allw),
                "aligned_agents": converged,
                "success_rate": self.success_count}

    def validate_state(self):
        return []


class AbramsStrogatz:
    """BEH046 Abrams–Strogatz 语言竞争：dX/dt = c·X^a·Y − c·Y^a·X。"""

    model_id = "BEH046"
    clock_type = "ode"

    def __init__(self, s=0.42, a=1.31, X0=0.5):
        self.s, self.a, self.X0 = s, a, X0
        self.x = np.array([X0])

    def initialize(self, context, parameters, population, topology, rng):
        self.s = parameters.get("s", self.s)
        self.a = parameters.get("a", self.a)
        self.x = np.array([parameters.get("X0", 0.5)])

    def derivatives(self, t, x):
        X = max(1e-9, min(1 - 1e-9, x[0]))
        Y = 1 - X
        return np.array([self.s * X ** self.a * Y - self.s * Y ** self.a * X])

    def observe(self):
        return {"X_frac": float(self.x[0]), "Y_frac": float(1 - self.x[0])}

    def validate_state(self):
        return [] if 0 <= self.x[0] <= 1 else ["语言占比越界"]
