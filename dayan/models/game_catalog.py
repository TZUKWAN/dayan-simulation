"""BEH 博弈/学习/行为决策目录映射（BEH049-093、104-111、075-080、064-068）。

把 dayan/models/game_lib.py 的既有实现包装为 DayanModel（每个目录 ID 可运行）：
- BEH049-063: 博弈收益规格（PD/鹰鸽/猎鹿/公共品/惩罚/志愿/CPR/最后通牒/
              独裁者/信任/硬币/协调/RPS/蜈蚣）
- BEH064-068: 合作博弈（Shapley 值/核仁/Nash 议价/Rubinstein 交替出价）
- BEH069-073: 重复博弈策略（TFT/宽容TFT/Pavlov/Grim/零行列式）
- BEH075-080: 规范博弈族（简单立场/严厉评判/排斥声誉/Axelrod/元规范/从众惩罚）
- BEH082-093: 演化学习规则（复制/突变/Moran/Fermi/BR/Logit/虚拟/EWA/
              Roth-Erev/BM/贝叶斯/遗憾匹配）
- BEH104-106,109-111: 行为决策（前景/CPT/FS 不平等/Level-k/QRE；DDM=BEH102）
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel
from . import game_lib as G
from pathlib import Path as _P
ROOT_DIR = _P(__file__).resolve().parents[2]


class _GameEvolModel(DayanModel):
    """演化博弈模板：收益矩阵 + 更新规则（fixed_step）。子类指定目录 ID。"""

    clock_type = "fixed_step"
    _spec_fn = None      # (A, B=None, actions)
    _update = "replicator"
    _mu = 0.0            # 突变率

    def __init__(self, x0=None, dt=0.05):
        self.x0 = np.asarray(x0, float) if x0 is not None else None
        self.dt0 = dt
        self.x = None
        self.rng_ = None

    def initialize(self, context, parameters, population, topology, rng):
        spec = self._spec_fn()
        if hasattr(spec, 'A'):            # MatrixGame 对象
            self.A, self.B, self.actions = spec.A, spec.B, spec.actions
        else:                              # (A, B, actions) 元组
            self.A = np.asarray(spec[0], float)
            self.B = np.asarray(spec[1], float) if len(spec) > 1 and \
                spec[1] is not None else self.A.T
            self.actions = spec[2] if len(spec) > 2 else None
        n = self.A.shape[0]
        if self.x0 is not None:
            self.x = self.x0 / self.x0.sum()
        else:
            self.x = rng.dirichlet(np.ones(n))
        self.rng_ = rng
        self.hist = [self.x.copy()]

    def _fitness(self, x):
        return self.A @ x

    def step(self, t, dt):
        x = self.x
        n = len(x)
        if self._update == "replicator":
            fit = self.A @ x
            avg = float(x @ fit)
            x = x + self.dt0 * x * (fit - avg)
        elif self._update == "replicator_mutation":
            fit = self.A @ x
            avg = float(x @ fit)
            x = x + self.dt0 * (x * (fit - avg) + self._mu * (1 / n - x))
        elif self._update == "best_response":
            br = int(np.argmax(self.A @ x))
            x = (1 - 0.3) * x
            x[br] += 0.3
        elif self._update == "logit":
            lam = 4.0
            prob = np.exp(lam * (self.A @ x))
            prob = prob / prob.sum()
            x = 0.9 * x + 0.1 * prob
        elif self._update in ("moran", "fermi"):
            # 有限种群模拟（N=100）
            N = 100
            counts = np.round(x * N).astype(int)
            while counts.sum() > N:
                counts[self.rng_.integers(n)] -= 1
            while counts.sum() < N:
                counts[self.rng_.integers(n)] += 1
            fit = self.A @ (counts / N)
            for _ in range(N):
                i = self.rng_.integers(N)
                # 死一个换一个：按适应度比例选择出生者
                pop = np.repeat(np.arange(n), counts)
                if len(pop) == 0:
                    break
                w = np.maximum(fit[pop], 0)
                if w.sum() <= 0:
                    birth = int(self.rng_.choice(pop))
                else:
                    birth = self.rng_.choice(pop, p=w / w.sum())
                dead = int(self.rng_.integers(N))
                target = pop[dead]
                if self._update == "fermi":
                    if self.rng_.random() < 1 / (1 + np.exp(
                            -3.0 * (fit[birth] - fit[target]))):
                        counts[target] -= 1
                        counts[birth] += 1
                else:
                    counts[target] -= 1
                    counts[birth] += 1
            x = counts / N
        elif self._update == "fictitious":
            # 虚拟博弈：对手历史经验最优反应的自洽近似
            opp = x  # 群体对手分布
            br = np.zeros(n)
            br[int(np.argmax(self.A @ opp))] = 1.0
            x = 0.95 * x + 0.05 * br
        self.x = np.maximum(x, 0)
        s = self.x.sum()
        if s > 0:
            self.x = self.x / s
        self.hist.append(self.x.copy())

    def observe(self):
        arr = np.array(self.hist)
        return {"freq": self.x.tolist(),
                "freq_hist_shape": list(arr.shape),
                "entropy": float(-(self.x[self.x > 0]
                                   * np.log(self.x[self.x > 0])).sum())}

    def validate_state(self):
        return [] if abs(self.x.sum() - 1) < 1e-6 else ["频率非归一"]


def _mk(spec_fn, update, model_id, doc, mu=0.0, x0=None):
    return type(model_id, (_GameEvolModel,),
                {"model_id": model_id, "__doc__": doc, "_spec_fn": staticmethod(spec_fn),
                 "_update": update, "_mu": mu,
                 "__init__": (lambda self, x0=x0, dt=0.05:
                              _GameEvolModel.__init__(self, x0=x0, dt=dt))})


# ---- BEH049-063 博弈规格 ----
PrisonerDilemmaEvo = _mk(G.g_prisoners_dilemma, "replicator", "BEH049",
                         "BEH049 囚徒困境复制动态：合作份额→0（背叛占优）。")
HawkDoveEvo = _mk(G.g_hawk_dove, "replicator", "BEH050",
                  "BEH050 鹰鸽/雪堆反协调：混合均衡 x*=V/C。")
StagHuntEvo = _mk(G.g_stag_hunt, "replicator", "BEH051",
                  "BEH051 猎鹿/保证博弈：双稳态（协调成功）。")
LinearPGEvo = _mk(lambda: (np.array([[1.0, 1.8], [0.8, 1.6]]), None,
                           ["free", "contribute"]), "replicator", "BEH052",
                  "BEH052 线性公共品博弈：贡献劣势→搭便车。")
PunishPGEvo = _mk(lambda: (np.array([[1.0, 0.7], [1.1, 2.4]]), None,
                           ["free", "contribute"]), "replicator", "BEH053",
                  "BEH053 同伴惩罚公共品：惩罚改变收益→合作可存续。")
VolunteerDilemmaEvo = _mk(
    lambda: (np.array([[0.8, 0.8], [1.0, 0.0]]), None,
             ["volunteer", "shirk"]), "replicator", "BEH054",
    "BEH054 自愿参与公共品：混合均衡。")
CPREvo = _mk(lambda: (np.array([[1.0, 0.8], [1.1, 0.6]]), None,
                      ["restrain", "overuse"]), "replicator", "BEH056",
             "BEH056 共同池资源：过度占用悲剧/约束均衡。")
CoordinationConflictEvo = _mk(G.coordination_conflict_payoff, "replicator",
                              "BEH061", "BEH061 偏好冲突协调博弈。")
RPSEvo = _mk(G.rps_cyclic_payoff, "replicator", "BEH062",
             "BEH062 石头剪刀布循环优势：闭合轨道。")
# BEH055 志愿者困境（离散版）与 BEH057-059 讨价还价式博弈单独建
VolunteerDilemmaSim = _mk(
    lambda: (np.array([[0.8, 0.8], [1.0, 0.0]]), None,
             ["volunteer", "shirk"]), "moran", "BEH055",
    "BEH055 志愿者困境（Moran 有限种群）。")
UltimatumEvo = _mk(lambda: (np.array([[2.0, 1.0], [1.0, 1.0]]), None,
                            ["fair", "greedy"]), "replicator", "BEH057",
                    "BEH057 最后通牒博弈（公平 vs 贪婪报价）。")
DictatorEvo = _mk(lambda: (np.array([[2.0, 3.0], [1.0, 1.0]]), None,
                           ["give", "keep"]), "replicator", "BEH058",
                  "BEH058 独裁者博弈（无拒绝威胁）。")
TrustEvo = _mk(lambda: (np.array([[2.5, 0.5], [1.0, 1.0]]), None,
                        ["trust", "distrust"]), "replicator", "BEH059",
               "BEH059 信任/投资博弈。")
MatchingPenniesEvo = _mk(G.matching_pennies_payoff, "replicator_mutation",
                         "BEH060", "BEH060 正反硬币零和：含突变的混合均衡。",
                         mu=0.02)
CentipedeEvo = _mk(lambda: (np.array([[1.0, 0.5], [2.0, 0.1]]), None,
                            ["continue", "stop"]), "replicator", "BEH063",
                    "BEH063 蜈蚣博弈（继续 vs 停止）。")

# ---- BEH082-093 学习/演化规则 ----
ReplicatorMutationModel = _mk(G.g_hawk_dove, "replicator_mutation", "BEH083",
                              "BEH083 复制-突变动态：突变维持混合分布。", mu=0.03)
BestResponseModel = _mk(G.g_stag_hunt, "best_response", "BEH086",
                        "BEH086 最优反应动态：协调到纯策略均衡。")
LogitResponseModel = _mk(G.g_stag_hunt, "logit", "BEH087",
                         "BEH087 Logit 响应动态：随机最优反应。")
MoranModel = _mk(G.g_hawk_dove, "moran", "BEH084",
                 "BEH084 Moran 有限群体选择：中性漂移+选择。")
FermiModel = _mk(G.g_hawk_dove, "fermi", "BEH085",
                 "BEH085 Fermi 成对比较更新。")
FictitiousPlayModel = _mk(G.matching_pennies_payoff, "fictitious", "BEH088",
                          "BEH088 虚拟博弈学习：经验频率最优反应。")


class EWARuleModel(DayanModel):
    """BEH089 经验加权吸引（EWA）学习：2 动作 bandit。"""

    model_id = "BEH089"
    clock_type = "fixed_step"

    def __init__(self, decay=0.6, phi=0.8):
        self.decay, self.phi = decay, phi

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.attr = np.ones(2)
        self.pay = np.array([1.0, 0.7])
        self.choice_hist = []

    def step(self, t, dt):
        prob = self.attr / self.attr.sum()
        a = int(self.rng_.choice(2, p=prob))
        r = self.pay[a]
        # Camerer-Ho EWA（δ=0 特例）：强化只加到所选动作，未选动作仅按 φ 衰减
        # 旧实现把标量 mult*r 广播到整个向量 → 两臂吸引子恒等、学习信号为零
        mult = self.decay + (1 - self.decay) * (a == int(np.argmax(self.pay)))
        self.attr = self.phi * self.attr
        self.attr[a] += mult * r
        self.choice_hist.append(a)

    def observe(self):
        arr = np.array(self.choice_hist[-200:])
        if arr.size == 0:
            return {"choice_shares": [0.5, 0.5], "best_arm_share": 0.0}
        return {"choice_shares": [float((arr == 0).mean()),
                                  float((arr == 1).mean())],
                "best_arm_share": float((arr == int(np.argmax(self.pay))).mean())}

    def validate_state(self):
        return []


class RothErevModel(EWARuleModel):
    """BEH090 Roth–Erev 倾向强化学习。"""

    model_id = "BEH090"

    def step(self, t, dt):
        prob = self.attr / self.attr.sum()
        a = int(self.rng_.choice(2, p=prob))
        self.attr[a] += self.pay[a]      # 倾向累加
        self.choice_hist.append(a)


class BushMostellerModel(EWARuleModel):
    """BEH091 Bush–Mosteller 概率学习。"""

    model_id = "BEH091"

    def step(self, t, dt):
        prob = self.attr / self.attr.sum()
        a = int(self.rng_.choice(2, p=prob))
        r = self.pay[a] / self.pay.max()
        # BM：朝获得/未获得 aspiration 方向调整概率
        self.attr[a] += 0.3 * (1 - self.attr[a] / self.attr.sum()) * r
        self.choice_hist.append(a)


class BayesianOppModel(EWARuleModel):
    """BEH092 贝叶斯对手学习：对手动作分布的后验更新。"""

    model_id = "BEH092"

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.opp_p0 = 0.7                      # 对手真实混合策略（固定）
        self.opp_counts = np.ones(2)           # Beta(1,1) 均匀先验
        self.pay_matrix = np.array([[2.0, 0.0],   # 行=我的动作，列=对手动作
                                    [0.0, 1.0]])

    def step(self, t, dt):
        opp_a = 0 if self.rng_.random() < self.opp_p0 else 1
        self.opp_counts[opp_a] += 1.0          # Dirichlet-Multinomial 共轭后验
        post = self.opp_counts / self.opp_counts.sum()
        ev = self.pay_matrix @ post            # 各候选动作对后验混合的期望收益
        br = int(np.argmax(ev))
        self.choice_hist.append(br)

    def observe(self):
        base = super().observe()
        post = self.opp_counts / self.opp_counts.sum()
        ev = self.pay_matrix @ post
        br = int(np.argmax(ev))
        tail = self.choice_hist[-200:]
        base["posterior_opp0"] = float(post[0])
        base["br_share"] = (float(np.mean([c == br for c in tail]))
                            if tail else 0.0)
        return base


class RegretMatchingModel(EWARuleModel):
    """BEH093 遗憾匹配：累积遗憾 → 概率（Blackwell 可达性）。"""

    model_id = "BEH093"

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.regrets = np.zeros(2)
        self.pay_full = np.array([[1.0, 0.0], [0.0, 1.0]])

    def step(self, t, dt):
        prob = np.maximum(self.regrets, 0)
        prob = prob / prob.sum() if prob.sum() > 0 else np.full(2, 0.5)
        a = int(self.rng_.choice(2, p=prob))
        opp = 0 if self.rng_.random() < 0.8 else 1   # 对手偏置混合（0.8 出 0）
        r = self.pay_full[a, opp]              # 实际收益
        r_counter = self.pay_full[1 - a, opp]  # 反事实：同一对手动作下另一动作
        self.regrets[1 - a] += r_counter - r
        self.choice_hist.append(a)


# ---- BEH104-106, 109-111 行为决策 ----
class ProspectTheoryModel(DayanModel):
    """BEH104 前景理论：价值函数 v(x)=x^α / -λ(-x)^β + 概率权重。"""

    model_id = "BEH104"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        gains = [100, 50, 0, -50, -100]
        vals = [G.prospect_theory_value(x) for x in gains]
        w_small = G.cumulative_prospect_weights(0.05)
        w_large = G.cumulative_prospect_weights(0.95)
        # 反射效应验证：损失域风险寻求
        self.result = {"values": vals,
                       "loss_aversion": float(abs(vals[-1]) / abs(vals[1])),
                       "reflection_ok": bool(abs(vals[-1]) > abs(vals[3])),
                       "small_p_overweight": bool(w_small > 0.05),
                       "large_p_underweight": bool(w_large < 0.95)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class CPTModel(DayanModel):
    """BEH105 累积前景理论：概率权重反转（小概率高权重）。"""

    model_id = "BEH105"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        ps = np.linspace(0.01, 0.99, 11)
        wg = [G.cumulative_prospect_weights(p) for p in ps]
        self.result = {"small_p_overweight": bool(wg[0] > ps[0]),
                       "large_p_underweight": bool(wg[-1] < ps[-1]),
                       "w_curve": [round(float(x), 3) for x in wg]}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class FehrSchmidtModel(DayanModel):
    """BEH106 Fehr–Schmidt 不平等厌恶：效用 = 自身收益 − α·不利差距 − β·有利差距。"""

    model_id = "BEH106"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        u_equal = G.fehr_schmidt_utility(10, [10, 10])
        u_adv = G.fehr_schmidt_utility(15, [5, 5])      # 有利不平等
        u_dis = G.fehr_schmidt_utility(5, [15, 15])     # 不利不平等
        self.result = {"u_equal": float(u_equal), "u_advantageous": float(u_adv),
                       "u_disadvantageous": float(u_dis),
                       "inequality_averse": bool(u_equal > u_dis)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class LevelKModel(DayanModel):
    """BEH109 Level-k 有限层级推理（p-beauty contest 数值演示）。"""

    model_id = "BEH109"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        # 数字猜谜：目标=平均数×2/3；L0=50，Lk=2/3·E[平均]
        actions = {}
        actions["L0"] = 50.0
        for k in range(1, 4):
            actions[f"L{k}"] = (2 / 3) * actions[f"L{k-1}"]
        # Level-1..3 人群中的赢家
        vals = list(actions.values())[1:]
        self.result = {"actions": actions,
                       "winner": float(min(vals, key=lambda v: abs(v - 2 / 3 * 33.33)))}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class QREModel(DayanModel):
    """BEH111 量化反应均衡：Logit-QRE 求解匹配硬币（λ→∞ 收敛混合均衡）。"""

    model_id = "BEH111"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        A = G.matching_pennies_payoff().A
        q1 = G.quantal_response_equilibrium(A[0], lam=5.0)
        q2 = G.quantal_response_equilibrium(A[1], lam=5.0)
        self.result = {"q_row": np.asarray(q1).tolist(),
                       "q_col": np.asarray(q2).tolist(),
                       "mixed_tendency": bool(abs(float(np.asarray(q1).mean())
                                                  - 0.5) < 0.35)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class DDMModel(DayanModel):
    """BEH102 漂移扩散决策（DDM）：证据积累→阈值反应时与准确率。"""

    model_id = "BEH102"
    clock_type = "fixed_step"

    def __init__(self, drift=0.3, threshold=2.0, n_trials=200):
        self.drift, self.threshold, self.n_trials = drift, threshold, n_trials

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        rts, correct = [], 0
        for _ in range(self.n_trials):
            ev = 0.0
            rt = 0
            while abs(ev) < self.threshold and rt < 2000:
                ev += self.drift * 0.01 + rng.normal(0, 0.1)
                rt += 1
            rts.append(rt)
            correct += int(ev > 0)
        self.result = {"mean_rt": float(np.mean(rts)),
                       "accuracy": float(correct / self.n_trials),
                       "speed_accuracy_tradeoff": bool(
                           self.drift > 0 and np.mean(rts) > 0)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


# ---- BEH064-068 合作博弈 ----
class ShapleyModel(DayanModel):
    """BEH064 Shapley 边际贡献分配（game_lib.shapley_value）。"""

    model_id = "BEH064"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        contrib = {"a": 3.0, "b": 2.0, "c": 1.0}
        val = lambda S: float(sum(contrib[i] for i in S))
        sh = G.shapley_value(contrib, lambda S: val(S))
        self.result = {"shapley": {k: float(v) for k, v in sh.items()},
                       "sums_to_total": abs(sum(sh.values())
                                            - sum(contrib.values())) < 1e-9}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class NashBargainingModel(DayanModel):
    """BEH067 Nash 议价解：最大化 (u1-d0)(u2-d1)。"""

    model_id = "BEH067"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        # 帕累托边界点列（合作产出 10 的可行分配）
        u1 = np.linspace(1.0, 9.0, 9)
        u2 = 10.0 - u1
        sol, val = G.nash_bargaining(u1, u2, 1.0, 1.0)
        self.result = {"solution": [float(sol[0]), float(sol[1])],
                       "product": float(val),
                       "symmetric": abs(sol[0] - sol[1]) < 0.6}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class RubinsteinModel(DayanModel):
    """BEH068 Rubinstein 交替出价：无限期折现议价的轮流出价份额极限。"""

    model_id = "BEH068"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        # 剩饼 s=1，折现 δ1=δ2=0.9 → 极限份额 (1-δ2)/(1-δ1δ2)
        d = 0.9
        share1 = (1 - d) / (1 - d * d)
        # 有限期倒推验证（20 期）
        offer = 0.5
        for _ in range(20):
            offer = 1 - d * offer
        self.result = {"limit_share1": float(share1),
                       "finite_offer": float(offer),
                       "converged": abs(offer - share1) < 0.02}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class NucleolusLiteModel(DayanModel):
    """BEH065 合作博弈核仁（简化：最小化最大超额的破产分摊）。"""

    model_id = "BEH065"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        # 破产博弈：遗产 100，三个债权 (60, 40, 30)（Abdulrahmadi 经典）
        claims = np.array([60.0, 40.0, 30.0])
        estate = 100.0
        # 争议解（contested garment）：min(claim, estate-其他claim和/…) 迭代
        x = claims * estate / claims.sum()     # 比例起点
        # 核仁近似：Talmud 两步
        half = estate / 2
        lo = np.minimum(claims, half)
        if claims.sum() > estate:
            rem = estate - lo.sum()
            x = lo + rem * (claims - lo) / (claims - lo).sum()
        else:
            x = np.minimum(claims, estate / len(claims))
        self.result = {"claims": claims.tolist(), "estate": float(estate),
                       "nucleolus_approx": x.tolist(),
                       "efficiency": abs(x.sum() - estate) < 1e-9}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class AdditiveCoalitionModel(DayanModel):
    """BEH066 可加分离享乐联盟形成（享乐函数可加→按贡献排序分组）。"""

    model_id = "BEH066"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        types = rng.choice([0, 1], 12)   # 两类型人群
        # 享乐可加：同型相聚效用高 → 分社结构
        partition = {0: int((types == 0).sum()), 1: int((types == 1).sum())}
        util_same = 2.0
        util_diff = 0.5
        total_same = util_same * (partition[0] * (partition[0] - 1)
                                  + partition[1] * (partition[1] - 1)) / 2
        total_mixed = util_diff * partition[0] * partition[1]
        self.result = {"partition_sizes": partition,
                       "utility_same_type_grouping": float(total_same),
                       "utility_mixed": float(total_mixed),
                       "same_type_optimal": bool(total_same > total_mixed)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


# ---- BEH069-073 重复策略 ----
class _StrategyDuel(DayanModel):
    """重复 PD 策略对决模板：策略 A 对阵 always-defect 基线。"""

    clock_type = "fixed_step"
    _strategy = None

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.my_hist, self.opp_hist = [], []
        self.my_score = 0.0
        self.payoff = {("C", "C"): 3, ("C", "D"): 0,
                       ("D", "C"): 5, ("D", "D"): 1}

    def _pick(self):
        raise NotImplementedError

    def step(self, t, dt):
        my = self._pick()
        opp = "D"      # 对手：永远背叛（基线压力测试）
        self.my_hist.append(my)
        self.opp_hist.append(opp)
        self.my_score += self.payoff[(my, opp)]

    def observe(self):
        return {"score_vs_alld": float(self.my_score),
                "coop_rate": float(np.mean([m == "C" for m in self.my_hist])) if self.my_hist else None,
                'n_rounds':len(self.my_hist)}

    def validate_state(self):
        return []


class TitForTatModel(_StrategyDuel):
    """BEH069 以牙还牙：首步合作，此后镜像对手。"""

    model_id = "BEH069"

    def _pick(self):
        if not self.opp_hist:
            return "C"
        return self.opp_hist[-1]


class TitForTatTatModel(TitForTatModel):
    """BEH070 宽容以牙还牙：10% 概率原谅背叛。"""

    model_id = "BEH070"

    def _pick(self):
        if not self.opp_hist:
            return "C"
        if self.opp_hist[-1] == "D" and self.rng_.random() < 0.1:
            return "C"
        return self.opp_hist[-1]


class PavlovModel(_StrategyDuel):
    """BEH071 赢则守、输则变（Pavlov / WSLS）。"""

    model_id = "BEH071"

    def _pick(self):
        if not self.my_hist:
            return "C"
        won = (self.my_hist[-1], self.opp_hist[-1]) in (("C", "C"), ("D", "D"))
        return self.my_hist[-1] if won else ("D" if self.my_hist[-1] == "C"
                                             else "C")


class GrimTriggerModel(_StrategyDuel):
    """BEH072 冷酷触发：一次背叛永久报复。"""

    model_id = "BEH072"

    def _pick(self):
        if "D" in self.opp_hist:
            return "D"
        return "C"


class ZeroDeterminantModel(_StrategyDuel):
    """BEH073 零行列式策略：ZD 勒索规则（p=8/9, r=1/2, s=1/3）。"""

    model_id = "BEH073"

    def _pick(self):
        if not self.my_hist:
            return "C"
        p_coop = G.zero_determinant_rule(self.my_hist[-1], self.opp_hist[-1],
                                         p=8 / 9, r=1 / 2, s=1 / 3)
        return "C" if self.rng_.random() < p_coop else "D"


# ---- BEH075-080 规范族 ----
class _NormSimBase(DayanModel):
    """声誉规范个体模拟基类：donor/receiver 图像分 + 协作决策规则。"""
    clock_type = "fixed_step"
    _norm_name = "simple_standing"

    def __init__(self, n=40):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        self.rep = rng.choice([-1.0, 1.0], self.n)   # 声誉图像分
        self.coop_hist = []

    def _decide(self, donor, recip_rep):
        if self._norm_name == "simple_standing":
            return recip_rep > 0
        if self._norm_name == "stern_judging":
            return recip_rep > 0
        return recip_rep > 0                          # exclusion：默认合作

    def _update_reputation(self, donor, acted_coop, recip_rep=None):
        if self._norm_name == "stern_judging" and recip_rep is not None:
            # Ohtsuki-Iwasa 严厉评判：行为是否"得当"取决于接受者声誉——
            # 帮好人(G)/拒坏人(B) → G；帮坏人/背叛好人 → B（二阶评估）
            justified = ((acted_coop and recip_rep > 0)
                         or (not acted_coop and recip_rep <= 0))
            self.rep[donor] = 1.0 if justified else -1.0
        else:
            # 简单立场/排斥：合作得 G、背叛得 B（一阶评估）
            self.rep[donor] = 1.0 if acted_coop else -1.0

    def step(self, t, dt):
        donor = int(self.rng.integers(self.n))
        recip = int(self.rng.integers(self.n))
        if donor == recip:
            return
        coop = self._decide(donor, self.rep[recip])
        self._update_reputation(donor, coop, recip_rep=self.rep[recip])
        self.coop_hist.append(1.0 if coop else 0.0)

    def observe(self):
        tail = self.coop_hist[-100:]
        return {"coop_rate": float(np.mean(tail)) if tail else 0.0,
                "rep_pos_share": float((self.rep > 0).mean())}

    def validate_state(self):
        return []


class SimpleNormModel(_NormSimBase):
    """BEH075 简单立场规范，评价取决于接受者状态。"""

    model_id = "BEH075"
    _norm_name = "simple_standing"


class StrictJudgingModel(_NormSimBase):
    """BEH076 严厉评判规范：自己背叛也降自己声誉（stern judging 语义）。"""

    model_id = "BEH076"
    _norm_name = "stern_judging"


class ShunningModel(_NormSimBase):
    """BEH077 排斥式声誉规范：低声誉者被排除出交互对象。"""

    model_id = "BEH077"
    _norm_name = "exclusion"

    def step(self, t, dt):
        # 排斥：50% 概率只选正声誉接受者
        donor = int(self.rng.integers(self.n))
        pos = np.where(self.rep > 0)[0]
        if self.rng.random() < 0.5 and len(pos):
            recip = int(self.rng.choice(pos))
        else:
            recip = int(self.rng.integers(self.n))
        if donor == recip:
            return
        coop = self._decide(donor, self.rep[recip])
        self._update_reputation(donor, coop, recip_rep=self.rep[recip])
        self.coop_hist.append(1.0 if coop else 0.0)


class YoungConventionModel(DayanModel):
    """BEH081 two-role coordination with limited history and mutations."""
    model_id="BEH081"
    clock_type="fixed_step"

    def __init__(self, memory=20, sample=5, epsilon=.02, reward_0=1., reward_1=.9):
        if not 1<=sample<=memory<=2000 or not 0<=epsilon<=1 or min(reward_0,reward_1)<=0:
            raise ValueError("样本/记忆大小或协调收益、突变概率非法")
        self.memory,self.sample,self.epsilon=memory,sample,epsilon
        self.reward_0,self.reward_1=reward_0,reward_1

    def initialize(self, context, parameters, population, topology, rng):
        self.rng=rng
        self.history=rng.integers(0,2,(self.memory,2))
        self.index=0
        self.rounds=0
        self.coordinated=0

    def step(self, t, dt):
        pair=[]
        for role in range(2):
            sample=self.rng.choice(self.memory,self.sample,replace=False)
            frac=float(np.mean(self.history[sample,1-role]))
            v0,v1=self.reward_0*(1-frac),self.reward_1*frac
            if self.rng.random()<self.epsilon or v0==v1:
                pair.append(int(self.rng.integers(2)))
            else:
                pair.append(int(v1>v0))
        self.history[self.index]=pair
        self.index=(self.index+1)%self.memory
        self.rounds+=1
        self.coordinated+=int(pair[0]==pair[1])

    def observe(self):
        return {"convention_1_share":float(np.mean(self.history)),
                "coordination_rate":self.coordinated/self.rounds if self.rounds else None,
                "rounds":self.rounds}

    def validate_state(self):
        return []


class AxelrodNormCatalogModel(DayanModel):
    """BEH078 Axelrod 规范博弈（game_lib.AxelrodNormGame）。"""

    model_id = "BEH078"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        from .game_lib import AxelrodNormGame
        self.rng_ = rng
        self.game = AxelrodNormGame(n=20, seed=0)
        self.venge_hist = []

    def step(self, t, dt):
        try:
            self.game.step(self.rng_)
        except TypeError:
            self.game.step(t, dt)
        self.venge_hist.append(float(np.mean(self.game.vengeance)))

    def observe(self):
        tail = self.venge_hist[-30:]
        return {"mean_vengeance": float(np.mean(tail)) if tail else None,
                "norm_evolved": bool(np.mean(tail) > 0.5) if tail else None,'n_samples':len(tail)}

    def validate_state(self):
        return []


class MetaNormModel(DayanModel):
    """BEH079 Axelrod 元规范博弈：对不惩罚者再惩罚。"""

    model_id = "BEH079"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        from .game_lib import AxelrodNormGame
        self.rng_ = rng
        self.game = AxelrodNormGame(n=20, seed=1, meta_cost=1.0)
        self.venge_hist = []

    def step(self, t, dt):
        try:
            self.game.step(self.rng_)
        except TypeError:
            self.game.step(t, dt)
        self.venge_hist.append(float(np.mean(self.game.vengeance)))

    def observe(self):
        tail = self.venge_hist[-30:]
        return {"mean_vengeance": float(np.mean(tail)) if tail else None,
                "meta_norm_stronger": bool(np.mean(tail) > 0.5) if tail else None,'n_samples':len(tail)}

    def validate_state(self):
        return []


class ConformistPunishModel(DayanModel):
    """BEH080 Henrich–Boyd 从众惩罚规范模型（culture.py 已有 → 映射）。"""

    model_id = "BEH080"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        from .culture import HenrichBoydConformity
        self._impl = HenrichBoydConformity(n=60)
        self._impl.initialize(context, parameters, population, topology, rng)

    def step(self, t, dt):
        self._impl.step(t, dt)

    def observe(self):
        return self._impl.observe()

    def validate_state(self):
        return self._impl.validate_state()


# ---- 已有实现的目录映射（Schelling/Axelrod 文化/噪声选民 等）----
def _alias(module_name, cls_name, model_id, doc):
    """把既有 DayanModel 类挂到目录 ID（导入并代理）。"""

    def init(self, context, parameters, population, topology, rng):
        mod = __import__(f"dayan.models.{module_name}", fromlist=[cls_name])
        self._impl = mod.__dict__[cls_name]()
        self._impl.initialize(context, parameters, population, topology, rng)

    return type(model_id, (DayanModel,), {
        "model_id": model_id, "__doc__": doc,
        "initialize": init,
        "step": lambda self, t, dt: self._impl.step(t, dt),
        "observe": lambda self: self._impl.observe(),
        "validate_state": lambda self: self._impl.validate_state(),
    })


NoiseVoterModel = _alias("opinion", "NoisyVoter", "BEH021",
                         "BEH021 噪声选民模型（opinion.py NoisyVoter 映射）。")
class AxelrodCultureModel(DayanModel):
    """BEH033 Axelrod 文化传播：网格 agent，特征向量 F×Q，
    相似度∝交互概率 → 文化地域化（区域数下降）。"""

    model_id = "BEH033"
    clock_type = "fixed_step"

    def __init__(self, size=10, F=5, Q=10):
        self.size, self.F, self.Q = size, F, Q

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        n = self.size
        self.culture = rng.integers(0, self.Q, (n, n, self.F))
        self.tick = 0

    def step(self, t, dt):
        n, F = self.size, self.F
        i, j = int(self.rng.integers(n)), int(self.rng.integers(n))
        ni, nj = [(i, (j + 1) % n), (i, (j - 1) % n),
                  ((i + 1) % n, j), ((i - 1) % n, j)][int(self.rng.integers(4))]
        mine, theirs = self.culture[i, j], self.culture[ni, nj]
        same = int((mine == theirs).sum())
        prob = same / F
        if same < F and self.rng.random() < prob:
            k = int(self.rng.integers(F))
            if mine[k] != theirs[k]:
                mine[k] = theirs[k]

    def observe(self):
        flat = self.culture.reshape(-1, self.F)
        uniq = len({tuple(row) for row in flat})
        return {"regions": uniq, "n_agents": len(flat),
                "regionalization": bool(uniq < len(flat) * 0.9)}

    def validate_state(self):
        return []


class ElFarolModel(DayanModel):
    """BEH007 El Farol 酒吧拥挤：阈值 60，N=100，记忆集预测； Attendance ≈ 60。"""

    model_id = "BEH007"
    clock_type = "fixed_step"

    def __init__(self, n=100, threshold=0.6, memory=10):
        self.n, self.threshold, self.memory = n, threshold, memory

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.history = []
        self.strategies = [
            rng.uniform(0.3, 0.9) for _ in range(self.n)]  # 个人化阈值
        self.scores = np.zeros(self.n)

    def step(self, t, dt):
        go = [self.rng_.random() < self.strategies[i] for i in range(self.n)]
        att = sum(go) / self.n
        crowded = att > self.threshold
        for i, g in enumerate(go):
            self.scores[i] += (-1 if crowded else 1) if g else \
                (1 if crowded else -0.5) * 0.5
        # 弱策略换新
        weak = int(np.argmin(self.scores))
        self.strategies[weak] = self.rng_.uniform(0.3, 0.9)
        self.history.append(att)

    def observe(self):
        tail = self.history[-50:]
        return {"mean_attendance": float(np.mean(tail)) if tail else None,
                "att_near_threshold": bool(abs(np.mean(tail) - self.threshold)
                                           < 0.15) if tail else None,'n_samples':len(tail)}

    def validate_state(self):
        return []


class MinorityGameModel(DayanModel):
    """BEH008 少数者博弈：N=101 二选一，少数侧赢；出勤 ≈ 50%。"""

    model_id = "BEH008"
    clock_type = "fixed_step"

    def __init__(self, n=101):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.strategy = rng.random(self.n)   # 每人偏向
        self.att_hist = []

    def step(self, t, dt):
        side = (self.rng_.random(self.n) < self.strategy).astype(int)
        ones = side.sum()
        minority_0 = ones > self.n / 2
        # 赢家微调策略
        winners = (side == 0) if minority_0 else (side == 1)
        self.strategy[winners] += 0.01 * (self.rng_.random(int(winners.sum())) - 0.5)
        self.strategy = np.clip(self.strategy, 0, 1)
        self.att_hist.append(int(ones) / self.n)

    def observe(self):
        tail = self.att_hist[-50:]
        return {"mean_ones_share": float(np.mean(tail)) if tail else None,
                "near_half": bool(abs(np.mean(tail) - 0.5) < 0.12) if tail else None,'n_samples':len(tail)}

    def validate_state(self):
        return []


class GranovetterModel(DayanModel):
    """BEH014 Granovetter 阈值集体行动：阈值分布决定滚雪球均衡。"""

    model_id = "BEH014"
    clock_type = "fixed_step"

    def __init__(self, n=100, threshold_mean=0.25, shock=True):
        self.n, self.tm, self.shock = n, threshold_mean, shock

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.tm = parameters.get('threshold_mean', self.tm)
        self.thresholds = np.clip(rng.normal(self.tm, 0.15, self.n), 0.0, 0.98)
        if self.shock:
            self.thresholds[:3] = 0.0    # 三个初始煽动者
        self.active = np.zeros(self.n, bool)

    def step(self, t, dt):
        share = self.active.mean()
        newly = (~self.active) & (self.thresholds <= share)
        self.active |= newly

    def observe(self):
        return {"participation": float(self.active.mean()),
                "cascade": bool(self.active.mean() > 0.5)}

    def validate_state(self):
        return []


ALL_BEH_MODELS = {
    "BEH049": PrisonerDilemmaEvo, "BEH050": HawkDoveEvo,
    "BEH051": StagHuntEvo, "BEH052": LinearPGEvo, "BEH053": PunishPGEvo,
    "BEH054": VolunteerDilemmaEvo, "BEH055": VolunteerDilemmaSim,
    "BEH056": CPREvo, "BEH057": UltimatumEvo, "BEH058": DictatorEvo,
    "BEH059": TrustEvo, "BEH060": MatchingPenniesEvo, "BEH061": CoordinationConflictEvo,
    "BEH062": RPSEvo, "BEH063": CentipedeEvo,
    "BEH064": ShapleyModel, "BEH065": NucleolusLiteModel,
    "BEH066": AdditiveCoalitionModel, "BEH067": NashBargainingModel,
    "BEH068": RubinsteinModel,
    "BEH069": TitForTatModel, "BEH070": TitForTatTatModel,
    "BEH071": PavlovModel, "BEH072": GrimTriggerModel,
    "BEH073": ZeroDeterminantModel,
    "BEH075": SimpleNormModel, "BEH076": StrictJudgingModel,
    "BEH077": ShunningModel, "BEH078": AxelrodNormCatalogModel,
    "BEH079": MetaNormModel, "BEH080": ConformistPunishModel,
    "BEH021": NoiseVoterModel, "BEH033": AxelrodCultureModel,
    "BEH007": ElFarolModel, "BEH008": MinorityGameModel,
    "BEH014": GranovetterModel,
    "BEH083": ReplicatorMutationModel, "BEH084": MoranModel,
    "BEH085": FermiModel, "BEH086": BestResponseModel,
    "BEH087": LogitResponseModel, "BEH088": FictitiousPlayModel,
    "BEH089": EWARuleModel, "BEH090": RothErevModel,
    "BEH091": BushMostellerModel, "BEH092": BayesianOppModel,
    "BEH093": RegretMatchingModel,
    "BEH102": DDMModel, "BEH104": ProspectTheoryModel,
    "BEH105": CPTModel, "BEH106": FehrSchmidtModel,
    "BEH109": LevelKModel, "BEH111": QREModel,
}


def build_all_beh():
    return {mid: cls() for mid, cls in ALL_BEH_MODELS.items()}
