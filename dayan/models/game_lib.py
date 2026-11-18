"""博弈收益库（BEH049-068）+ 策略/演化学习（BEH069-093）+ 行为决策（BEH094-111）。

统一为紧凑规格/类，全部带解析或行为基准（tests/test_dayan_games_lib.py）。
"""
from __future__ import annotations

import numpy as np
from math import factorial

from ..engines.games import MatrixGame


def _g(A, B=None, actions=None):
    return MatrixGame(A, (B if B is not None else A.copy()), actions)


# ============ BEH049-068 博弈收益库 ============
def g_prisoners_dilemma():
    """BEH049: R=3,T=5,S=0,P=1 → 唯一纳什 (D,D)。"""
    return _g([[3, 0], [5, 1]], [[3, 5], [0, 1]], ["C", "D"])


def g_hawk_dove(V=4, C=6):
    """BEH050 鹰鸽/雪堆：两纯 + 一混合。"""
    A = np.array([[(V - C) / 2, V], [0, V / 2]])
    return _g(A, A.T.copy(), ["Hawk", "Dove"])


def g_stag_hunt(r=4, s=1, p=2):
    """BEH051 猎鹿/保证博弈：两纯纳什（猎鹿风险占优可调）。"""
    A = np.array([[r, 0], [s, p]])
    return _g(A, A.T.copy(), ["Stag", "Hare"])


def public_goods_payoff(mult=1.6, contrib=1.0, n=4):
    """BEH052-054 公共品：贡献者收益 = mult·Σc/n − c。"""
    def payoff_row_player(contrib_i, others_sum, n=n, mult=mult):
        return mult * (contrib_i + others_sum) / n - contrib_i
    return payoff_row_player


def volunteer_dilemma_cost(c=1.0, n=5):
    """BEH055 志愿者困境： volunteer 得 −c，其余 0；无人志愿全输。"""
    def payoff(is_volunteer, someone_else=False, c=c):
        if is_volunteer:
            return -c
        return 0.0 if someone_else else -5.0
    return payoff


def cpr_appropriation(n=6, r=1.0, a=20.0, b=0.3):
    """BEH056 共同池资源： appropriation 外部性 a−b·Σe。"""
    def payoff(ei, total_e, r=r, a=a, b=b):
        return ei * max(0.0, r * (a - b * total_e))
    return payoff


def ultimatum_split(offer, accept_threshold=None):
    """BEH057 最后通牒：提议者分 offer，回应者阈值接受。"""
    if accept_threshold is not None and offer < accept_threshold:
        return (0.0, 0.0)
    return (10.0 - offer, offer)


def dictator_split(give):
    """BEH058 独裁者：单方面决定。"""
    return (10.0 - give, give)


def trust_game(invest, return_rate=0.3):
    """BEH059 信任/投资博弈：投资×3，受信人返还 return_rate·3·invest。"""
    returned = return_rate * 3 * invest
    return (10.0 - invest + returned, 3 * invest - returned)


def matching_pennies_payoff():
    """BEH060 正反硬币零和：A = −B，无纯纳什，混合各 1/2。"""
    A = np.array([[1.0, -1.0], [-1.0, 1.0]])
    return _g(A, -A.copy(), ["Heads", "Tails"])


def coordination_conflict_payoff(a=2.0, b=1.0):
    """BEH061 偏好冲突协调：两纯纳什+混合，偏好不对称。"""
    A = np.array([[a, 0.0], [0.0, b]])
    B = np.array([[b, 0.0], [0.0, a]])
    return _g(A, B, ["Opera", "Ball"])


def rps_cyclic_payoff():
    """BEH062 石头剪刀布：循环优势，唯一混合纳什 1/3×1/3。"""
    A = np.array([[0.0, -1.0, 1.0], [1.0, 0.0, -1.0], [-1.0, 1.0, 0.0]])
    return _g(A, -A.copy(), ["R", "P", "S"])


def centipede_depth(k=6):
    """BEH063 蜈蚣博弈：k 节点，早停收益差→"合作"可帕累托占优。"""
    # 节点 i：继续→下一节点；停止→(s_i, t_i)
    s = [2 ** i * 1.0 for i in range(k)]
    t = [2 ** i * 0.9 for i in range(k)]
    return {"stop_self": s, "stop_other": t, "depth": k}


def shapley_value(costs_or_contrib: dict, coalition_fn=None) -> dict:
    """BEH064 Shapley 边际贡献分配（精确枚举）。"""
    from itertools import permutations
    players = list(costs_or_contrib)
    vals = costs_or_contrib
    contrib = {p: 0.0 for p in players}
    for perm in permutations(players):
        s = set()
        for p in perm:
            s.add(p)
            contrib[p] += vals.get(frozenset(s), 0.0) / factorial(len(s)) \
                if False else 0.0
    # 简化：均匀分离值（特征函数由 coalition_fn 给）
    if coalition_fn is None:
        return contrib
    n = len(players)
    fact = factorial
    out = {p: 0.0 for p in players}
    for perm in permutations(players):
        s = set()
        prev = coalition_fn(frozenset(s))
        for p in perm:
            s.add(p)
            cur = coalition_fn(frozenset(s))
            out[p] += (cur - prev) / fact(n)
            prev = cur
    return out


def nash_bargaining(u0, u1, d0=0.0, d1=0.0):
    """BEH067 Nash 议价解：max (u0−d0)(u1−d1) 。
    u0/u1: 帕累托边界上的两个点列表（等长）。"""
    best, best_val = None, -np.inf
    for a, b in zip(u0, u1):
        val = (a - d0) * (b - d1)
        if val > best_val:
            best_val = val
            best = (a, b)
    return best, best_val


# ============ BEH069-093 策略/演化规则 ============
class RepeatedPDStrategies:
    """BEH069-072 重复 PD 策略库：TFT/GTFT/Pavlov/Grim。"""

    @staticmethod
    def tit_for_tat(my_hist, opp_hist):
        return opp_hist[-1] if opp_hist else 0  # 0=合作

    @staticmethod
    def generous_tft(my_hist, opp_hist, p_forgive=0.1, rng=None):
        if not opp_hist:
            return 0
        if opp_hist[-1] == 1:
            rng = rng or np.random.default_rng()
            return 1 if rng.random() < p_forgive else 0
        return 0

    @staticmethod
    def pavlov(my_hist, opp_hist):
        if not my_hist:
            return 0
        if my_hist[-1] == opp_hist[-1]:  # 上轮同 action（都合作/都背叛）→ 重复
            return my_hist[-1]
        return 1 - my_hist[-1]

    @staticmethod
    def grim_trigger(my_hist, opp_hist):
        return 1 if (1 in opp_hist) else 0


def zero_determinant_rule(my_last, opp_last, p, r, s=1.0):
    """BEH073 零行列式策略：以 p 概率回应合作，r 概率回应背叛（可"勒索"）。"""
    prob_c = p if my_last == 0 else (r if opp_last == 1 else s)
    rng = np.random.default_rng()
    return 0 if rng.random() < prob_c else 1


class ImageScoringIndirectReciprocity:
    """BEH074 bounded first-order image scores and score-based donations."""

    model_id = "BEH074"

    def __init__(self, n=100, err=0.01, seed=0):
        if not 2<=n<=5000 or not 0<=err<=1:
            raise ValueError("至少两名主体，错误概率在0..1")
        self.n, self.err, self.seed = n, err, seed
        self.rng = np.random.default_rng(seed)
        self.image = np.zeros(n,dtype=int)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        self.image = np.zeros(self.n,dtype=int)
        self.cooperations=0
        self.encounters=0

    def step(self, t, dt):
        d = int(self.rng.integers(self.n))
        r = int(self.rng.integers(self.n-1))
        if r>=d:r+=1
        cooperate = self.image[r] >= 0
        if self.rng.random() < self.err:
            cooperate = not cooperate
        self.image[d]=int(np.clip(self.image[d]+(1 if cooperate else -1),-5,5))
        self.cooperations+=int(cooperate)
        self.encounters+=1

    def observe(self):
        return {"mean_image": float(self.image.mean()),
                "coop_image_frac": float((self.image >= 0).mean()),
                "cooperation_rate": self.cooperations/self.encounters if self.encounters else None,
                "encounters": self.encounters}

    def validate_state(self):
        return []


class NormsModels:
    """BEH075-077 声誉规范三件套：简单立场/严厉评判/排斥。"""

    @staticmethod
    def simple_standing(donor_rep, recip_rep):
        return 1.0 if recip_rep > 0 else -1.0

    @staticmethod
    def stern_judging(donor_rep, recip_rep, cooperate):
        if cooperate:
            return 1.0 if recip_rep > 0 else -1.0
        return -1.0 if recip_rep > 0 else 1.0

    @staticmethod
    def exclusion_norm(pop_image, exclude_below=0.0):
        return [i for i, r in pop_image if r <= exclude_below]


class AxelrodNormGame:
    """BEH078-079 Axelrod 规范/元规范博弈：胆怯→受罚→规范存续。"""

    def __init__(self, n=20, reward=3.0, punishment=9.0, meta_cost=1.0, seed=0):
        self.n = n
        self.boldness = np.random.default_rng(seed).random(n)
        self.vengeance = np.random.default_rng(seed + 1).random(n)
        self.reward, self.punishment, self.meta_cost = reward, punishment, meta_cost

    def step(self, t, dt):
        rng = np.random.default_rng()
        i = int(rng.integers(self.n))
        if self.boldness[i] > rng.random():
            # 行窃被发现概率=剩余目击者比例
            witnesses = [j for j in range(self.n) if j != i]
            seen = [j for j in witnesses if rng.random() < 1 / len(witnesses) * 2]
            for j in seen:
                if self.vengeance[j] > rng.random():
                    self.boldness[i] -= self.punishment / 10
                    break
        self.boldness = np.clip(self.boldness, 0, 1)
        self.vengeance = np.clip(self.vengeance + 0.01 * (rng.random() - 0.5), 0, 1)

    def observe(self):
        return {"mean_boldness": float(self.boldness.mean()),
                "norm_violation_rate": float((self.boldness > 0.5).mean())}


class YoungConventions:
    """BEH081 Young 惯例演化：邻居加权多数 + 随机扰动 → 惯例涌现。"""

    model_id = "BEH081"

    def __init__(self, n=100, actions=2, seed=0):
        self.n, self.actions, self.seed = n, actions, seed
        self.rng = np.random.default_rng(seed)
        self.actions_held = rng.integers(0, actions, n)

    def initialize(self, context, parameters, population, topology, rng):
        self.actions_held = rng.integers(0, self.actions, self.n)

    def step(self, t, dt):
        rng = self.rng
        i = int(rng.integers(self.n))
        j = int(rng.integers(self.n))
        self.actions_held[i] = self.actions_held[j]

    def observe(self):
        u, c = np.unique(self.actions_held, return_counts=True)
        return {"dominant_share": float(c.max() / self.n)}


# ============ 演化/学习规则（BEH082-093） ============
def moran_process(fitness: np.ndarray, rng: np.random.default_rng = None) -> np.ndarray:
    """BEH084 Moran 过程：按适应度选复制者，均匀选死亡者。"""
    rng = rng or np.random.default_rng()
    pop = fitness.copy()
    i = rng.choice(len(pop), p=pop / pop.sum())
    j = int(rng.integers(len(pop)))
    pop[j] = pop[i]
    return pop


def fermi_update(my_fit, other_fit, beta=3.0, rng=None):
    """BEH085 Fermi 成对比较：switch 概率 = 1/(1+e^{β(Δf<0)})。"""
    rng = rng or np.random.default_rng()
    return 1.0 / (1.0 + np.exp(beta * (my_fit - other_fit)))


def best_response_dynamics(payoff_matrix, x0, steps=50, rng=None):
    """BEH086 最优反应动态。"""
    rng = rng or np.random.default_rng()
    x = np.asarray(x0, float).copy()
    n = len(x)
    for s in range(steps):
        i = s % n
        br = int(np.argmax(payoff_matrix[i] @ x))
        x[i] = br
    return x


def logit_response_dynamics(payoff_matrix, x0, lam=2.0, steps=100, dt=0.1):
    """BEH087 Logit 响应：平滑最优反应。"""
    x = np.asarray(x0, float).copy()
    for _ in range(steps):
        fit = payoff_matrix @ x
        exp_fit = np.exp(lam * (fit - fit.max()))
        target = exp_fit / exp_fit.sum()
        x = x + dt * (target - x)
    return x


def fictitious_play(payoff_row, opp_action_hist, laplace=1):
    """BEH088 虚拟博弈：对手历史频率 → 最优反应。"""
    from collections import Counter
    c = Counter(opp_action_hist)
    n = len(opp_action_hist) + laplace * len(payoff_row)
    beliefs = np.array([(c.get(i, 0) + laplace) / n
                        for i in range(len(payoff_row))])
    return int(np.argmax(payoff_row @ beliefs))


def ewa_learning(payoffs_chosen, attractivities, decay=0.6, phi=0.8):
    """BEH089 经验加权吸引（EWA）。"""
    attractivities = phi * attractivities + payoffs_chosen
    return attractivities


def roth_erev(payoffs, propensities, exp=1.0):
    """BEH090 Roth–Erev 强化：倾向累积 + 指数权重选择。"""
    prop = exp * np.asarray(propensities, float) + np.asarray(payoffs, float)
    probs = prop / prop.sum()
    return prop, probs


def bush_mosteller(prob_vec, payoff_vec, aspiration, lambda_rate=0.3):
    """BEH091 Bush–Mosteller 概率学习。"""
    chosen = int(np.argmax(payoff_vec))
    delta = np.zeros_like(prob_vec)
    delta[chosen] = 1.0 if payoff_vec[chosen] >= aspiration else -1.0
    return prob_vec + lambda_rate * (delta - prob_vec)


def bayesian_opponent_learning(my_action, opp_action, prior_matrix):
    """BEH092 贝叶斯对手学习：更新对手类型后验。"""
    post = prior_matrix.copy()
    # 观测对手动作 → 简化似然更新
    post[opp_action] *= 2.0
    total = post.sum()
    return post / total


def regret_matching(cum_regrets: np.ndarray) -> np.ndarray:
    """BEH093 遗憾匹配：正遗憾比例选择。"""
    pos = np.clip(cum_regrets, 0, None)
    total = pos.sum()
    return pos / total if total > 0 else np.ones(len(pos)) / len(pos)


# ============ BEH094-111 行为决策/认知（紧凑） ============
def prospect_theory_value(x, alpha=0.88, beta=0.88, lam=2.25):
    """BEH104 前景理论价值函数：收益凹/损失凸×2.25 放大。"""
    if x >= 0:
        return x ** alpha
    return -lam * (-x) ** beta


def cumulative_prospect_weights(p, gamma=0.61, delta=0.69):
    """BEH105 累积前景理论决策权重。"""
    w_p = p ** gamma / (p ** gamma + (1 - p) ** gamma) ** (1 / gamma)
    return w_p


def fehr_schmidt_utility(own, others: list, alpha=0.5, beta=0.3):
    """BEH106 Fehr–Schmidt 不平等厌恶：劣势厌恶 α > 优势厌恶 β。"""
    advantaged = [o - own for o in others if o > own]
    disadvantaged = [own - o for o in others if o < own]
    u = own - alpha * sum(advantaged) - beta * sum(disadvantaged)
    return u


def level_k_action(k: int, best_responses: dict, level0=None):
    """BEH109 Level-k 递推：L1 对 L0 最优反应，L2 对 L1 最优反应……"""
    if k == 0:
        return level0
    a = best_responses.get(k - 1)
    return best_responses.get(k, a)


def quantal_response_equilibrium(payoff_row, lam=1.0):
    """BEH111 量化反应均衡：P(i) ∝ exp(λ·u_i)。"""
    u = np.asarray(payoff_row, float)
    e = np.exp(lam * (u - u.max()))
    return e / e.sum()


def drift_diffusion(t, evidence, threshold, bound=2.0, dt=0.01):
    """BEH102 漂移扩散决策（DDM）：证据累积到界 → 决策。"""
    e = evidence
    steps = int(t / dt)
    pos = 0.0
    for _ in range(steps):
        pos += e * dt + np.random.default_rng().normal(0, 0.1)
        if abs(pos) >= bound:
            return pos
    return pos


class BDIAgentStub:
    """BEH094 BDI 架构骨架：Beliefs/Desires/Intentions 三层。"""

    def __init__(self):
        self.beliefs: dict = {}
        self.desires: list = []
        self.intentions: list = []

    def add_belief(self, key, val):
        self.beliefs[key] = val

    def deliberate(self):
        self.intentions = [d for d in self.desires
                           if self.beliefs.get(d.get("condition", True))]

    def execute_next(self):
        return self.intentions.pop(0) if self.intentions else None
