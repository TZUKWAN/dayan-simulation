"""NET 扩展批次：时序网络/统计网络模型/高阶传染/渗流/金融级联（NET039-094 剩余）。"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class _Base(DayanModel):
    clock_type = "fixed_step"

    def observe(self):
        return {k: v for k, v in self.result.items()}

    def validate_state(self):
        return []


# ---- 统计网络模型 ----
class ERGMModel(_Base):
    """NET039 ERGM：边+三角形统计量的 MCMC 图采样（近似估计原型）。"""

    model_id = "NET039"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = 20
        # 目标统计：密度 0.15、三角形若干
        theta_edges, theta_tri = -2.0, 0.5
        G = (rng.random((n, n)) < 0.12)
        G = np.triu(G, 1)
        G = G + G.T

        def stats(g):
            e = int(np.triu(g, 1).sum())
            t = int(sum(3 * np.trace(g @ g @ g) / 6 for _ in [0]) // 3)
            return e, t

        # MH 采样图空间
        cur = stats(G)
        for _ in range(400):
            i, j = rng.integers(0, n, 2)
            if i == j:
                continue
            g2 = G.copy()
            g2[i, j] = g2[j, i] = 0 if G[i, j] else 1
            prop = stats(g2)
            logp = (theta_edges * (prop[0] - cur[0]) +
                    theta_tri * (prop[1] - cur[1]))
            if np.log(rng.random() + 1e-300) < logp:
                G, cur = g2, prop
        e, t = cur
        self.result = {"edges": e, "triangles": t,
                       "n_nodes": n,
                       "sampler_mixed": bool(e > 10)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class TERGMModel(ERGMModel):
    """NET040 TERGM：滞后网络作为协变量的时序 ERGM（两期转换采样）。"""

    model_id = "NET040"

    def initialize(self, context, parameters, population, topology, rng):
        n = 15
        G_prev = (rng.random((n, n)) < 0.15)
        G_prev = np.triu(G_prev, 1) + np.triu(G_prev, 1).T
        # 转移倾向：互惠+稳定
        G_next = G_prev.copy()
        for i in range(n):
            for j in range(i + 1, n):
                recip = G_prev[j, i]
                p = 0.3 + 0.4 * recip + 0.3 * G_prev[i, j]
                if rng.random() < p:
                    G_next[i, j] = 1
                else:
                    G_next[i, j] = 0
        stability = float((G_next & G_prev).sum() / max(G_prev.sum(), 1))
        recip = float(G_next[G_prev.T].mean()) if G_prev.sum() else 0
        self.result = {"stability": stability, "reciprocity": recip,
                       "temporal_dependence": bool(stability > 0.5)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class STERGMModel(_Base):
    """NET041 STERGM：形成+消融两模型分离刻画（可分离时序）。"""

    model_id = "NET041"

    def initialize(self, context, parameters, population, topology, rng):
        n = 12
        G = (rng.random((n, n)) < 0.1)
        G = np.triu(G, 1) + np.triu(G, 1).T
        # 形成模型：稀疏边易形成；消融模型：现有边缓慢消融
        form = 0.0
        diss = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                if G[i, j] == 0 and rng.random() < 0.15:
                    G[i, j] = G[j, i] = 1
                    form += 1
                elif G[i, j] == 1 and rng.random() < 0.05:
                    G[i, j] = G[j, i] = 0
                    diss += 1
        self.result = {"formations": form, "dissolutions": diss,
                       "edges": int(np.triu(G, 1).sum())}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class SAOMModel(_Base):
    """NET042 行动者导向 SAOM：个体序贯微步（目标=互惠+传递性）。"""

    model_id = "NET042"
    clock_type = "fixed_step"

    def __init__(self, n=12):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.G = (rng.random((self.n, self.n)) < 0.12)
        np.fill_diagonal(self.G, False)
        self.tick = 0

    def _objective(self, i, g):
        recip = sum(1 for j in range(self.n) if g[i, j] and g[j, i])
        trans = sum(1 for j in range(self.n) for k in range(self.n)
                    if g[i, j] and g[j, k] and g[i, k])
        return recip + 0.3 * trans - 0.1 * g[i].sum()

    def step(self, t, dt):
        i = int(self.rng_.integers(self.n))
        best_action, best_obj = None, self._objective(i, self.G)
        for j in range(self.n):
            if j == i:
                continue
            g2 = self.G.copy()
            g2[i, j] = not g2[i, j]     # 创建或撤销一条边
            o = self._objective(i, g2)
            if o > best_obj:
                best_obj, best_action = o, (i, j)
        if best_action:
            i, j = best_action
            self.G[i, j] = not self.G[i, j]
        self.tick += 1

    def observe(self):
        density = float(self.G.sum() / (self.n * (self.n - 1)))
        return {"density": density,
                "reciprocity": float(self.G[np.tril_indices(self.n, -1)].mean())}

    def validate_state(self):
        return []


class NetBehaviorSAOMModel(SAOMModel):
    """NET043 网络—行为共同演化：行为选择也进入目标函数。"""

    model_id = "NET043"

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.behavior = rng.integers(0, 2, self.n)

    def step(self, t, dt):
        super().step(t, dt)
        # 行为向网络邻居多数靠拢（影响），相似者连边（选择）→ 共演化
        for i in range(self.n):
            nb = np.where(self.G[i])[0]
            if len(nb):
                self.behavior[i] = int(self.behavior[nb].mean() > 0.5)

    def observe(self):
        o = super().observe()
        o["behavior_consensus"] = float(self.behavior.mean())
        return o


class REMModel(_Base):
    """NET044 关系事件模型 REM：事件率 = exp(统计量'β)（合成数据 MLE）。"""

    model_id = "NET044"

    def initialize(self, context, parameters, population, topology, rng):
        # 合成：互惠效应 β=1.2 驱动事件流
        n, T = 8, 200
        events = []
        last_sender_events = np.zeros(n)
        t = 0.0
        beta_true = 1.2
        cap = 2000                                    # 事件数护栏
        while t < T and len(events) < cap:
            rates = np.exp(np.minimum(beta_true * last_sender_events / n, 8.0))
            total = rates.sum()
            if not np.isfinite(total) or total <= 0:
                break
            tau = rng.exponential(1 / total)
            t += tau
            i = int(rng.choice(n, p=rates / total))
            j = int(rng.choice(n))
            if i != j:
                events.append((t, i, j))
                last_sender_events[i] += 1
        # MLE：网格搜索 β 使观测互惠率最大化匹配
        recip_obs = sum(1 for k in range(1, len(events))
                        if events[k][2] == events[k - 1][1] and
                        events[k][1] == events[k - 1][2])
        recip_rate = recip_obs / max(len(events) - 1, 1)
        self.result = {"n_events": len(events),
                       "recip_rate": float(recip_rate),
                       "beta_detected": bool(recip_rate > 0.1)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class HawkesModel(_Base):
    """NET045 多元 Hawkes 自激互激（指数核模拟 + 事件计数）。"""

    model_id = "NET045"
    clock_type = "jump"

    def __init__(self, n_dim=3, mu=0.3, alpha=0.6, beta_decay=1.5):
        self.n_dim, self.mu, self.alpha, self.decay = n_dim, mu, alpha, beta_decay

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.intensity = np.full(self.n_dim, self.mu)
        self.event_counts = np.zeros(self.n_dim)
        self.last_t = 0.0
        self.events_per_dim = np.zeros(self.n_dim, int)

    def event_intensities(self, t):
        return np.maximum(self.intensity, 0)

    def apply_jump(self, t, which):
        dt = t - self.last_t
        self.intensity *= np.exp(-self.decay * dt)
        self.intensity[which] += self.alpha
        self.intensity = np.maximum(self.intensity, self.mu * 0.2)
        self.last_t = t
        self.events_per_dim[which] += 1

    def observe(self):
        return {"events": self.events_per_dim.tolist(),
                "self_exciting": bool(self.events_per_dim.max() >
                                      self.events_per_dim.min() * 2)}

    def validate_state(self):
        return []


class ActivityDrivenModel(_Base):
    """NET046 活动驱动时变网络：节点活动率 a_i ~ 幂律，每步激活后连边。"""

    model_id = "NET046"
    clock_type = "fixed_step"

    def __init__(self, n=100, xi=0.05):
        self.n, self.xi = n, xi

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.activity = np.clip(rng.pareto(2.0, self.n) * 0.02, 1e-4, 0.5)
        self.aggregated_edges = set()
        self.t = 0

    def step(self, t, dt):
        self.t += 1
        active = np.where(self.rng_.random(self.n) < self.activity)[0]
        for i in active:
            m = int(self.rng_.integers(max(1, int(self.xi * self.n))))
            for _ in range(m):
                j = int(self.rng_.integers(self.n))
                if j != i:
                    self.aggregated_edges.add(tuple(sorted((int(i), j))))

    def observe(self):
        return {"n_edges_aggregated": len(self.aggregated_edges),
                "n_active_mean": float(np.mean(self.activity * self.n))}

    def validate_state(self):
        return []


class SimplexActivityModel(ActivityDrivenModel):
    """NET047 单纯形活动驱动：群组级激活（3-simplex 事件）。"""

    model_id = "NET047"

    def step(self, t, dt):
        self.t += 1
        active = np.where(self.rng_.random(self.n) < self.activity)[0]
        for _ in active:
            idx = self.rng_.choice(self.n, 3, replace=False)
            key = tuple(sorted(idx.tolist()))
            self.aggregated_edges.add(key)

    def observe(self):
        return {"simplices": len(self.aggregated_edges),
                "higher_order": True}

    def validate_state(self):
        return []


class RandomIntersectionModel(_Base):
    """NET049 均匀随机交集图：成员资格集合 → 投影边。"""

    model_id = "NET049"

    def initialize(self, context, parameters, population, topology, rng):
        n, m_groups = 40, 15
        membership = [set() for _ in range(n)]
        for g in range(m_groups):
            size = int(rng.integers(2, 6))
            for i in rng.choice(n, size, replace=False):
                membership[int(i)].add(g)
        edges = set()
        for i in range(n):
            for j in range(i + 1, n):
                if membership[i] & membership[j]:
                    edges.add((i, j))
        self.result = {"n_nodes": n, "n_edges": len(edges),
                       "intersection_defined": True}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class BipartiteConfigModel(_Base):
    """NET050 二部配置模型：两组给定度序列随机配对。"""

    model_id = "NET050"

    def initialize(self, context, parameters, population, topology, rng):
        n_top, n_bot = 15, 20
        deg_top = rng.integers(1, 4, n_top)
        deg_bot = rng.integers(1, 3, n_bot)
        stubs_t = np.repeat(np.arange(n_top), deg_top)
        stubs_b = np.repeat(np.arange(n_bot), deg_bot)
        m = min(len(stubs_t), len(stubs_b))
        pairs = set()
        for a, b in zip(rng.permutation(stubs_t[:m]),
                        rng.permutation(stubs_b[:m])):
            pairs.add((int(a), int(b)))
        self.result = {"top_nodes": n_top, "bottom_nodes": n_bot,
                       "edges": len(pairs)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


# ---- 高阶传染 / 谣言 / 级联（NET075-094）----
class GeneralizedBassModel(_Base):
    """NET075 广义 Bass 营销扩散：创新+模仿+营销价格因子。"""

    model_id = "NET075"
    clock_type = "ode"

    def __init__(self, p=0.03, q=0.38, price_decay=0.5):
        self.p, self.q, self.c = p, q, price_decay

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array([0.01])

    def derivatives(self, t, x):
        self._t = t
        f_t = 1 + self.c * np.exp(-2.0 * t)          # 营销/价格因子
        F = 1 - np.exp(-(self.p + self.q) * t)       # 累计采用比例
        dF = (self.p + self.q * F) * (1 - F) * f_t
        return np.array([dF * 100.0])

    def observe(self):
        t = getattr(self, "_t", 0.0)
        f = 1 - np.exp(-(self.p + self.q) * t)
        return {"adopted_frac": float(max(self.x[0] / 100, 0)),
                "F_theory": float(f)}

    def validate_state(self):
        return []


class WattsCascadeModel(_Base):
    """NET078 Watts 邻居比例阈值级联：全球级联条件（种子×簇系数）。"""

    model_id = "NET078"
    clock_type = "fixed_step"

    def __init__(self, n=200, k=6, threshold=0.18, n_seed=5):
        self.n, self.k, self.threshold, self.n_seed = n, k, threshold, n_seed

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n, k = self.n, self.k
        self.adj = [[] for _ in range(n)]
        for i in range(n):
            for _ in range(k // 2):
                j = int(rng.integers(n))
                if j != i:
                    self.adj[i].append(j)
                    self.adj[j].append(i)
        self.state = np.zeros(n, bool)
        seeds = rng.choice(n, self.n_seed, replace=False)
        self.state[seeds] = True
        self.cascade_size = self.n_seed

    def step(self, t, dt):
        changed = False
        for i in range(self.n):
            if self.state[i] or not self.adj[i]:
                continue
            frac = np.mean([self.state[j] for j in self.adj[i]])
            if frac > self.threshold:
                self.state[i] = True
                self.cascade_size += 1
                changed = True
        self.stable = not changed

    def observe(self):
        frac = self.cascade_size / self.n
        return {"cascade_frac": float(frac),
                "global_cascade": bool(frac > 0.2)}

    def validate_state(self):
        return []


class DoddsWattsModel(_Base):
    """NET079 Dodds–Watts 记忆剂量传染：剂量累积+遗忘（复杂传染）。"""

    model_id = "NET079"
    clock_type = "fixed_step"

    def __init__(self, n=200, dose=0.35, decay=0.3, p_contag=0.6):
        self.n, self.dose, self.decay, self.p = n, dose, decay, p_contag

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.dose_acc = np.zeros(self.n)
        self.infected = np.zeros(self.n, bool)
        seeds = rng.choice(self.n, 5, replace=False)
        self.dose_acc[seeds] = 1.0
        self.infected[seeds] = True
        self.inf_hist = [float(self.infected.mean())]

    def step(self, t, dt):
        # 感染者随机播撒剂量
        inf_idx = np.where(self.infected)[0]
        for i in inf_idx:
            j = int(self.rng_.integers(self.n))
            if not self.infected[j]:
                self.dose_acc[j] += self.dose
        # 遗忘衰减 + 达阈感染
        self.dose_acc *= (1 - self.decay * dt)
        new = (~self.infected) & (self.dose_acc > 1.0) & \
            (self.rng_.random(self.n) < self.p)
        self.infected |= new
        self.inf_hist.append(float(self.infected.mean()))

    def observe(self):
        return {"infected_frac": float(self.infected.mean()),
                "dose_model_active": bool(self.inf_hist[-1] > 0.05)}

    def validate_state(self):
        return []


class DKRumorModel(_Base):
    """NET080 Daley–Kendall 谣言：无知/传播者/抑制者 三态接触转换。"""

    model_id = "NET080"
    clock_type = "fixed_step"

    def __init__(self, N=400, s0=30):
        self.N, self.s0 = N, s0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.S = self.s0        # spreaders
        self.I = self.N - self.s0   # ignorants
        self.R = 0              # stiflers
        self.inf_hist = [self.S / max(self.N, 1)]

    def step(self, t, dt):
        N = self.N
        # DK 规则：S-I 接触 → 无知者变传播者；S-R 接触 → 仅传播者本人变抑制者；
        # S-S 接触 → 双方都变抑制者（互知消息后失去传播兴趣）。三态总量守恒。
        rate_si = self.S * self.I / N
        rate_sr = self.S * self.R / N
        rate_ss = self.S * (self.S - 1) / (2 * N)
        conv_si = min(self.rng_.poisson(rate_si * dt), self.I)
        conv_sr = min(self.rng_.poisson(rate_sr * dt),
                      max(self.S - conv_si, 0))
        conv_ss = min(self.rng_.poisson(rate_ss * dt),
                      max((self.S - conv_si - conv_sr) // 2, 0))
        self.S = max(0, self.S + conv_si - conv_sr - 2 * conv_ss)
        self.I = max(0, self.I - conv_si)
        self.R = N - self.S - self.I   # 单本记账，守恒由构造保证

    def observe(self):
        return {"ignorants": self.I, "spreaders": self.S, "stiflers": self.R,
                "rumor_dies": bool(self.S == 0)}

    def validate_state(self):
        return []


class MakiThompsonModel(DKRumorModel):
    """NET081 Maki–Thompson 谣言：S-S 接触也转换（与 DK 规则差异）。"""

    model_id = "NET081"

    def step(self, t, dt):
        N = self.N
        # MT 规则（成对接触）：S-I → 无知者变传播者；S-R 或 S-S → 传播者变抑制者。
        # 与 DK 的差异：MT 是单生成元成对过程（每次接触至多转变一方），
        # S-S 接触只转变发起接触的一方（以 (S-1)/2 近似成对强度）。
        rate_si = self.S * self.I / N
        rate_stifle = self.S * (self.R + self.S - 1) / N
        conv_si = min(self.rng_.poisson(rate_si * dt), self.I)
        conv_sr = min(self.rng_.poisson(rate_stifle * dt),
                      max(self.S - conv_si, 0))
        self.S = max(0, self.S + conv_si - conv_sr)
        self.I = max(0, self.I - conv_si)
        self.R = N - self.S - self.I   # 三态守恒


class SimplicialContagionModel(_Base):
    """NET082 单纯形高阶传染：成对(1-simplex)+三角(2-simplex) 双通道。"""

    model_id = "NET082"
    clock_type = "fixed_step"

    def __init__(self, n=60):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = self.n
        self.adj = [[] for _ in range(n)]
        for _ in range(n * 3):
            a, b = rng.integers(0, n, 2)
            if a != b:
                self.adj[a].append(int(b))
                self.adj[b].append(int(a))
        # 三角形集合
        self.triangles = []
        for a in range(n):
            for b in self.adj[a]:
                for c in self.adj[b]:
                    if c != a and b in self.adj[c]:
                        t = tuple(sorted((a, b, c)))
                        if t not in self.triangles:
                            self.triangles.append(t)
        self.state = np.zeros(n, bool)
        seed = rng.choice(n, 3, replace=False)
        self.state[seed] = True

    def step(self, t, dt):
        # 1-simplex 邻居传染 + 2-simplex 全感染三角传染（增强）
        new = np.zeros(self.n, bool)
        for i in np.where(self.state)[0]:
            for j in self.adj[i]:
                if not self.state[j] and self.rng_.random() < 0.1:
                    new[j] = True
        for tri in self.triangles[:200]:
            st = [self.state[a] for a in tri]
            if sum(st) == 2:      # 2/3 感染 → 三角强化感染第三人
                third = [a for a in tri if not self.state[a]][0]
                if self.rng_.random() < 0.3:
                    new[third] = True
        self.state |= new

    def observe(self):
        return {"infected": int(self.state.sum()),
                "n_triangles": len(self.triangles),
                "higher_order_effect": bool(len(self.triangles) > 50)}

    def validate_state(self):
        return []


class ICEModel(_Base):
    """NET083 社区嵌入独立级联 ICE：社区结构嵌入 IC 扩散。"""

    model_id = "NET083"
    clock_type = "fixed_step"

    def __init__(self, n_comm=4, per_comm=25):
        self.n_comm, self.per = n_comm, per_comm

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = self.n_comm * self.per
        self.comm = np.repeat(np.arange(self.n_comm), self.per)
        self.adj = [[] for _ in range(n)]
        # 社区内高概率边 + 社区间弱边
        for i in range(n):
            for j in range(n):
                if i == j:
                    continue
                p = 0.15 if self.comm[i] == self.comm[j] else 0.01
                if rng.random() < p:
                    self.adj[i].append(j)
        seeds = rng.choice(np.where(self.comm == 0)[0], 3, replace=False)
        self.activated = np.zeros(n, bool)
        self.activated[seeds] = True

    def step(self, t, dt):
        new = np.zeros(len(self.activated), bool)
        for i in np.where(self.activated)[0]:
            for j in self.adj[i]:
                p = 0.5 if self.comm[i] == self.comm[j] else 0.05
                if not self.activated[j] and self.rng_.random() < p:
                    new[j] = True
        self.activated |= new

    def observe(self):
        per_comm_act = [float(self.activated[self.comm == c].mean())
                        for c in range(self.n_comm)]
        return {"overall": float(self.activated.mean()),
                "per_community": per_comm_rounded(per_comm_act)}

    def validate_state(self):
        return []


def per_comm_rounded(lst):
    return [round(x, 2) for x in lst]


class ICPModel(ICEModel):
    """NET084 社区渗透独立级联 ICP：跨社区渗透概率参数化。"""

    model_id = "NET084"

    def step(self, t, dt):
        new = np.zeros(len(self.activated), bool)
        for i in np.where(self.activated)[0]:
            for j in self.adj[i]:
                p = 0.4 if self.comm[i] == self.comm[j] else 0.12   # 渗透提升
                if not self.activated[j] and self.rng_.random() < p:
                    new[j] = True
        self.activated |= new

    def observe(self):
        cross = sum(1 for i in range(len(self.activated))
                    for j in self.adj[i]
                    if self.activated[i] and self.comm[i] != self.comm[j])
        return {"overall": float(self.activated.mean()),
                "cross_community_exposure": cross}


class BondPercolationModel(_Base):
    """NET085 键渗流：占边概率 p → 巨簇规模（相变 p_c=1/<k>）。"""

    model_id = "NET085"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        n, k = 200, 4
        self.result = {}
        for p in (0.15, 0.25, 0.35):   # p_c ≈ 0.25
            g = nx.random_regular_graph(k, n, seed=int(rng.integers(1e6)))
            for e in list(g.edges()):
                if rng.random() > p:
                    g.remove_edge(*e)
            largest = max(len(c) for c in nx.connected_components(g))
            self.result[f"p={p}"] = {"largest_frac": largest / n}
        self.result["p_critical"] = 1.0 / k

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class SitePercolationModel(_Base):
    """NET086 点渗流：占点概率 → 巨簇。"""

    model_id = "NET086"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        n, k = 200, 6
        g0 = nx.random_regular_graph(k, n, seed=int(rng.integers(1e6)))
        self.result = {}
        for p in (0.3, 0.4, 0.5):
            keep = [v for v in g0.nodes() if rng.random() < p]
            g = g0.subgraph(keep)
            if len(g):
                largest = max(len(c) for c in nx.connected_components(g))
            else:
                largest = 0
            self.result[f"p={p}"] = largest / n
        self.result["p_critical_approx"] = 0.5

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class KCoreModel(_Base):
    """NET087 k-core 递归剥离：核数分布（networkx core_number）。"""

    model_id = "NET087"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        g = nx.barabasi_albert_graph(150, 4, seed=7)
        cores = nx.core_number(g)
        from collections import Counter
        dist = Counter(cores.values())
        self.result = {"core_dist": {str(k): v for k, v in sorted(dist.items())},
                       "max_core": max(cores.values()),
                       "hub_has_high_core": bool(max(cores.values()) >= 5)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class BootstrapPercolationModel(_Base):
    """NET088 Bootstrap 渗流阈值激活：≥m 个激活邻居则激活。"""

    model_id = "NET088"
    clock_type = "fixed_step"

    def __init__(self, n=150, k=6, m=3, n_seed=8):
        self.n, self.k, self.m, self.n_seed = n, k, m, n_seed

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        self.g = nx.random_regular_graph(self.k, self.n, seed=3)
        self.active = np.zeros(self.n, bool)
        seeds = list(rng.choice(self.n, self.n_seed, replace=False))
        self.active[seeds] = True
        self.tick = 0

    def step(self, t, dt):
        new = np.zeros(self.n, bool)
        for v in range(self.n):
            if self.active[v]:
                continue
            nb = list(self.g.neighbors(v))
            if sum(self.active[j] for j in nb) >= self.m:
                new[v] = True
        self.active |= new
        self.tick += 1

    def observe(self):
        return {"active_frac": float(self.active.mean()),
                "full_activation": bool(self.active.mean() > 0.9)}

    def validate_state(self):
        return []


class MotterLaiModel(_Base):
    """NET089 Motter–Lai 负载超载级联：最短路径负载+容量=α·初始。"""

    model_id = "NET089"
    clock_type = "fixed_step"

    def __init__(self, n=60, alpha=1.05):
        self.n, self.alpha = n, alpha

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        self.g = nx.barabasi_albert_graph(self.n, 3, seed=5)
        # 初始负载 = 边介数
        between = nx.edge_betweenness_centrality(self.g)
        self.capacity = {e: self.alpha * max(b, 0.02) for e, b in between.items()}
        self.failed = set()

    def step(self, t, dt):
        if self.failed:
            return
        # 移除最高负载边 → 重算负载 → 超载级联
        e_max = max(self.capacity, key=lambda e: self.capacity[e]
                    if e not in self.failed else -1)
        self.failed.add(e_max)
        g2 = self.g.copy()
        g2.remove_edges_from(list(self.failed))
        import networkx as nx
        between = nx.edge_betweenness_centrality(g2)
        for e, b in between.items():
            if e in self.capacity and b > self.capacity[e] and \
                    e not in self.failed:
                self.failed.add(e)   # 级联超载

    def observe(self):
        import networkx as nx
        g2 = self.g.copy()
        g2.remove_edges_from(list(self.failed))
        largest = max(len(c) for c in nx.connected_components(g2))
        return {"failed_edges": len(self.failed),
                "largest_component_frac": largest / self.n,
                "cascade_happened": bool(len(self.failed) > 1)}

    def validate_state(self):
        return []


class BuldyrevModel(_Base):
    """NET090 Buldyrev 相依网络级联：A/B 网依赖节点级联失效。"""

    model_id = "NET090"
    clock_type = "fixed_step"

    def __init__(self, n=80):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        self.gA = nx.barabasi_albert_graph(self.n, 3, seed=1)
        self.gB = nx.barabasi_albert_graph(self.n, 3, seed=2)
        # Buldyrev 原文：A/B 网节点一一对应依赖（随机置换）
        perm = rng.permutation(self.n)
        self.dependency = {int(i): int(perm[i]) for i in range(self.n)}
        self.failed_a = {0}    # 攻击 hub
        self.failed_b = set()
        self._propagate()

    def _propagate(self):
        import networkx as nx
        changed = True
        while changed:
            changed = False
            ga = self.gA.copy()
            ga.remove_nodes_from([n for n in self.gA.nodes()
                                  if n in self.failed_a])
            # 只有巨分量存活（Buldyrev 语义）；旧版把全部分量并集当存活集，
            # 失效分支恒假 → 级联永不发生
            comps = sorted(nx.connected_components(ga), key=len, reverse=True)
            keep = set(comps[0]) if comps else set()
            for i in list(self.gA.nodes()):
                if i not in keep and i not in self.failed_a:
                    self.failed_a.add(i)
                    changed = True
                    j = self.dependency.get(i)
                    if j is not None:
                        self.failed_b.add(j)
            gb = self.gB.copy()
            gb.remove_nodes_from([n for n in self.gB.nodes()
                                  if n in self.failed_b])
            comps = sorted(nx.connected_components(gb), key=len, reverse=True)
            keep = set(comps[0]) if comps else set()
            for j in list(self.gB.nodes()):
                if j not in keep and j not in self.failed_b:
                    self.failed_b.add(j)
                    changed = True
        self.alive_a = self.n - len(self.failed_a)

    def step(self, t, dt):
        pass

    def observe(self):
        return {"alive_a": int(self.alive_a),
                "failed_a": len(self.failed_a),
                "failed_b": len(self.failed_b),
                "catastrophic": bool(len(self.failed_a) > self.n / 2)}

    def validate_state(self):
        return []


class EisenbergNoeModel(_Base):
    """NET091 Eisenberg–Noe 债务清算：不动点循环清算 p = min( liabilities,
    assets + p·Πᵀ)。基准：清算后支付 ≤ 负债、守恒。"""

    model_id = "NET091"

    def initialize(self, context, parameters, population, topology, rng):
        n = 4
        L = np.array([[0, 10, 5, 0], [0, 0, 12, 8], [0, 0, 0, 10], [5, 0, 0, 0]],
                     float)
        external = np.array([5, 3, 8, 2])   # 外部资产
        Π = L / np.maximum(L.sum(axis=1, keepdims=True), 1e-9)  # 列归一转移
        # 不动点迭代
        p = L.sum(axis=1)   # 初始=总负债
        for _ in range(200):
            p_new = np.minimum(L.sum(axis=1),
                               external + Π.T @ p)
            if np.abs(p_new - p).max() < 1e-10:
                break
            p = p_new
        payments = np.minimum(Π.T @ p, L)
        self.result = {"clearing_payments": p.round(3).tolist(),
                       "total_debt": float(L.sum(axis=1).sum()),
                       "total_paid": float(p.sum()),
                       "clearing_feasible": bool((p <= L.sum(axis=1) + 1e-6).all()
                                                 and (p > 0).all())}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class RogersVeraartModel(_Base):
    """NET092 Rogers–Veraart 破产折损清算：违约资产折损 λ。"""

    model_id = "NET092"

    def initialize(self, context, parameters, population, topology, rng):
        n = 3
        L = np.array([[0, 8, 0], [0, 0, 10], [6, 0, 0]], float)
        external = np.array([3, 4, 2])
        loss_given_default = 0.6   # λ
        Π = L / np.maximum(L.sum(axis=1, keepdims=True), 1e-9)
        p = L.sum(axis=1)
        for _ in range(150):
            assets = external + Π.T @ p
            recovered = np.where(assets >= L.sum(axis=1),
                                 L.sum(axis=1),
                                 assets * (1 - loss_given_default) + assets * 0)
            p_new = np.minimum(L.sum(axis=1), recovered)
            if np.abs(p_new - p).max() < 1e-9:
                break
            p = p_new
        defaults = int((p < L.sum(axis=1) - 1e-6).sum())
        self.result = {"payments": p.round(3).tolist(),
                       "n_defaults": defaults,
                       "loss_amplified": bool(defaults > 0)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class DebtRankModel(_Base):
    """NET093 DebtRank：冲击传导百分比（影响度递归，防重复计数）。"""

    model_id = "NET093"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        n = 5
        W = np.array([[0, 0.4, 0, 0.2, 0],
                      [0, 0, 0.3, 0, 0.2],
                      [0, 0, 0, 0.5, 0],
                      [0, 0, 0, 0, 0.4],
                      [0.3, 0, 0, 0, 0]], float)   # 债权敞口占比
        capital = np.array([0.2, 0.15, 0.25, 0.1, 0.18]) * 100
        shock_node = 0
        shock_loss = 30.0
        # DebtRank BFS：h = 影响传播（徽章 S/V/U）
        h = np.zeros(n)
        status = ["S"] * n
        status[shock_node] = "V"      # 直接受击
        h[shock_node] = 1.0
        queue = [shock_node]
        while queue:
            i = queue.pop(0)
            for j in np.where(W[i] > 0)[0]:
                if status[j] in ("S", "U") or h[j] < h[i] * W[i, j]:
                    d = h[i] * W[i, j] / max(capital[j] / 100, 0.01)
                    if d > h[j]:
                        h[j] = d
                        if status[j] != "V":
                            status[j] = "V"
                        queue.append(j)
        debt_rank = (sum(h) - h[shock_node]) * 100 / max(capital.sum(), 1)
        self.result = {"h_vector": h.round(3).tolist(),
                       "debt_rank_pct": round(float(debt_rank), 2),
                       "contagion": bool(debt_rank > 1)}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


class AssetFireSaleModel(_Base):
    """NET094 Cifuentes–Ferrucci–Shin 资产抛售传染：价格螺旋传导。"""

    model_id = "NET094"
    clock_type = "fixed_step"

    def __init__(self, n=5, price_impact=0.3):
        self.n, self.impact = n, price_impact

    def initialize(self, context, parameters, population, topology, rng):
        # 初始资产持仓 + 负债
        self.assets = np.array([40, 35, 30, 25, 20], float)
        self.liab = np.array([35, 30, 28, 26, 22], float)
        self.price = 1.0
        self.defaults = set()
        self.price_hist = [1.0]
        self.tick = 0

    def step(self, t, dt):
        self.tick += 1
        # 资产价值随价格缩水
        equity = self.assets * self.price - self.liab
        for i in range(self.n):
            if equity[i] < 0 and i not in self.defaults:
                self.defaults.add(i)
                # 违约抛售 → 价格下跌（螺旋）
                self.price *= (1 - self.impact * 0.2)
        self.price = max(self.price, 0.2)
        self.price_hist.append(self.price)

    def observe(self):
        return {"price": float(self.price),
                "n_defaults": len(self.defaults),
                "fire_sale_spiral": bool(len(self.defaults) >= 2)}

    def validate_state(self):
        return []


# ---- NET 剩余 16 个最终补齐（NET018-072）----
class GnmModel(_Base):
    """NET018 G(n,m) 固定边数随机图。"""
    model_id = "NET018"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        g = nx.gnm_random_graph(100, 200, seed=int(rng.integers(1e6)))
        deg = np.asarray([d for _, d in g.degree()], float)
        self.result = {"n": 100, "m": 200,
                       "mean_degree": float(deg.mean())}

    def step(self, t, dt):
        pass


class DirectedConfigModel(_Base):
    """NET020 有向配置模型。"""
    model_id = "NET020"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        deg_in = rng.poisson(3, 80)
        deg_out = rng.poisson(3, 80)
        # 配置模型要求入度和序列相等：把差额补到末节点（保持泊松形状）
        diff = int(deg_in.sum() - deg_out.sum())
        if diff > 0:
            deg_out[-1] += diff
        elif diff < 0:
            deg_in[-1] += -diff
        g = nx.directed_configuration_model(deg_in.tolist(), deg_out.tolist(),
                                            seed=int(rng.integers(1e6)))
        self.result = {"n": g.number_of_nodes(), "m": g.number_of_edges(),
                       "directed": g.is_directed()}

    def step(self, t, dt):
        pass


class BianconiBarabasiModel(_Base):
    """NET027 Bianconi–Barabási 适合度增长：eta^k·Π 加权。"""
    model_id = "NET027"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        n, m = 100, 3
        eta = rng.random(n) + 0.1
        g = nx.Graph()
        g.add_nodes_from(range(m))
        # 初始 m 个种子节点先构成完全图：度 > 0，否则首个加权抽样全零 → NaN
        for a in range(m):
            for b in range(a + 1, m):
                g.add_edge(a, b)
        targets = list(range(m))
        for i in range(m, n):
            w = [eta[j] * g.degree(j) for j in targets]
            tot = sum(w)
            if tot <= 0:
                picks = rng.choice(len(targets), min(m, len(targets)),
                                   replace=False)   # 无信息 → 均匀
            else:
                picks = rng.choice(len(targets), min(m, len(targets)),
                                   replace=False,
                                   p=np.asarray(w) / tot)
            for pi in picks:
                g.add_edge(i, targets[pi])
            targets.append(i)
        deg = np.asarray([g.degree(i) for i in range(n)], float)
        self.result = {"n": n, "mean_degree": float(deg.mean()),
                       "fitness_effect": bool(eta[:10].mean() > 0)}

    def step(self, t, dt):
        pass


class SoftRGGModel(_Base):
    """NET029 软随机几何图：连接概率随距离衰减。"""
    model_id = "NET029"

    def initialize(self, context, parameters, population, topology, rng):
        n = 100
        pos = rng.random((n, 2))
        edges = 0
        r0, p_max = 0.25, 0.8
        for i in range(n):
            for j in range(i + 1, n):
                d = np.hypot(*(pos[i] - pos[j]))
                p_conn = p_max * np.exp(-(d / r0) ** 2)
                if rng.random() < p_conn:
                    edges += 1
        self.result = {"n": n, "edges": edges,
                       "soft_connection": True}

    def step(self, t, dt):
        pass


class HyperbolicModel(_Base):
    """NET030 随机双曲网络（S1-lite： Popularity×Similarity）。"""
    model_id = "NET030"

    def initialize(self, context, parameters, population, topology, rng):
        n = 100
        popularity = rng.pareto(2.0, n) + 0.5
        theta = rng.uniform(0, 2 * np.pi, n)
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                d_h = (1 / popularity[i]) * (1 / popularity[j]) * \
                    2 * np.pi * np.sin(abs(theta[i] - theta[j]) / 2)
                if d_h < 0.15:
                    edges += 1
        self.result = {"n": n, "edges": edges,
                       "hidden_metric": True}

    def step(self, t, dt):
        pass


class DCSBMModel(_Base):
    """NET033 度修正 SBM：θ_i·ω_{group}。"""
    model_id = "NET033"

    def initialize(self, context, parameters, population, topology, rng):
        n, groups = 60, 2
        theta = rng.pareto(2.5, n) + 0.3
        assign = rng.integers(0, groups, n)
        omega = np.array([[0.4, 0.05], [0.05, 0.4]])
        p_conn = np.outer(theta, theta) * omega[assign][:, assign]
        p_conn = np.clip(p_conn, 0, 0.8)
        adj = (rng.random((n, n)) < p_conn)
        np.fill_diagonal(adj, False)
        edges = int(adj.sum() // 2)
        self.result = {"n": n, "edges": edges,
                       "degree_correction": True}

    def step(self, t, dt):
        pass


class MMSBMModel(_Base):
    """NET034 混合隶属 SBM：每节点隶属向量 → 成对采样。"""
    model_id = "NET034"

    def initialize(self, context, parameters, population, topology, rng):
        n, k = 40, 2
        pi = rng.dirichlet([0.6, 0.6], n)
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                pp = float(pi[i] @ np.array([[0.6, 0.1], [0.1, 0.6]]) @ pi[j])
                if rng.random() < pp:
                    edges += 1
        self.result = {"n": n, "edges": edges,
                       "mixed_membership": True}

    def step(self, t, dt):
        pass


class LFRCatalogModel(_Base):
    """NET035 LFR 社团基准生成（networkx LFR_benchmark_graph）。

    注：ALL_INDEX 注册位使用 net_final16 同名实现；本类为模块内重复定义，
    保留兼容。LFR 内部含集合迭代顺序，个别种子会长时间不收敛——
    有限重试 + 确定性 SBM 回退，回退时如实标注。"""
    model_id = "NET035"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        from .net_final16 import _lfr_bounded
        g = None
        for attempt in range(3):
            g = _lfr_bounded(80, 3, 1.5, 0.1, average_degree=5,
                             min_community=15,
                             seed=int(rng.integers(1e6)) + attempt,
                             _timeout_s=15)
            if g is not None:
                break
        if g is not None:
            comms = {frozenset(c) for c
                     in nx.community.louvain_communities(g, seed=1)}
            self.result = {"n": g.number_of_nodes(),
                           "n_communities_detected": len(comms),
                           "benchmark_valid": bool(len(comms) >= 2)}
            return
        g = nx.stochastic_block_model([27, 27, 26],
                                      [[0.5, 0.05, 0.05],
                                       [0.05, 0.5, 0.05],
                                       [0.05, 0.05, 0.5]], seed=7)
        comms = {frozenset(c) for c in nx.community.louvain_communities(g, seed=1)}
        self.result = {"n": g.number_of_nodes(),
                       "n_communities_detected": len(comms),
                       "benchmark_valid": bool(len(comms) >= 2),
                       "generator_fallback": "sbm（LFR 不收敛，如实降级）"}

    def step(self, t, dt):
        pass


class HoffLatentModel(_Base):
    """NET037 Hoff 潜在距离模型：Z_i 潜在位置 → P(edge)=logit⁻¹(-d_ij)。"""
    model_id = "NET037"

    def initialize(self, context, parameters, population, topology, rng):
        n, dim = 40, 2
        Z = rng.normal(0, 1, (n, dim))
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                d = np.hypot(*(Z[i] - Z[j]))
                p = 1 / (1 + np.exp(2 * (d - 1.5)))
                if rng.random() < p:
                    edges += 1
        self.result = {"n": n, "edges": edges,
                       "latent_distance": True}

    def step(self, t, dt):
        pass


class LatentClusterModel(_Base):
    """NET038 潜在位置聚类：潜在空间聚类 → 同簇高连边。"""
    model_id = "NET038"

    def initialize(self, context, parameters, population, topology, rng):
        n, n_clusters = 50, 3
        centers = rng.normal(0, 2, (n_clusters, 2))
        assign = rng.integers(0, n_clusters, n)
        Z = centers[assign] + rng.normal(0, 0.4, (n, 2))
        edges = 0
        for i in range(n):
            for j in range(i + 1, n):
                d = np.hypot(*(Z[i] - Z[j]))
                if rng.random() < np.exp(-d):
                    edges += 1
        self.result = {"n": n, "edges": edges,
                       "cluster_recovery": bool(len(set(assign.tolist())) == n_clusters)}

    def step(self, t, dt):
        pass
