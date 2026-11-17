"""BEH 经典 ABM 与社会理论批次（BEH001-013 / 041-048 / 082 / 103 / 107-110 / 136-138）。"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel
from . import game_lib as G


class _ABMBase(DayanModel):
    clock_type = "fixed_step"

    def observe(self):
        return {k: (v.tolist() if isinstance(v, np.ndarray) else v)
                for k, v in self.result.items()}

    def validate_state(self):
        return []


class SchellingModel(_ABMBase):
    """BEH001 Schelling 空间隔离：相似度阈值 → 隔离指数（非故意隔离经典）。"""

    model_id = "BEH001"
    clock_type = "fixed_step"

    def __init__(self, size=40, threshold=0.4, density=0.9):
        self.size, self.threshold, self.density = size, threshold, density

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        n = self.size
        cells = rng.random((n, n)) < self.density
        self.grid = np.where(cells, rng.integers(1, 3, (n, n)), 0)
        self.resident_ids = np.full((n, n), -1, dtype=int)
        self.resident_ids[cells] = np.arange(int(cells.sum()))
        self.tick = 0

    def _similarity(self, g):
        same = np.zeros_like(g, float)
        occ = g > 0
        cnt = np.zeros_like(same)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (di, dj) == (0, 0):
                    continue
                nb = np.roll(np.roll(g, di, 0), dj, 1)
                same += (nb == g) & occ
                cnt += (nb > 0) & occ
        with np.errstate(invalid="ignore", divide="ignore"):
            sim = np.where(cnt > 0, same / np.maximum(cnt, 1), 1.0)
        return sim, occ, cnt

    def step(self, t, dt):
        g = self.grid
        sim, occ, cnt = self._similarity(g)
        unhappy = occ & (sim < self.threshold)
        idx = np.argwhere(unhappy)
        empties = np.argwhere(g == 0)
        if len(idx) and len(empties):
            moves = min(len(idx), len(empties))
            pick_e = empties[self.rng.choice(len(empties), moves, replace=False)]
            pick_u = idx[self.rng.choice(len(idx), moves, replace=False)]
            for (ui, uj), (ei, ej) in zip(pick_u, pick_e):
                g[ei, ej], g[ui, uj] = g[ui, uj], 0
                self.resident_ids[ei, ej], self.resident_ids[ui, uj] = self.resident_ids[ui, uj], -1
        self.tick += 1

    def observe(self):
        sim, occ, _ = self._similarity(self.grid)
        return {"segregation": float(np.nanmean(sim[occ])),
                "unhappy_frac": float(np.mean(sim[occ] < self.threshold))}

    def state_frame(self):
        """WP7 状态帧：真实居民类型与格点位置。"""
        n = self.grid.shape[0]
        coords = np.argwhere(self.grid > 0)
        entities = [{"id": f"res_{int(self.resident_ids[x, y])}", "type": "resident",
                     "x": float(y), "y": float(x),
                     "state": f"type_{int(self.grid[x, y])}"}
                    for x, y in coords]
        return {"entities": entities,
                "facilities": [{"id": "grid", "type": "lattice",
                                "size": int(n)}],
                "aggregates": self.observe()}

    def validate_state(self):
        return []


class SchellingTippingModel(SchellingModel):
    """BEH002 有界邻里倾覆：阈值随邻里规模变化 → 倾覆动态。"""

    model_id = "BEH002"

    def observe(self):
        sim, occ, cnt = self._similarity(self.grid)
        return {"segregation": float(np.nanmean(sim[occ])),
                "tipped": bool(np.nanmean(sim[occ]) > self.threshold + 0.2)}


class SugarscapeModel(_ABMBase):
    """BEH003 Sugarscape 基础：糖采集+代谢 → 财富不平等涌现。"""

    model_id = "BEH003"
    clock_type = "fixed_step"

    def __init__(self, n_agents=80, size=30):
        self.n, self.size = n_agents, size

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = self.size
        # 双峰糖地形
        x, y = np.meshgrid(np.arange(n), np.arange(n))
        self.sugar = 4 - (np.hypot(x - n * 0.3, y - n * 0.7) +
                          np.hypot(x - n * 0.7, y - n * 0.3)) / (n / 2)
        self.sugar = np.clip(self.sugar, 0.2, 4)
        self.pos = rng.integers(0, n, (self.n, 2))
        self.wealth = rng.integers(5, 25, self.n).astype(float)
        self.metab = rng.uniform(1, 4, self.n)
        self.tick = 0

    def step(self, t, dt):
        n = self.size
        for i in range(self.n):
            x, y = self.pos[i]
            # 视野内向最近糖高处移动
            best = None
            for di in range(-2, 3):
                for dj in range(-2, 3):
                    nx, ny = (x + di) % n, (y + dj) % n
                    v = self.sugar[nx, ny]
                    if best is None or v > best[0]:
                        best = (v, nx, ny)
            self.pos[i] = [best[1], best[2]]
            self.wealth[i] += self.sugar[best[1], best[2]] - self.metab[i]
        self.sugar *= 0.95
        self.sugar += 0.05 * 4 / 4
        self.sugar = np.clip(self.sugar, 0, 4)
        self.tick += 1

    def observe(self):
        alive = self.wealth > 0
        w = self.wealth[alive]
        gini = float(np.abs(w[:, None] - w[None, :]).mean() / (2 * max(w.mean(), 1e-9))) \
            if len(w) > 1 else 0
        return {"alive": int(alive.sum()), "gini": gini,
                "inequality_emerged": bool(gini > 0.15)}

    def validate_state(self):
        return []


class SugarscapeTradeModel(SugarscapeModel):
    """BEH004 双资源交易：糖+香料，交换→价格涌现。"""

    model_id = "BEH004"

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.spice_pos = self.pos.copy()
        self.spice = rng.uniform(2, 6, self.n)
        self.spice_metab = rng.uniform(1, 3, self.n)
        self.prices = []

    def step(self, t, dt):
        super().step(t, dt)
        # 随机配对交易：MRS 差 → 以几何均价交换
        i, j = self.rng_.choice(self.n, 2, replace=False)
        mrs_i = (self.wealth[i] * self.metab[i]) / max(self.spice[i] * self.spice_metab[i], 1e-9)
        mrs_j = (self.wealth[j] * self.metab[j]) / max(self.spice[j] * self.spice_metab[j], 1e-9)
        if mrs_i != mrs_j and min(self.wealth[i], self.spice[j]) > 1:
            price = float(np.sqrt(mrs_i * mrs_j))
            q = 1.0
            self.wealth[i] -= q * price; self.wealth[j] += q * price
            self.spice[i] += q; self.spice[j] -= q
            self.prices.append(price)

    def observe(self):
        o = super().observe()
        recent = [x for x in self.prices[-50:] if np.isfinite(x)]
        o["trade_price_mean"] = float(np.mean(recent)) if recent else None
        o["n_trades"] = len(self.prices)
        return o


class EpsteinViolenceModel(_ABMBase):
    """Epstein (2002) Model I: G=H(1-L), N=R[1-exp(-k C/A)].

    Toroidal square-vision lattice; movement, citizen decisions, then arrests.
    This phase schedule is explicit, rather than a claim to reproduce every
    activation-order variant. Jail terms are measured in agent steps.
    Reference: https://doi.org/10.1073/pnas.092080199
    """

    model_id = "BEH005"
    clock_type = "fixed_step"
    primary_metric = "active_frac"

    def __init__(self, n_agents=60, n_cops=6, size=30, legitimacy=0.85,
                 vision=2, threshold=0.1, arrest_constant=2.3, max_jail_term=30):
        if n_agents < 1 or n_cops < 0 or size < 2 or n_agents+n_cops >= size*size:
            raise ValueError("人口/警察必须非负，且格点必须留有空位")
        if not 0 <= legitimacy <= 1 or not 0 <= threshold <= 1 or arrest_constant <= 0:
            raise ValueError("合法性/阈值须在0–1，逮捕系数须为正")
        if not 0 <= vision < size or max_jail_term < 0:
            raise ValueError("视野须小于边长，监禁期不能为负")
        self.n, self.n_cops, self.size = n_agents, n_cops, size
        self.legitimacy, self.vision, self.threshold = legitimacy, vision, threshold
        self.arrest_constant, self.max_jail_term = arrest_constant, max_jail_term

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        sites = rng.choice(self.size*self.size, self.n+self.n_cops, replace=False)
        positions = np.column_stack((sites // self.size, sites % self.size))
        self.pos_a = positions[:self.n].copy()
        self.hardship = rng.uniform(0, 1, self.n)
        self.grievance = self.hardship * (1-self.legitimacy)
        self.risk_av = rng.uniform(0, 1, self.n)
        self.active = np.zeros(self.n, bool)
        self.pos_c = positions[self.n:].copy()
        self.jailed = np.zeros(self.n, int)
        self.arrests = 0
        self.violence_hist = []

    def _near(self, positions, point):
        delta = np.abs(positions-point)
        delta = np.minimum(delta, self.size-delta)
        return delta.max(axis=1) <= self.vision

    def _move(self, position, occupied, releasing=False):
        candidates = sorted({((int(position[0])+dx) % self.size,
                              (int(position[1])+dy) % self.size)
                             for dx in range(-self.vision, self.vision+1)
                             for dy in range(-self.vision, self.vision+1)} - occupied)
        if not candidates and releasing:
            candidates = sorted({(x, y) for x in range(self.size) for y in range(self.size)}-occupied)
        return np.array(candidates[int(self.rng_.integers(len(candidates)))]) if candidates else position.copy()

    def arrest_probability(self, citizen):
        cops = int(self._near(self.pos_c, self.pos_a[citizen]).sum()) if self.n_cops else 0
        near = self._near(self.pos_a, self.pos_a[citizen]) & (self.jailed == 0) & self.active
        near[citizen] = False
        # The deciding citizen counts themself as active, so A is never zero.
        actives = int(near.sum())+1
        return float(-np.expm1(-self.arrest_constant*cops/actives))

    def step(self, t, dt):
        imprisoned = self.jailed > 0
        self.jailed[imprisoned] -= 1
        occupied = {tuple(p) for p in self.pos_a[~imprisoned]} | {tuple(p) for p in self.pos_c}
        # Release to a vacant site, without overlapping an officer or citizen.
        for i in np.flatnonzero(imprisoned & (self.jailed == 0)):
            self.pos_a[i] = self._move(self.pos_a[i], occupied, releasing=True)
            occupied.add(tuple(self.pos_a[i]))
        actors = self.rng_.permutation(self.n+self.n_cops)
        for actor in actors:
            if actor < self.n:
                if self.jailed[actor] > 0:
                    continue
                positions, index = self.pos_a, actor
            else:
                positions, index = self.pos_c, actor-self.n
            occupied.discard(tuple(positions[index]))
            positions[index] = self._move(positions[index], occupied)
            occupied.add(tuple(positions[index]))
        self.grievance = self.hardship * (1-self.legitimacy)
        for i in self.rng_.permutation(self.n):
            self.active[i] = self.jailed[i] == 0 and self.grievance[i]-self.risk_av[i]*self.arrest_probability(i) > self.threshold
        for ci in self.rng_.permutation(self.n_cops):
            targets = np.flatnonzero(self._near(self.pos_a, self.pos_c[ci]) & self.active & (self.jailed == 0))
            if len(targets):
                caught = int(self.rng_.choice(targets))
                self.active[caught] = False
                occupied.discard(tuple(self.pos_c[ci]))
                self.pos_c[ci] = self.pos_a[caught].copy()
                self.jailed[caught] = int(self.rng_.integers(self.max_jail_term+1))
                if self.jailed[caught] == 0:
                    self.pos_a[caught] = self._move(self.pos_a[caught], occupied, releasing=True)
                    occupied.add(tuple(self.pos_a[caught]))
                self.arrests += 1
        self.violence_hist.append(float(self.active.mean()))

    def observe(self):
        tail = self.violence_hist[-50:]
        return {"violence_frac": float(np.mean(tail)) if tail else 0,
                "active_frac": float(self.active.mean()), "jailed_count": int((self.jailed > 0).sum()),
                "arrests": int(self.arrests), "mean_grievance": float(self.grievance.mean()),
                "episodic": bool(np.std(tail) > 0.01) if len(tail) > 5 else False}

    def state_frame(self):
        citizens = [{"id": f"citizen_{i}", "type": "pedestrian", "x": float(p[0]), "y": float(p[1]),
                     "state": "active" if self.active[i] else "quiet"}
                    for i, p in enumerate(self.pos_a) if self.jailed[i] == 0]
        cops = [{"id": f"cop_{i}", "type": "pedestrian", "x": float(p[0]), "y": float(p[1]), "state": "cop"}
                for i, p in enumerate(self.pos_c)]
        return {"entities": citizens+cops, "space": {"bounds": [0, 0, self.size, self.size], "unit": "cell", "topology": "torus"},
                "aggregates": self.observe(), "note": "监禁者不在格点中，不为其绘制虚构坐标"}

    def snapshot(self):
        return {"parameters": {"n_agents": self.n, "n_cops": self.n_cops, "size": self.size,
                               "legitimacy": self.legitimacy, "vision": self.vision,
                               "threshold": self.threshold, "arrest_constant": self.arrest_constant,
                               "max_jail_term": self.max_jail_term},
                "arrays": {name: getattr(self, name).tolist() for name in
                           ("pos_a", "pos_c", "hardship", "grievance", "risk_av", "active", "jailed")},
                "violence_hist": list(self.violence_hist), "arrests": self.arrests,
                "rng_state": self.rng_.bit_generator.state}

    def restore(self, snapshot):
        self.__init__(**snapshot["parameters"])
        for name, values in snapshot["arrays"].items():
            kind = bool if name == "active" else int if name in ("pos_a", "pos_c", "jailed") else float
            setattr(self, name, np.array(values, dtype=kind))
        self.violence_hist = list(snapshot["violence_hist"])
        self.arrests = snapshot["arrests"]
        self.rng_ = self.rng = np.random.default_rng()
        self.rng_.bit_generator.state = snapshot["rng_state"]

    def validate_state(self):
        errs = []
        positions = [tuple(p) for p in self.pos_a[self.jailed == 0]]+[tuple(p) for p in self.pos_c]
        if len(positions) != len(set(positions)):
            errs.append("格点占用冲突")
        if np.any(self.active & (self.jailed > 0)) or np.any(self.jailed < 0):
            errs.append("监禁者仍活跃或监禁期限非法")
        return errs


class AgentZeroModel(_ABMBase):
    """BEH006 Agent_Zero：情感传染 × 认知概率推力 × 社会阈值 → 集体攻击。"""

    model_id = "BEH006"
    clock_type = "fixed_step"

    def __init__(self, n=30):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.affect = rng.uniform(0.2, 0.5, self.n)
        self.cog_prob = rng.uniform(0.1, 0.4, self.n)
        self.threshold = rng.uniform(0.3, 0.7, self.n)
        self.attacking = np.zeros(self.n, bool)
        self.hist = []

    def step(self, t, dt):
        # 情感传染（邻近均值回归）
        mean_a = self.affect.mean()
        self.affect = 0.9 * self.affect + 0.1 * mean_a + \
            self.rng_.normal(0, 0.02, self.n)
        combined = np.clip(self.affect + self.cog_prob, 0, 1)
        new = (combined > self.threshold) | \
            (self.attacking & (combined > self.threshold * 0.7))
        # 社会传染：邻居攻击数抬升阈值下限
        frac = self.attacking.mean()
        new |= (frac > 0.4) & (combined > self.threshold * 0.8)
        self.attacking = new
        self.hist.append(float(self.attacking.mean()))

    def observe(self):
        tail = self.hist[-30:]
        return {"attack_frac": float(np.mean(tail)) if tail else 0,
                "contagion_spread": bool(tail and max(tail) > 0.5)}

    def validate_state(self):
        return []


class BonabeauModel(_ABMBase):
    """BEH009 Bonabeau 自组织等级：人口密度↑ → 权力梯度陡峭（回响反馈）。"""

    model_id = "BEH009"
    clock_type = "fixed_step"

    def __init__(self, n=60, density_feedback=0.5):
        self.n, self.dfb = n, density_feedback

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.power = rng.uniform(0, 0.3, self.n)
        self.hist = []

    def step(self, t, dt):
        i, j = self.rng_.choice(self.n, 2, replace=False)
        pi, pj = self.power[i], self.power[j]
        # 强者胜率随功率差与种群密度反馈
        win_i = self.rng_.random() < 1 / (1 + np.exp((pj - pi) / max(self.dfb, 1e-6)))
        if win_i:
            self.power[j] = max(0.0, pj - 0.01)
        else:
            self.power[i] = max(0.0, pi - 0.01)
        # 权力恢复 ∝ 群体密度
        self.power += 0.005 * (1 + self.dfb)
        self.power = np.clip(self.power, 0, 1)
        if i % 5 == 0:
            self.hist.append(float(np.std(self.power)))

    def observe(self):
        return {"power_std": float(np.std(self.power)) if len(self.power) else 0,
                "hierarchy_emerged": bool(np.std(self.power) > 0.05)}

    def validate_state(self):
        return []


class MarchExploitationModel(_ABMBase):
    """BEH010 March 探索-利用：组织间互学，探索回报方差大 → 采用率演化。"""

    model_id = "BEH010"
    clock_type = "fixed_step"

    def __init__(self, n_orgs=20, p_explore=0.3):
        self.n, self.p0 = n_orgs, p_explore

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.p_explore = np.full(self.n, self.p0)
        self.knowledge = rng.uniform(0, 1, self.n)
        self.hist = []

    def step(self, t, dt):
        for i in range(self.n):
            if self.rng_.random() < self.p_explore[i]:
                # 探索：方差大
                gain = self.rng_.normal(0.05, 0.3)
            else:
                # 利用：回报确定但小
                gain = 0.02
            self.knowledge[i] += gain
        # 互学：向最好邻居的 p_explore 模仿（差回报→降探索）
        best = int(np.argmax(self.knowledge))
        for i in range(self.n):
            if i != best:
                self.p_explore[i] += 0.05 * (self.p_explore[best] - self.p_explore[i])
        self.p_explore = np.clip(self.p_explore, 0.02, 0.95)
        self.hist.append(float(self.p_explore.mean()))

    def observe(self):
        return {"mean_explore": float(self.p_explore.mean()),
                "knowledge_mean": float(self.knowledge.mean()),
                "exploit_dominates": bool(self.p_explore.mean() < self.p0)}

    def validate_state(self):
        return []


class GarbageCanModel(_ABMBase):
    """BEH011 垃圾桶组织决策：问题/方案/参与者/选择 四流独立耦合。"""

    model_id = "BEH011"
    clock_type = "fixed_step"

    def __init__(self, n_problems=12):
        self.n = n_problems

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.problem_energy = rng.uniform(0.5, 1.5, self.n)   # 问题所需能量
        self.energy_left = self.problem_energy.copy()
        self.solved = 0
        self.att_hist = []

    def step(self, t, dt):
        # 参与者能量随机注入"选择机场"
        energy_pool = self.rng_.uniform(0.3, 1.2)
        # 能量随机分配到未解问题（弱耦合=垃圾桶精神）
        idx = self.rng_.integers(self.n)
        self.energy_left[idx] -= energy_pool
        if self.energy_left[idx] <= 0 and self.problem_energy[idx] > 0:
            self.solved += 1
            self.problem_energy[idx] = 0   # 标记已解
        self.att_hist.append(self.solved / self.n)

    def observe(self):
        return {"solved_frac": float(self.solved / self.n),
                "flight_prob": bool(self.solved / self.n < 0.7)}

    def validate_state(self):
        return []


class NKLandscapeModel(_ABMBase):
    """BEH012 NK 崎岖景观：N 基因 K 交互 → 局部最优数量随 K 增大。"""

    model_id = "BEH012"
    clock_type = "fixed_step"

    def __init__(self, N=12, K=3):
        self.N, self.K = N, K

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        N, K = self.N, self.K
        # 贡献表：每个基因的 2^(K+1) 配置 → 随机贡献
        self.tables = rng.uniform(0, 1, (N, 2 ** (K + 1)))
        self.genome = rng.integers(0, 2, N)
        self.tick = 0

    def _fitness(self, g):
        N, K = self.N, self.K
        f = 0.0
        for i in range(N):
            idx = 0
            for k in range(K + 1):
                idx = idx * 2 + g[(i + k) % N]
            f += self.tables[i, idx]
        return f / N

    def step(self, t, dt):
        g = self.genome.copy()
        i = int(self.rng_.integers(self.N))
        g[i] = 1 - g[i]
        if self._fitness(g) > self._fitness(self.genome):
            self.genome = g

    def observe(self):
        f = self._fitness(self.genome)
        return {"fitness": float(f), "genome_std": float(self.genome.std())}

    def validate_state(self):
        return []


class LazerFriedmanModel(_ABMBase):
    """BEH013 Lazer–Friedman 网络探索：聚集网络 → 探索衰减 → 集体表现下降。"""

    model_id = "BEH013"
    clock_type = "fixed_step"

    def __init__(self, n=10, p_closure=0.6):
        self.n, self.p_closure = n, p_closure

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        # 初始环 + 闭合概率
        self.net = np.zeros((self.n, self.n), bool)
        for i in range(self.n):
            self.net[i, (i + 1) % self.n] = True
        for i in range(self.n):
            for j in range(i + 1, self.n):
                if self.net[i, j] == 0 and self.rng_.random() < self.p_closure * 0.3:
                    self.net[i, j] = self.net[j, i] = True
        self.problem = rng.uniform(0, 1, 20)
        self.solutions = rng.uniform(0, 1, (self.n, 20))
        self.explore_hist = []

    def step(self, t, dt):
        # 解共享：邻居取均值（网络聚集 → 解同质化）
        for i in range(self.n):
            nb = np.where(self.net[i])[0]
            if len(nb):
                self.solutions[i] = 0.5 * self.solutions[i] + \
                    0.5 * self.solutions[nb].mean(axis=0)
        # 探索率随同质化下降
        diversity = float(np.std(self.solutions.mean(axis=1)))
        p_explore = 0.5 / (1 + 10 * (1 - diversity))
        explore = self.rng_.random((self.n, 20)) < p_explore * 0.2
        self.solutions[explore] = self.rng_.uniform(0, 1, explore.sum())
        # 目标漂移（问题变化）
        self.problem = 0.9 * self.problem + 0.1 * self.rng_.uniform(0, 1, 20)
        fit = -np.abs(self.solutions - self.problem).mean(axis=1)
        self.explore_hist.append(p_explore)

    def observe(self):
        tail = self.explore_hist[-40:]
        fit = -np.abs(self.solutions - self.problem).mean(axis=1).mean()
        return {"explore_decay": bool(tail[0] > tail[-1] + 0.02) if len(tail) > 5
                else False,
                "mean_fit": float(fit)}

    def validate_state(self):
        return []


# ---- BEH041-048 文化与规范传播 ----
class BoydRichersonModel(_ABMBase):
    """BEH041 Boyd–Richerson 群体有利规范：文化群体选择维持利他规范。"""

    model_id = "BEH041"
    clock_type = "fixed_step"

    def __init__(self, n_groups=8, n_per=30):
        self.n_groups, self.n_per = n_groups, n_per

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.norm_freq = rng.uniform(0.3, 0.7, self.n_groups)

    def step(self, t, dt):
        # 利他规范组内成本但组间竞争优势
        fitness = 1.0 + 0.4 * self.norm_freq - 0.15 * self.norm_freq ** 2
        # 文化传播（组内复制）+ 组间差异选择
        self.norm_freq += 0.05 * (self.norm_freq * (1 - self.norm_freq)) * \
            (fitness - fitness.mean()) * 2
        self.norm_freq = np.clip(self.norm_freq + self.rng_.normal(0, 0.01, self.n_groups), 0, 1)

    def observe(self):
        return {"mean_norm": float(self.norm_freq.mean()),
                "between_group_var": float(self.norm_freq.var()),
                "norm_survives": bool(self.norm_freq.mean() > 0.3)}

    def validate_state(self):
        return []


class AokiCoevolutionModel(_ABMBase):
    """BEH042 Aoki 乳文化—基因共演化：文化实践频率与等位基因频率互促。"""

    model_id = "BEH042"
    clock_type = "fixed_step"

    def __init__(self):
        self.culture = 0.2
        self.gene = 0.05

    def initialize(self, context, parameters, population, topology, rng):
        self.culture, self.gene = 0.2, 0.05

    def step(self, t, dt):
        # 基因（乳糖耐受）适应度依赖文化实践（饮奶）；文化采纳依赖基因收益
        self.gene += 0.05 * self.gene * (1 - self.gene) * (0.5 + self.culture) * dt
        self.culture += 0.04 * self.culture * (1 - self.culture) * \
            (0.3 + self.gene) * dt
        self.gene = float(np.clip(self.gene, 0, 1))
        self.culture = float(np.clip(self.culture, 0, 1))

    def observe(self):
        return {"culture": float(self.culture), "gene": float(self.gene),
                "coevolved": bool(self.culture > 0.6 and self.gene > 0.4)}

    def validate_state(self):
        return []


class EthnocentrismModel(_ABMBase):
    """BEH043 Hammond–Axelrod 民族中心主义：同族合作/异族背叛策略占优。"""

    model_id = "BEH043"
    clock_type = "fixed_step"

    def __init__(self, n=40):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.group = rng.integers(0, 4, self.n)
        # 策略四型：同异族合作位
        self.in_coop = rng.random(self.n) < 0.5
        self.out_coop = rng.random(self.n) < 0.5
        self.pts = np.full(self.n, 10.0)

    def step(self, t, dt):
        i, j = self.rng_.choice(self.n, 2, replace=False)
        same = self.group[i] == self.group[j]
        coop_i = self.in_coop[i] if same else self.out_coop[i]
        coop_j = self.in_coop[j] if same else self.out_coop[j]
        # PD 收益
        if coop_i and coop_j:
            self.pts[i] += 3; self.pts[j] += 3
        elif coop_i:
            self.pts[i] -= 1; self.pts[j] += 5
        elif coop_j:
            self.pts[i] += 5; self.pts[j] -= 1
        # 弱者死亡被同策略者替换（文化复制）
        weakest = int(np.argmin(self.pts))
        src = int(self.rng_.integers(self.n))
        if self.pts[weakest] < 0:
            self.group[weakest] = self.group[src]
            self.in_coop[weakest] = self.in_coop[src]
            self.out_coop[weakest] = self.out_coop[src]
            self.pts[weakest] = 10

    def observe(self):
        same = self.group[:, None] == self.group[None, :]
        np.fill_diagonal(same, False)
        ethno = float(np.mean(self.in_coop & (~self.out_coop)))
        return {"ethnocentrism_share": ethno,
                "dominant": bool(ethno > 0.35)}

    def validate_state(self):
        return []


class UlloaCoevolutionModel(_ABMBase):
    """BEH044 Ulloa 制度—文化共同演化：制度合法性与文化适应互构。"""

    model_id = "BEH044"
    clock_type = "fixed_step"

    def __init__(self):
        self.institution = 0.5
        self.culture = 0.3

    def initialize(self, context, parameters, population, topology, rng):
        self.institution, self.culture = 0.5, 0.3

    def step(self, t, dt):
        # 制度约束文化；文化合法性反向支撑制度
        self.culture += 0.05 * (self.institution - self.culture) * dt
        legit = 1 - abs(self.institution - self.culture)
        self.institution += 0.05 * (legit - 0.5) * dt
        self.institution = float(np.clip(self.institution, 0, 1))
        self.culture = float(np.clip(self.culture, 0, 1))

    def observe(self):
        return {"institution": float(self.institution),
                "culture": float(self.culture),
                "converged": bool(abs(self.institution - self.culture) < 0.15)}

    def validate_state(self):
        return []


class BilingualCompetitionModel(_ABMBase):
    """BEH047 Castelló 双语竞争（AbramsStrogatz 扩展：双语混合态）。"""

    model_id = "BEH047"
    clock_type = "fixed_step"

    def __init__(self, prestige_a=1.2, prestige_b=1.0, x0=0.6):
        self.pa, self.pb, self.x = prestige_a, prestige_b, x0

    def initialize(self, context, parameters, population, topology, rng):
        self.x = parameters.get("x0", self.x)  # 说语言 A 的份额

    def step(self, t, dt):
        # dx/dt = (1-x)·pa·x^c - x·pb·(1-x)^c（c=0.6 近似双语共存区）
        c = 0.6
        dx = (1 - self.x) * self.pa * self.x ** c - \
            self.x * self.pb * (1 - self.x) ** c
        self.x = float(np.clip(self.x + 0.02 * dx, 0, 1))

    def observe(self):
        return {"share_a": float(self.x),
                "bilingual_stationary": bool(0.1 < self.x < 0.9)}

    def validate_state(self):
        return []


class BayesianIteratedLearningModel(_ABMBase):
    """BEH048 贝叶斯迭代学习：语言传递链 → 先验再现（Kirby Smith 结果）。"""

    model_id = "BEH048"
    clock_type = "fixed_step"

    def __init__(self, n_generations=15, n_meanings=8):
        self.n_gen, self.n_meanings = n_generations, n_meanings

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        # 初始语言：随机映射（意义→信号）
        self.language = rng.integers(0, self.n_meanings,
                                     (self.n_meanings, self.n_meanings))
        self.compositional_hist = []

    def _compositional_score(self, lang):
        # 组合性度量：信号=意义（恒等映射程度）
        return float(np.mean(lang == np.tile(np.arange(len(lang))[:, None],
                                             (1, len(lang)))))

    def step(self, t, dt):
        if t >= self.n_gen:
            return
        # 学习者：贝叶斯后验（以输入数据为似然、均衡先验），生成新语言
        data_idx = self.language[self.rng_.integers(0, self.n_meanings, 6)]
        posterior = np.full((self.n_meanings, self.n_meanings), 0.5)
        for row in data_idx:
            for m, s in enumerate(row):
                posterior[m, s] += 10   # 数据似然增强
        # 采样新语言
        new_lang = np.zeros_like(self.language)
        for m in range(self.n_meanings):
            p = posterior[m] / posterior[m].sum()
            new_lang[m] = self.rng_.choice(self.n_meanings, p=p)
        self.language = new_lang
        self.compositional_hist.append(self._compositional_score(new_lang))

    def observe(self):
        tail = self.compositional_hist[-5:] or [0]
        return {"compositional": float(np.mean(tail)),
                "structured_emerged": bool(np.mean(tail) > 0.3)}

    def validate_state(self):
        return []


# ---- BEH082 / 103 / 107 / 108 / 110 ----
class ReplicatorCatalogModel(_ABMBase):
    """BEH082 复制动态（鹰鸽，解析混合均衡对照）。"""

    model_id = "BEH082"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        g = G.g_hawk_dove().A
        self.A = g
        self.x = np.array([0.7, 0.3])
        self.tick = 0

    def step(self, t, dt):
        fit = self.A @ self.x
        avg = float(self.x @ fit)
        self.x = self.x + dt * self.x * (fit - avg)
        self.x = np.maximum(self.x, 0)
        self.x = self.x / max(self.x.sum(), 1e-12)

    def observe(self):
        V, C = 4.0, 6.0
        x_hawk_star = V / C
        return {"freq": self.x.tolist(),
                "err_vs_star": abs(float(self.x[0]) - x_hawk_star)}

    def validate_state(self):
        return []


class TPBModel(_ABMBase):
    """BEH103 计划行为理论：态度+主观规范+知觉控制 → 意向 → 行为。"""

    model_id = "BEH103"
    clock_type = "fixed_step"

    def __init__(self, n=100):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.attitude = rng.normal(0, 1, self.n)
        self.norm = rng.normal(0, 1, self.n)
        self.control = rng.normal(0, 1, self.n)
        self.behaved = np.zeros(self.n, bool)

    def step(self, t, dt):
        intention = 0.4 * self.attitude + 0.3 * self.norm + 0.3 * self.control
        self.behaved = intention > 0.3

    def observe(self):
        return {"behavior_rate": float(self.behaved.mean()),
                "tpb_structure": True}

    def validate_state(self):
        return []


class ERCModel(_ABMBase):
    """BEH107 ERC 相对收益地位：份额比较 → 剥夺驱动再分配要求。"""

    model_id = "BEH107"
    clock_type = "fixed_step"

    def __init__(self, n=12):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        self.claim = rng.dirichlet(np.ones(self.n))
        self.actual = rng.dirichlet(np.ones(self.n))
        self.conflict_hist = []

    def step(self, t, dt):
        # 剥夺 = claim − actual；冲突强度 ∝ 剥夺方差
        deprived = self.claim - self.actual
        conflict = float(np.mean(np.maximum(deprived, 0)))
        self.conflict_hist.append(conflict)
        # 再分配：冲突推动 actual 向 claim 移动
        self.actual += 0.1 * deprived * dt
        self.actual = self.actual / self.actual.sum()

    def observe(self):
        return {"conflict": float(np.mean(self.conflict_hist[-30:] or [0])),
                "claim_actual_gap": float(np.abs(self.claim - self.actual).mean())}

    def validate_state(self):
        return []


class RabinReciprocityModel(_ABMBase):
    """BEH108 Rabin 意图互惠：善良函数 κ 与互惠反应矩阵。"""

    model_id = "BEH108"
    clock_type = "fixed_step"

    def initialize(self, context, parameters, population, topology, rng):
        # 2×2 信任博弈：kindness_i = a_ij − 均值
        pay = np.array([[4, 0], [6, 1]])
        # Rabin 平衡：互惠善良函数相互最大化
        self.kind_matrix = pay - pay.mean(axis=1, keepdims=True)
        self.reciprocal_eq = bool(np.sign(self.kind_matrix[0, 1]) !=
                                  np.sign(self.kind_matrix[1, 0]))

    def step(self, t, dt):
        pass

    def observe(self):
        return {"kindness": self.kind_matrix.tolist(),
                "reciprocal_pair": self.reciprocal_eq}

    def validate_state(self):
        return []


class CognitiveHierarchyModel(_ABMBase):
    """BEH110 认知层级 CH：Poisson(τ) 层级分布 + 最优反应（p-beauty）。"""

    model_id = "BEH110"
    clock_type = "fixed_step"

    def __init__(self, tau=1.5, n_max=20):
        self.tau, self.n_max = tau, n_max

    def initialize(self, context, parameters, population, topology, rng):
        # CH 分布：P(k) ∝ τ^k/k!
        ks = np.arange(self.n_max)
        w = self.tau ** ks / np.array([np.math.factorial(k) if hasattr(np, "math")
                                       else __import__("math").factorial(k)
                                       for k in ks])
        self.dist = w / w.sum()
        # 各层最优反应迭代
        avg = 50.0
        self.actions = []
        for k in ks:
            self.actions.append(avg * 2 / 3)
            avg = self.actions[-1]

    def step(self, t, dt):
        pass

    def observe(self):
        win = float(np.dot(self.dist[1:], self.actions[:self.n_max - 1]))
        return {"distribution_head": self.dist[:5].round(3).tolist(),
                "winning_number": win,
                "below_50": bool(win < 50)}

    def validate_state(self):
        return []


# ---- BEH136-138 ----
class DownsHotellingSpatialModel(_ABMBase):
    """BEH136 Downs–Hotelling 空间投票：双候选人向中位选民收敛。"""

    model_id = "BEH136"
    clock_type = "fixed_step"

    def __init__(self, median=0.5):
        self.median = median

    def initialize(self, context, parameters, population, topology, rng):
        self.cand = np.array([0.15, 0.85])

    def step(self, t, dt):
        # 距中位更远者移动
        d = np.abs(self.cand - self.median)
        loser = int(np.argmax(d))
        self.cand[loser] += np.sign(self.median - self.cand[loser]) * 0.02

    def observe(self):
        return {"positions": self.cand.tolist(),
                "gap": float(np.abs(self.cand[0] - self.cand[1])),
                "converged": bool(np.abs(self.cand[0] - self.cand[1]) < 0.1)}

    def validate_state(self):
        return []


class SocialIdentityModel(_ABMBase):
    """BEH137 社会认同与自我分类：去个性化（原型吸引 → 群内一致）。"""

    model_id = "BEH137"
    clock_type = "fixed_step"

    def __init__(self, n=30, n_groups=2):
        self.n, self.k = n, n_groups

    def initialize(self, context, parameters, population, topology, rng):
        self.identity = rng.uniform(0, 1, self.n)
        self.member = rng.integers(0, self.k, self.n)

    def step(self, t, dt):
        # 自我分类：向群原型（均值）吸引，个体方差衰减
        for g in range(self.k):
            mask = self.member == g
            if mask.sum() > 1:
                proto = self.identity[mask].mean()
                self.identity[mask] += 0.15 * (proto - self.identity[mask])

    def observe(self):
        within = []
        for g in range(self.k):
            mask = self.member == g
            if mask.sum() > 1:
                within.append(float(self.identity[mask].std()))
        return {"mean_within_var": float(np.mean(within)),
                "depersonalized": bool(np.mean(within) < 0.15)}

    def validate_state(self):
        return []


class BourdieuCapitalModel(_ABMBase):
    """BEH138 场域与资本转换：经济/文化/社会资本转换矩阵（Bourdieu）。"""

    model_id = "BEH138"
    clock_type = "fixed_step"

    def __init__(self, n=50):
        self.n = n

    def initialize(self, context, parameters, population, topology, rng):
        # 三类资本存量
        self.capital = rng.dirichlet([1, 1, 1], self.n) * 100  # 经济/文化/社会

    def step(self, t, dt):
        # 转换矩阵：经济→文化（教育投资）损耗 30%；文化→社会损耗 40%…
        T = np.array([[0.9, 0.0, 0.3],
                      [0.6, 0.85, 0.0],
                      [0.2, 0.5, 0.9]])
        flow = self.capital @ T * 0.05
        self.capital = self.capital - self.capital * 0.05 + flow
        self.capital = np.maximum(self.capital, 0)

    def observe(self):
        mean_cap = self.capital.mean(axis=0)
        return {"capital_means": mean_cap.round(2).tolist(),
                "conversion_active": bool(mean_cap.sum() > 50)}

    def validate_state(self):
        return []
