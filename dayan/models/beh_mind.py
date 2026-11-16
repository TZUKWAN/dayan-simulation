"""认知架构与生成式主体骨架（BEH094-101、129-135）。

LLM 主体（BEH129-133）：真实API调用、模拟工具行动与反馈（ReAct 环、反思记忆、
技能库生长等机制真实运行）；LLM 适配器接口留空，未来即插即用。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class _Base(DayanModel):
    clock_type = "fixed_step"

    def observe(self):
        return {k: v for k, v in self.result.items()}

    def validate_state(self):
        return []


class BDIAgentFullModel(_Base):
    """BEH094 信念—愿望—意图 BDI 架构：信念更新 → 愿望排序 → 意图承诺。"""

    model_id = "BEH094"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.beliefs = {"supply": 0.5, "demand": 0.8}
        self.desires = {"restock": 0.6, "price_up": 0.9}
        self.intentions = []
        self.deliberate()

    def deliberate(self):
        # 愿望按 信念一致性×效用 排序 → 意图承诺
        scores = {}
        scores["restock"] = self.desires["restock"] * (1 - self.beliefs["supply"])
        scores["price_up"] = self.desires["price_up"] * self.beliefs["demand"]
        self.intentions = sorted(scores, key=scores.get, reverse=True)

    def step(self, t, dt):
        # 行动改变信念（restock 提升供给）
        if self.intentions and self.intentions[0] == "restock":
            self.beliefs["supply"] = min(1.0, self.beliefs["supply"] + 0.1)
        self.deliberate()

    def observe(self):
        return {"intentions": self.intentions, "beliefs": self.beliefs}


class ACTRModel(_Base):
    """BEH095 ACT-R lite：陈述性块激活 B=ln(Σ t^-d)+噪声，检索竞争。"""

    model_id = "BEH095"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        # 块：最近使用时刻列表
        self.chunks = {"ch1": [3.0, 6.0], "ch2": [8.0], "ch3": [1.0]}
        self.time = 10.0
        self.d = 0.5
        self.retrievals = []
        self.result = {}

    def _activation(self, chunk):
        times = np.array(self.chunks[chunk])
        base = np.log((times ** -self.d).sum() + 1e-9)
        noise = self.rng_.normal(0, 0.3)
        return base + noise

    def step(self, t, dt):
        self.time += dt
        # 检索：激活最高者胜
        acts = {c: self._activation(c) for c in self.chunks}
        winner = max(acts, key=acts.get)
        self.chunks[winner].append(self.time)
        self.retrievals.append(winner)

    def observe(self):
        from collections import Counter
        c = Counter(self.retrievals)
        return {"retrieval_freq": dict(c),
                "dominant": c.most_common(1)[0][0] if c else None}

    def validate_state(self):
        return []


class SoarLiteModel(_Base):
    """BEH096 Soar lite：问题空间+产生式匹配；平局僵局 → 学习新算子偏好。"""

    model_id = "BEH096"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.state = "start"
        self.preferences = {"go_left": 0.5, "go_right": 0.5}
        self.impasse_count = 0
        self.solved = False

    def step(self, t, dt):
        if self.state == "solved":
            return
        # 产生式匹配：两个算子平局 → 僵局
        best = max(self.preferences, key=self.preferences.get)
        others = {k: v for k, v in self.preferences.items() if k != best}
        if abs(self.preferences[best] - max(others.values())) < 0.05:
            self.impasse_count += 1
            # 僵局解决：偏好微调（学习）
            self.preferences[best] += 0.05
        else:
            self.state = {"go_left": "solved_left", "go_right": "solved_right"}[best]
            self.solved = True

    def observe(self):
        return {"state": self.state, "impasse_count": self.impasse_count,
                "solved": self.solved}

    def validate_state(self):
        return []


class CLARIONModel(_Base):
    """BEH097 CLARION 双层：隐层 RC（Q 式）+ 显层规则抽取（自底向上）。"""

    model_id = "BEH097"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.q_values = np.zeros(2)        # 隐层
        self.rules = []                    # 显层规则 ("state→action")
        self.pay = np.array([0.8, 0.4])
        self.hist = []

    def step(self, t, dt):
        # 隐层选择
        a = int(np.argmax(self.q_values + self.rng_.normal(0, 0.1, 2)))
        r = self.pay[a]
        self.q_values[a] += 0.1 * (r - self.q_values[a])
        # 自底向上规则抽取：Q 差异显著 → 固化规则
        if self.q_values.max() - self.q_values.min() > 0.25 and \
                ("best" not in self.rules):
            self.rules.append("best")
        self.hist.append(a)

    def observe(self):
        return {"implicit_Q": self.q_values.tolist(),
                "explicit_rules": self.rules,
                "rule_extracted": bool(self.rules)}

    def validate_state(self):
        return []


class SigmaFactorGraphModel(_Base):
    """BEH098 Sigma 因子图认知架构：和积消息传递推断隐变量。"""

    model_id = "BEH098"

    def initialize(self, context, parameters, population, topology, rng):
        # 因子图：X — f1 — Y — f2 — Z；观测 Z=1 → 传递推断 X
        self.prior_X = np.array([0.7, 0.3])
        self.cond_f1 = np.array([[0.8, 0.2], [0.3, 0.7]])   # P(Y|X)
        self.cond_f2 = np.array([[0.9, 0.1], [0.4, 0.6]])   # P(Z|Y)
        self.obs_Z = 0
        # 和积推断（demo 协议：initialize 即完成推断）
        m_from_Z = np.array([1.0 if i == self.obs_Z else 0.0 for i in range(2)])
        msg_Y = self.cond_f2 @ m_from_Z
        belief_Y = self.cond_f1.T @ self.prior_X * msg_Y
        belief_Y = belief_Y / max(belief_Y.sum(), 1e-12)
        belief_X = self.cond_f1 @ belief_Y
        belief_X = belief_X / max(belief_X.sum(), 1e-12)
        self.result = {"belief_X": belief_X.round(3).tolist(),
                       "belief_Y": belief_Y.round(3).tolist()}
        self._msg_done = True

    def initialize_run(self):
        pass

    def initialize_step(self):
        pass

    def step(self, t, dt):
        if getattr(self, "_msg_done", False):
            return
        # 和积：m_XY = prior；m_YZ = f1^T m_XY …
        m_from_X = self.prior_X
        m_from_Z = np.array([1.0 if i == self.obs_Z else 0.0 for i in range(2)])
        msg_Y = self.cond_f2 @ m_from_Z                     # 来自观测的信念
        belief_Y = self.cond_f1.T @ m_from_X * msg_Y
        belief_Y = belief_Y / max(belief_Y.sum(), 1e-12)
        belief_X = self.cond_f1 @ belief_Y
        belief_X = belief_X / max(belief_X.sum(), 1e-12)
        self.result = {"belief_X": belief_X.round(3).tolist(),
                       "belief_Y": belief_Y.round(3).tolist()}

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class OCCModel(_Base):
    """BEH099 OCC 情绪评价：事件→目标一致性 + 期望 → 22 情绪空间子集。"""

    model_id = "BEH099"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.emotions = {}

    def appraise(self, goal_congruence, expected, actual):
        """简化 OCC： joy/distress(结果)、hope/fear(预期)、relief/disappointment。"""
        e = {}
        if goal_congruence > 0:
            e["joy"] = goal_congruence
        else:
            e["distress"] = -goal_congruence
        if actual is None:
            if expected > 0:
                e["hope"] = expected
            else:
                e["fear"] = -expected
        else:
            delta = (1 if goal_congruence > 0 else -1) * (actual - 0.5)
            if delta > 0 and expected > 0:
                e["satisfaction"] = delta
            elif delta < 0 and expected > 0:
                e["disappointment"] = -delta
        return e

    def step(self, t, dt):
        # 两事件评价：好消息确认 / 坏消息未预期
        self.emotions = self.appraise(+0.8, +0.6, +0.9)
        e2 = self.appraise(-0.4, -0.3, None)
        for k, v in e2.items():
            self.emotions[k] = self.emotions.get(k, 0) + v

    def observe(self):
        return {"emotions": {k: round(v, 3) for k, v in self.emotions.items()},
                "n_emotions": len(self.emotions)}

    def validate_state(self):
        return []


class PECSModel(_Base):
    """BEH100 PECS 参考架构：物理→情绪→认知→感应 优先级排序驱动行为。"""

    model_id = "BEH100"

    def initialize(self, context, parameters, population, topology, rng):
        self.needs = {"energy": 0.3, "social": 0.6, "safety": 0.8}
        self.behavior = None

    def step(self, t, dt):
        # PECS 顺序：物理需求(能量) > 安全 > 社交
        if self.needs["energy"] < 0.4:
            self.behavior = "eat"
            self.needs["energy"] += 0.1
        elif self.needs["safety"] < 0.5:
            self.behavior = "shelter"
            self.needs["safety"] += 0.1
        else:
            self.behavior = "socialize"
            self.needs["social"] = min(1.0, self.needs["social"] + 0.05)
            self.needs["energy"] -= 0.02

    def observe(self):
        return {"behavior": self.behavior, "needs": self.needs}

    def validate_state(self):
        return []


class ConsumatModel(_Base):
    """BEH101 Consumat：需要×能力 → 7 策略矩阵（重复/模仿/深思/社会比较…）。"""

    model_id = "BEH101"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.need = rng.uniform(0, 1)
        self.ability = rng.uniform(0.2, 1.0)
        self.strategy = None

    def step(self, t, dt):
        # 策略选择：高需要+低能力=模仿；高能力=深思；低需要=重复
        if self.need < 0.3:
            self.strategy = "repetition"
        elif self.need > 0.6 and self.ability > 0.5:
            self.strategy = "deliberation"
        elif self.need > 0.6 and self.ability <= 0.5:
            self.strategy = "imitation"
        else:
            self.strategy = "social_comparison"
        # 需求随行为满足
        if self.strategy == "deliberation":
            self.need = max(0, self.need - 0.2)
        elif self.strategy == "imitation":
            self.need = max(0, self.need - 0.1)
        self.need = min(1.0, self.need + 0.02)

    def observe(self):
        return {"strategy": self.strategy, "need": float(self.need)}

    def validate_state(self):
        return []


# BEH129-133 use real bounded API calls and evolving simulation state.
from .generative import (GenerativeAgentModel, ReActModel, ReflexionModel,
                         VoyagerSkillLibraryModel, ConcordiaModel)


class GraphRAGModel(_Base):
    """BEH134 GraphRAG：知识图谱检索增强（实体→关系→证据汇聚）。"""

    model_id = "BEH134"

    def initialize(self, context, parameters, population, topology, rng):
        # 微型知识图谱：实体→关系→实体
        self.graph = {
            "爱因斯坦": {"提出": ["相对论"], "生于": ["乌尔姆"]},
            "相对论": {"属于": ["物理学"]},
            "乌尔姆": {"位于": ["德国"]},
        }
        query = "爱因斯坦 的理论属于什么领域"
        # 1 跳 + 2 跳检索
        evidence = []
        ent = "爱因斯坦"
        for rel, objs in self.graph[ent].items():
            evidence.append(f"{ent}-{rel}-{objs}")
            for o in objs:
                if o in self.graph:
                    for r2, o2 in self.graph[o].items():
                        evidence.append(f"{o}-{r2}-{o2}")
        self.result = {"query": query, "evidence": evidence,
                       "retrieval_2hop": any("物理学" in e for e in evidence)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class NeurosymbolicModel(_Base):
    """BEH135 神经符号代理：MLP 打分 + 规则硬约束否决（规则约束生成）。"""

    model_id = "BEH135"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        # 神经：候选动作打分
        self.scores = rng.uniform(0, 1, 4)
        self.candidates = ["walk", "swim", "fly", "teleport"]
        # 符号规则：无翅膀 → 不能 fly；无传送门 → 不能 teleport
        self.constraints = {"fly": False, "teleport": False}
        chosen = None
        for idx in np.argsort(-self.scores):
            act = self.candidates[idx]
            if self.constraints.get(act, True):
                chosen = act
                break
        self.result = {"scores": self.scores.round(2).tolist(),
                       "chosen": chosen,
                       "rule_respected": bool(chosen in ("walk", "swim"))}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


ALL_MIND_MODELS = {
    "BEH094": BDIAgentFullModel, "BEH095": ACTRModel, "BEH096": SoarLiteModel,
    "BEH097": CLARIONModel, "BEH098": SigmaFactorGraphModel,
    "BEH099": OCCModel, "BEH100": PECSModel, "BEH101": ConsumatModel,
    "BEH129": GenerativeAgentModel, "BEH130": ReActModel,
    "BEH131": ReflexionModel, "BEH132": VoyagerSkillLibraryModel,
    "BEH133": ConcordiaModel, "BEH134": GraphRAGModel,
    "BEH135": NeurosymbolicModel,
}


def build_all_mind():
    return {mid: cls() for mid, cls in ALL_MIND_MODELS.items()}
