"""意见动力学家族（BEH015-032）：统一网络影响引擎 + 逐模型变体。

共享引擎：网络 + 连续/离散意见 + 逐模型更新规则。每模型实现 update_step。
"""
from __future__ import annotations

import numpy as np


def _ring(n, k=4, rng=None):
    """环格邻接（无向）。"""
    adj = [[] for _ in range(n)]
    for i in range(n):
        for dk in (1, -1):
            adj[i].append((i + dk) % n)
    return adj


class OpinionBase:
    """意见动力学基类（fixed_step，同步提交）。"""

    model_id = "unset"

    def __init__(self, n=100, x0=None, seed=0):
        self.n = n
        self.rng = np.random.default_rng(seed)
        self.x = (np.asarray(x0, float) if x0 is not None
                  else self.rng.random(n))
        self.step_count = 0

    def initialize(self, context, parameters, population, topology, rng):
        if parameters.get("x0") is not None:
            self.x = np.asarray(parameters["x0"], float)
        if parameters.get("n"):
            self.n = parameters["n"]

    def update_step(self):
        raise NotImplementedError

    def step(self, t, dt):
        self.update_step()
        self.step_count += 1

    def observe(self):
        return {"opinions": self.x.tolist(), "mean": float(self.x.mean()),
                "spread": float(self.x.max() - self.x.min()),
                "clusters": int(self._clusters())}

    def _clusters(self, eps=0.01):
        xs = np.sort(self.x)
        if len(xs) == 0:
            return 0
        return 1 + int((np.diff(xs) > eps).sum())

    def validate_state(self):
        return []


class FriedkinJohnsen(OpinionBase):
    """BEH016 固执度模型：x(t+1) = P x(t) 的 FJ 形式
    x_i(t+1) = g_i·x_i(0) + (1−g_i)·邻居加权均值。共识不必然（固执锚定）。"""

    model_id = "BEH016"

    def __init__(self, n=60, g=0.2, seed=0):
        super().__init__(n=n, seed=seed)
        self.g = g
        self.x0 = self.x.copy()

    def initialize(self, context, parameters, population, topology, rng):
        if parameters.get("g") is not None:
            self.g = parameters["g"]
        self.x0 = self.x.copy()

    def update_step(self):
        nb_mean = np.array([np.delete(self.x, i).mean()
                            for i in range(self.n)])
        self.x = self.g * self.x0 + (1 - self.g) * nb_mean


class DeffuantWeisbuch(OpinionBase):
    """BEH018 配对妥协：随机邻对，|差|≤d 时相互靠拢 μ。有界信任→极化簇。"""

    model_id = "BEH018"

    def __init__(self, n=100, d=0.2, mu=0.3, seed=0):
        super().__init__(n=n, seed=seed)
        self.d, self.mu = d, mu

    def initialize(self, context, parameters, population, topology, rng):
        self.d = parameters.get("d", self.d)
        self.mu = parameters.get("mu", self.mu)
        self.x = self.rng.random(self.n)

    def update_step(self):
        i = int(self.rng.integers(self.n))
        j = int(self.rng.integers(self.n))
        if i == j:
            return
        if abs(self.x[i] - self.x[j]) <= self.d:
            m = self.mu * (self.x[j] - self.x[i])
            self.x[i] += m
            self.x[j] -= m


class RelativeAgreement(OpinionBase):
    """BEH019 相对一致性：RA 规则，含极化端点排斥变体可调。"""

    model_id = "BEH019"

    def __init__(self, n=100, d=0.2, mu=0.2, seed=0):
        super().__init__(n=n, seed=seed)
        self.d, self.mu = d, mu

    def initialize(self, context, parameters, population, topology, rng):
        self.x = self.rng.random(self.n)

    def update_step(self):
        i, j = int(self.rng.integers(self.n)), int(self.rng.integers(self.n))
        if i == j:
            return
        ra = 1 - abs(self.x[i] - self.x[j])
        if ra >= self.d:
            m = self.mu * ra * (self.x[j] - self.x[i])
            self.x[i] += m


class NoisyVoter(OpinionBase):
    """BEH025 含噪多数投票：二值意见 + 独立噪声翻转。"""

    model_id = "BEH025"

    def __init__(self, n=100, noise=0.01, seed=0):
        super().__init__(n=n, seed=seed)
        self.noise = noise
        self.x = (self.rng.random(n) < 0.5).astype(float)

    def initialize(self, context, parameters, population, topology, rng):
        self.noise = parameters.get("noise", self.noise)
        self.x = (rng.random(self.n) < 0.5).astype(float)

    def update_step(self):
        i = int(self.rng.integers(self.n))
        if self.rng.random() < self.noise:
            self.x[i] = 1 - self.x[i]
        else:
            nb = np.delete(self.x, i)
            self.x[i] = 1.0 if nb.mean() > 0.5 else 0.0


class QVoterModel(OpinionBase):
    """BEH022 q-选民：q 个邻居一致 → 采纳；否则独立噪声翻转。"""

    model_id = "BEH022"

    def __init__(self, n=100, q=4, noise=0.05, seed=0):
        super().__init__(n=n, seed=seed)
        self.q, self.noise = q, noise
        self.x = (self.rng.random(n) < 0.5).astype(float)

    def initialize(self, context, parameters, population, topology, rng):
        self.q = parameters.get("q", self.q)
        self.noise = parameters.get("noise", self.noise)
        self.x = (rng.random(self.n) < 0.5).astype(float)

    def update_step(self):
        i = int(self.rng.integers(self.n))
        panel = self.rng.integers(0, self.n, self.q)
        panel = panel[panel != i]
        panel = np.append(panel, i)[:self.q]
        vals = self.x[panel]
        if vals.min() == vals.max():
            self.x[i] = vals[0]
        elif self.rng.random() < self.noise:
            self.x[i] = 1 - self.x[i]


class SznajdModel(OpinionBase):
    """BEH023 Sznajd 一致说服：随机对一致 → 说服全部邻居。"""

    model_id = "BEH023"

    def __init__(self, n=100, seed=0):
        super().__init__(n=n, seed=seed)
        self.x = (self.rng.random(n) < 0.5).astype(float)

    def update_step(self):
        i = int(self.rng.integers(self.n - 1))
        if self.x[i] == self.x[i + 1]:
            tgt = self.rng.integers(0, self.n, 6)
            self.x[tgt] = self.x[i]


class GalamModel(OpinionBase):
    """BEH024 Galam 局部多数：随机三人组多数裁决（含偏置）。"""

    model_id = "BEH024"

    def __init__(self, n=99, bias=0.0, seed=0):
        super().__init__(n=n, seed=seed)
        self.bias = bias
        self.x = (self.rng.random(n) < 0.5).astype(float)

    def initialize(self, context, parameters, population, topology, rng):
        self.bias = parameters.get("bias", self.bias)
        self.x = (rng.random(self.n) < 0.5).astype(float)

    def update_step(self):
        order = self.rng.permutation(self.n)
        for k in range(0, len(order) - 2, 3):
            trio = self.x[order[k:k + 3]]
            maj = 1.0 if trio.mean() > 0.5 else 0.0
            if self.rng.random() < self.bias:
                maj = 1 - maj
            self.x[order[k:k + 3]] = maj


class AltafiniModel(OpinionBase):
    """BEH028 Altafini 符号网络共识：负边翻转符号（结构平衡动力学）。"""

    model_id = "BEH028"

    def __init__(self, n=30, neg_prob=0.3, seed=0):
        super().__init__(n=n, seed=seed)
        self.neg_prob = neg_prob
        self.sign = np.where(self.rng.random((n, n)) < neg_prob, -1.0, 1.0)
        np.fill_diagonal(self.sign, 0.0)
        row = np.abs(self.sign).sum(axis=1)
        row[row == 0] = 1
        self.W = self.sign / row

    def initialize(self, context, parameters, population, topology, rng):
        pass

    def update_step(self):
        self.x = self.W @ self.x


class JagerAmblard(OpinionBase):
    """BEH030 Jager–Amblard 吸引/排斥：近吸引远排斥，不对称强度。"""

    model_id = "BEH030"

    def __init__(self, n=100, d_pos=0.3, mu_pos=0.2, mu_neg=0.5, seed=0):
        super().__init__(n=n, seed=seed)
        self.d_pos, self.mu_pos, self.mu_neg = d_pos, mu_pos, mu_neg

    def initialize(self, context, parameters, population, topology, rng):
        self.x = self.rng.random(self.n) * 2 - 1  # 意见域 [-1,1]

    def update_step(self):
        i, j = int(self.rng.integers(self.n)), int(self.rng.integers(self.n))
        if i == j:
            return
        diff = abs(self.x[i] - self.x[j])
        if diff <= self.d_pos:
            self.x[i] += self.mu_pos * (self.x[j] - self.x[i])
        else:
            self.x[i] -= self.mu_neg * (self.x[j] - self.x[i])
        self.x[i] = np.clip(self.x[i], -1, 1)


class BrockDurlauf(OpinionBase):
    """BEH031 Brock–Durlauf 社会互动离散选择：期望Peer效应+私偏好。"""

    model_id = "BEH031"

    def __init__(self, n=100, J=2.0, h=0.1, beta=1.5, seed=0):
        super().__init__(n=n, seed=seed)
        self.J, self.h, self.beta = J, h, beta
        self.x = (self.rng.random(n) < 0.5).astype(float) * 2 - 1  # {-1,+1}

    def initialize(self, context, parameters, population, topology, rng):
        self.J = parameters.get("J", self.J)
        self.x = (rng.random(self.n) < 0.5).astype(float) * 2 - 1

    def update_step(self):
        i = int(self.rng.integers(self.n))
        expect = np.delete(self.x, i).mean()
        util1 = self.h + self.J * expect
        prob = 1.0 / (1.0 + np.exp(-self.beta * util1))
        self.x[i] = 1.0 if self.rng.random() < prob else -1.0


class FlacheMacy(OpinionBase):
    """BEH032 Flache–Macy 带负影响的文化极化：连续意见+正负影响。"""

    model_id = "BEH032"

    def __init__(self, n=80, sus=0.8, neg_bias=0.5, seed=0):
        super().__init__(n=n, seed=seed)
        self.sus = sus
        self.neg_bias = neg_bias

    def initialize(self, context, parameters, population, topology, rng):
        self.x = rng.random(self.n) * 2 - 1

    def update_step(self):
        i, j = int(self.rng.integers(self.n)), int(self.rng.integers(self.n))
        if i == j:
            return
        diff = self.x[j] - self.x[i]
        if abs(diff) < 1.0:
            self.x[i] += self.sus * 0.2 * diff
        else:
            self.x[i] -= self.neg_bias * 0.2 * np.sign(diff)
        self.x[i] = np.clip(self.x[i], -1, 1)


class DynamicSocialInfluence(OpinionBase):
    """BEH026 动态社会影响（Nowak–Latané）：影响=强度×距离^衰减×人数。"""

    model_id = "BEH026"

    def __init__(self, n=60, src=0.2, expnt=2.0, seed=0):
        super().__init__(n=n, seed=seed)
        self.src, self.expnt = src, expnt
        self.strength = np.ones(n)

    def initialize(self, context, parameters, population, topology, rng):
        self.x = rng.random(self.n) * 2 - 1
        self.src_idx = int(rng.integers(self.n))
        self.x[self.src_idx] = 1.0

    def update_step(self):
        for i in range(self.n):
            if i == self.src_idx:
                continue
            d = abs(self.x[i] - 1.0) + 1e-9
            influence = self.strength.sum() / (d ** self.expnt)
            if self.rng.random() < min(0.5, influence / self.n * 2):
                self.x[i] += 0.1 * (1.0 - self.x[i])
        self.x = np.clip(self.x, -1, 1)


class ContinuousOpinionDiscreteAction(OpinionBase):
    """BEH027 连续意见—离散行动：意见连续演化，行动按阈值离散化。"""

    model_id = "BEH027"

    def __init__(self, n=80, d=0.25, mu=0.3, thr=0.5, seed=0):
        super().__init__(n=n, seed=seed)
        self.d, self.mu, self.thr = d, mu, thr
        self.action_pub = None

    def initialize(self, context, parameters, population, topology, rng):
        self.x = self.rng.random(self.n)

    def update_step(self):
        i = int(self.rng.integers(self.n))
        j = int(self.rng.integers(self.n))
        if i != j and abs(self.x[i] - self.x[j]) <= self.d:
            self.x[i] += self.mu * (self.x[j] - self.x[i])
        self.action_pub = (self.x > self.thr).astype(float).tolist()

    def observe(self):
        base = super().observe()
        base["action_share"] = float(np.mean(self.x > self.thr))
        return base


class HKTruthSeeking(OpinionBase):
    """BEH029 HK 真值寻求扩展：有界信任 + 真值吸引子。"""

    model_id = "BEH029"

    def __init__(self, n=60, eps=0.2, truth=0.7, w_truth=0.1, seed=0):
        super().__init__(n=n, seed=seed)
        self.eps, self.truth, self.w_truth = eps, truth, w_truth

    def initialize(self, context, parameters, population, topology, rng):
        self.x = rng.random(self.n)

    def update_step(self):
        new = []
        for xi in self.x:
            nb = self.x[np.abs(self.x - xi) <= self.eps]
            m = nb.mean()
            new.append((1 - self.w_truth) * m + self.w_truth * self.truth)
        self.x = np.array(new)


MODELS = {
    "BEH016": FriedkinJohnsen,
    "BEH018": DeffuantWeisbuch,
    "BEH019": RelativeAgreement,
    "BEH022": QVoterModel,
    "BEH023": SznajdModel,
    "BEH024": GalamModel,
    "BEH025": NoisyVoter,
    "BEH026": DynamicSocialInfluence,
    "BEH027": ContinuousOpinionDiscreteAction,
    "BEH028": AltafiniModel,
    "BEH030": JagerAmblard,
    "BEH031": BrockDurlauf,
    "BEH032": FlacheMacy,
    "BEH029": HKTruthSeeking,
}
