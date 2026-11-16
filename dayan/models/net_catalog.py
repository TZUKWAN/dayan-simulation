"""NET 目录映射层：经典 CA（NET001-008）、网络生成器（NET018-050 子集）、
仓室映射（NET051-060 → epidemic.py）、传播新族（NET063-068）、Fisher–KPP（NET016）。

诚实边界：ERGM 族/土地利用 CA（SLEUTH/CLUE-S/FLUS/PLUS）/双曲网络/TERGM 等
需要专门估计或遥感数据框架，保持"仅登记"。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


# ============ 经典 CA 族（NET001-008）============
class ElementaryCAModel(DayanModel):
    """NET001-004 初等元胞自动机（Wolfram Rule 30/90/110/184）。
    基准：Rule90 从单点生成 Sierpinski 三角（异或结构）；Rule184 交通守恒。"""

    clock_type = "fixed_step"

    def __init__(self, rule=30, cells=101, steps=60):
        self.rule, self.cells, self.steps = rule, cells, steps
        self.state = np.zeros(cells, np.uint8)

    def initialize(self, context, parameters, population, topology, rng):
        self.rule = int(parameters.get("rule", self.rule))
        n = int(parameters.get("cells", self.cells))
        self.state = np.zeros(n, np.uint8)
        self.state[n // 2] = 1
        self.tick = 0
        self.rows = [self.state.copy()]

    def _next(self, s):
        n = len(s)
        left = np.roll(s, 1)
        right = np.roll(s, -1)
        idx = (left << 2) | (s << 1) | right
        return np.array([(self.rule >> int(i)) & 1 for i in idx], np.uint8)

    def step(self, t, dt):
        if self.tick >= self.steps:
            return
        self.state = self._next(self.state)
        self.tick += 1
        if len(self.rows) < 500:
            self.rows.append(self.state.copy())

    def observe(self):
        arr = np.array(self.rows)
        density = float(arr.mean())
        # Rule90 Sierpinski：行内奇偶结构（每行对称性）
        symmetry = float(np.mean([np.array_equal(r, r[::-1])
                                  for r in arr[-10:]]))
        return {"rule": self.rule, "density": density,
                "n_steps": int(self.tick), "last_symmetry": symmetry,
                "n_patterns": len({r.tobytes() for r in self.rows})}

    def validate_state(self):
        return []


class Rule30Model(ElementaryCAModel):
    """NET001 Rule 30：混沌左偏结构。"""

    model_id = "NET001"

    def __init__(self):
        super().__init__(rule=30)


class Rule90Model(ElementaryCAModel):
    """NET002 Rule 90：Sierpinski 分形（对称）。"""

    model_id = "NET002"

    def __init__(self):
        super().__init__(rule=90)


class Rule110Model(ElementaryCAModel):
    """NET003 Rule 110：图灵完备复杂结构。"""

    model_id = "NET003"

    def __init__(self):
        super().__init__(rule=110)


class Rule184Model(ElementaryCAModel):
    """NET004 Rule 184：确定性交通 CA（车辆数守恒）。"""

    model_id = "NET004"

    def __init__(self):
        super().__init__(rule=184, cells=51)

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        # 均匀撒车（密度 0.5）而非单点
        n = self.cells
        self.state[:] = 0
        idx = rng.choice(n, n // 2, replace=False)
        self.state[idx] = 1
        self.rows = [self.state.copy()]
        self.n_cars0 = int(self.state.sum())

    def observe(self):
        return {"rule": 184, "cars": int(self.state.sum()),
                "cars_conserved": int(self.state.sum()) == self.n_cars0,
                "density": float(self.state.mean())}


class GameOfLifeModel(DayanModel):
    """NET005 康威生命游戏：B3/S23；基准：方块静止/滑翔机平移。"""

    model_id = "NET005"
    clock_type = "fixed_step"

    def __init__(self, size=32):
        self.size = size
        self.grid = np.zeros((size, size), np.uint8)

    def initialize(self, context, parameters, population, topology, rng):
        n = self.size = int(parameters.get("size", self.size))
        self.grid = np.zeros((n, n), np.uint8)
        # 放置滑翔机
        glider = [(0, 1), (1, 2), (2, 0), (2, 1), (2, 2)]
        for i, j in glider:
            self.grid[i + 2, j + 2] = 1
        self.tick = 0

    def step(self, t, dt):
        g = self.grid
        nb = sum(np.roll(np.roll(g, di, 0), dj, 1)
                 for di in (-1, 0, 1) for dj in (-1, 0, 1)
                 if (di, dj) != (0, 0))
        self.grid = ((nb == 3) | ((g == 1) & (nb == 2))).astype(np.uint8)
        self.tick += 1

    def observe(self):
        return {"alive": int(self.grid.sum()), "tick": self.tick}

    def validate_state(self):
        return []


class GreenbergHastingsModel(DayanModel):
    """NET006 Greenberg–Hastings 可激发介质：静息/激发/不应 三态螺旋波。"""

    model_id = "NET006"
    clock_type = "fixed_step"

    def __init__(self, size=40):
        self.size = size
        self.grid = np.zeros((size, size), int)  # 0静息 1激发 2..k不应

    def initialize(self, context, parameters, population, topology, rng):
        n = self.size
        self.grid = np.zeros((n, n), int)
        self.grid[n // 2, :n // 4] = 1          # 初始激发线
        self.tick = 0

    def step(self, t, dt):
        g = self.grid
        excited = (g == 1)
        nb_exc = sum(np.roll(np.roll(excited, di, 0), dj, 1)
                     for di in (-1, 0, 1) for dj in (-1, 0, 1)
                     if (di, dj) != (0, 0))
        new = np.zeros_like(g)
        new[g == 0] = (nb_exc[g == 0] > 0).astype(int) * 1
        new[g == 1] = 2                          # 激发→不应
        new[g > 1] = g[g > 1] + 1                # 不应期衰减
        new[g > 3] = 0
        self.grid = new
        self.tick += 1

    def observe(self):
        return {"excited": int((self.grid == 1).sum()),
                "resting": int((self.grid == 0).sum()),
                "wave_active": bool((self.grid == 1).sum() > 0)}

    def validate_state(self):
        return []


class CyclicCAModel(DayanModel):
    """NET007 循环竞争 CA：N 色环状捕食（mod-N 吃邻居）。"""

    model_id = "NET007"
    clock_type = "fixed_step"

    def __init__(self, size=48, n_colors=6):
        self.size, self.n_colors = size, n_colors

    def initialize(self, context, parameters, population, topology, rng):
        n = self.size = int(parameters.get("size", self.size))
        k = self.n_colors = int(parameters.get("n_colors", self.n_colors))
        self.grid = rng.integers(0, k, (n, n))

    def step(self, t, dt):
        g = self.grid
        k = self.n_colors
        prey = (g + 1) % k
        # 任一邻居是猎物 → 被吃
        eats = np.zeros_like(g, bool)
        for di in (-1, 0, 1):
            for dj in (-1, 0, 1):
                if (di, dj) == (0, 0):
                    continue
                nb = np.roll(np.roll(prey, di, 0), dj, 1)
                eats |= (nb == g)
        self.grid = np.where(eats, prey, g)

    def observe(self):
        counts = [int((self.grid == c).sum())
                  for c in range(self.n_colors)]
        return {"counts": counts,
                "diversity": sum(1 for c in counts if c > 0)}

    def validate_state(self):
        return []


class ForestFireModel(DayanModel):
    """NET008 Drossel–Schwabl 森林火灾：树生长 p、雷击 f（f≪p）自组织临界。"""

    model_id = "NET008"
    clock_type = "fixed_step"

    def __init__(self, size=60, p_growth=0.01, f_light=0.0002):
        self.size, self.p, self.f = size, p_growth, f_light
        self.grid = np.zeros((size, size), int)  # 0空 1树 2火

    def initialize(self, context, parameters, population, topology, rng):
        n = self.size
        self.grid = (rng.random((n, n)) < 0.3).astype(int)
        self.tick = 0
        self.fires = 0

    def step(self, t, dt):
        rng = getattr(self, "rng", None) or np.random.default_rng(int(t) + 5)
        g = self.grid
        n = self.size
        # 火点燃
        strikes = rng.random((n, n)) < self.f
        strikes &= (g == 1)
        if strikes.any():
            # 火蔓延（BFS 一轮）
            burning = strikes
            for _ in range(n):
                nb = sum(np.roll(np.roll(burning, di, 0), dj, 1)
                         for di in (-1, 0, 1) for dj in (-1, 0, 1)
                         if (di, dj) != (0, 0))
                spread = (nb > 0) & (g == 1) & (~burning)
                if not spread.any():
                    break
                burning |= spread
            g[burning] = 0
            self.fires += int(strikes.sum())
        # 树生长
        grow = (g == 0) & (rng.random((n, n)) < self.p)
        g[grow] = 1
        self.grid = g
        self.tick += 1

    def observe(self):
        g = self.grid
        return {"trees": int((g == 1).sum()), "trees_frac":
                float((g == 1).mean()), "lightning_fires": self.fires}

    def validate_state(self):
        return []


# ============ 传播/仓室映射（NET051-060 → epidemic.py）============
def _alias_epi(spec_name, model_id, doc):
    """把 epidemic.py 的 spec 包装为可运行 DayanModel。"""

    class _Wrapper(DayanModel):
        clock_type = "fixed_step"

        def __init__(self):
            from . import epidemic as ep
            self._impl = ep.CompartmentModel(getattr(ep, spec_name)())

        def initialize(self, context, parameters, population, topology, rng):
            self._impl.initialize(context, parameters, population,
                                  topology, rng)

        def step(self, t, dt):
            ns = self._impl._namespace(self._impl.x)
            dx = np.zeros(len(self._impl.compartments))
            for tr in self._impl.transitions:
                rate = float(eval(tr["rate"], {"__builtins__": {}}, dict(ns)))
                f, to = tr.get("from"), tr.get("to")
                # from/to 为 null 表示出生源/死亡汇（与 ODE 引擎同语义）
                fi = self._impl.compartments.index(f)                     if f in self._impl.compartments else None
                ti = self._impl.compartments.index(to)                     if to in self._impl.compartments else None
                if fi is not None:
                    dx[fi] -= rate
                if ti is not None:
                    dx[ti] += rate
            self._impl.x = np.maximum(self._impl.x + dx * dt, 0)

        def observe(self):
            return self._impl.observe()

        def validate_state(self):
            return self._impl.validate_state()

    return type(model_id, (_Wrapper,), {"model_id": model_id, "__doc__": doc})


SIModel = _alias_epi("spec_SI", "NET051", "NET051 SI 不可逆感染（仓室映射）。")
SIRSNetModel = _alias_epi("spec_SIRS", "NET054",
                          "NET054 SIRS 免疫衰减（仓室映射）。")
SEIRSNetModel = _alias_epi("spec_SEIRS", "NET056",
                           "NET056 SEIRS 潜伏与免疫衰减（仓室映射）。")
SEIRDNetModel = _alias_epi("spec_SEIRD", "NET057",
                           "NET057 SEIRD 显式死亡（仓室映射）。")
SEIARNetModel = _alias_epi("spec_SEIAR", "NET058",
                           "NET058 SEIAR 无症状感染（仓室映射）。")
SIRVitalNetModel = _alias_epi("spec_SIR_vital", "NET059",
                              "NET059 含出生死亡的 SIR（仓室映射）。")
SIRVNetModel = _alias_epi("spec_SIRV_vaccine", "NET060",
                          "NET060 SEIRV 疫苗保护（仓室映射）。")


# ============ 传播新族（NET063-068）============
class EdgeSIRModel(DayanModel):
    """NET063 逐边连续时间网络 SIR（Gillespie on network）。"""

    model_id = "NET063"
    clock_type = "jump"

    def __init__(self, n=100, k_avg=6, beta=0.3, gamma=0.1, n_seed=3):
        rng = np.random.default_rng(0)
        # 稀疏 ER 图邻接表
        edges = []
        for _ in range(n * k_avg // 2):
            a, b = rng.integers(0, n, 2)
            if a != b:
                edges.append((int(a), int(b)))
        self.n, self.beta, self.gamma, self.n_seed = n, beta, gamma, n_seed
        self.adj = [[] for _ in range(n)]
        for a, b in edges:
            self.adj[a].append(b)
            self.adj[b].append(a)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.status = np.zeros(self.n, int)     # 0=S 1=I 2=R
        seeds = rng.choice(self.n, self.n_seed, replace=False)
        self.status[seeds] = 1
        self._t = 0.0

    def event_intensities(self, t):
        I = np.where(self.status == 1)[0]
        if len(I) == 0:
            return np.array([0.0, 0.0])
        s_neighbors = sum(np.sum(self.status[self.adj[i]] == 0) for i in I)
        return np.array([self.beta * s_neighbors, self.gamma * len(I)])

    def apply_jump(self, t, which):
        self._t = t
        if which == 0:   # 感染：随机 S 邻边
            I = np.where(self.status == 1)[0]
            pairs = [(i, j) for i in I for j in self.adj[i]
                     if self.status[j] == 0]
            if pairs:
                i, j = pairs[int(self.rng_.integers(len(pairs)))]
                self.status[j] = 1
        else:            # 恢复
            I = np.where(self.status == 1)[0]
            if len(I):
                self.status[int(self.rng_.choice(I))] = 2

    def observe(self):
        return {"S": int((self.status == 0).sum()),
                "I": int((self.status == 1).sum()),
                "R": int((self.status == 2).sum())}

    def validate_state(self):
        return []


class MarkovSIRModel(DayanModel):
    """NET064 有限人口 Markov 随机 SIR（离散时间链）。"""

    model_id = "NET064"
    clock_type = "fixed_step"

    def __init__(self, N=300, beta=0.4, gamma=0.15, i0=5):
        self.N, self.beta, self.gamma, self.i0 = N, beta, gamma, i0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.S = self.N - self.i0
        self.I = self.i0
        self.R = 0

    def step(self, t, dt):
        lam = self.beta * self.S * self.I / self.N
        new_inf = self.rng_.binomial(self.S, min(lam * dt, 1.0))
        new_rec = self.rng_.binomial(self.I, min(self.gamma * dt, 1.0))
        self.S -= new_inf
        self.I += new_inf - new_rec
        self.R += new_rec

    def observe(self):
        return {"S": self.S, "I": self.I, "R": self.R,
                "conserv": self.S + self.I + self.R}

    def validate_state(self):
        return [] if self.S + self.I + self.R == self.N else ["人口不守恒"]


class ErlangStageSIRModel(DayanModel):
    """NET066 Erlang 多阶段传染期 SIR：感染期分 k 段（γ/k 每段）。"""

    model_id = "NET066"
    clock_type = "fixed_step"

    def __init__(self, N=2000, beta=0.4, gamma=0.3, k=3, i0=10):
        self.N, self.beta, self.gamma, self.k, self.i0 = N, beta, gamma, k, i0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.S = self.N - self.i0 * self.k
        self.I = [self.i0] * self.k     # k 个感染阶段
        self.R = 0.0

    def step(self, t, dt):
        I_total = sum(self.I)
        lam = self.beta * I_total / self.N
        new_inf = self.rng_.poisson(max(lam * self.S * dt, 0))
        # 每阶段按 γk 流出
        out = [self.rng_.poisson(self.gamma * self.k * n * dt) for n in self.I]
        self.I[0] += new_inf
        for s in range(self.k - 1, -1, -1):
            moved = min(out[s], self.I[s])
            self.I[s] -= moved
            if s == self.k - 1:
                self.R += moved
            else:
                self.I[s + 1] += moved
        self.S = max(0, self.S - new_inf)

    def observe(self):
        return {"S": float(self.S), "I_total": float(sum(self.I)),
                "R": float(self.R),
                "stages": [float(x) for x in self.I]}

    def validate_state(self):
        return []


class RossMacdonaldModel(DayanModel):
    """NET068 Ross–Macdonald 人—媒介传播：人类 M + 蚊子 V 双宿主 SEI。"""

    model_id = "NET068"
    clock_type = "fixed_step"

    def __init__(self, M_h=1000, M_v=2000, bite=0.3, b=0.5, c=0.5,
                 gamma=0.1, mu_v=0.1, i0h=5):
        self.M_h, self.M_v, self.bite, self.b, self.c, self.gamma, self.mu_v = \
            M_h, M_v, bite, b, c, gamma, mu_v
        self.i0h = i0h

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.Ih = self.i0h
        self.Sh = self.M_h - self.Ih
        self.Iv = 0
        self.Sv = self.M_v

    def step(self, t, dt):
        # 人→蚊（蚊叮感染者获得）
        inf_v = self.bite * self.b * (self.Ih / self.M_h) * self.Sv * dt
        inf_v = min(inf_v, self.Sv)
        # 蚊→人
        inf_h = self.bite * self.c * (self.Iv / self.M_v) * self.Sh * dt
        inf_h = min(inf_h, self.Sh)
        self.Sv -= inf_v
        self.Iv += inf_v - self.mu_v * self.Iv * dt
        self.Sv += self.mu_v * self.Iv * dt     # 蚊补充（平衡）
        self.Sh -= inf_h
        self.Ih += inf_h - self.gamma * self.Ih * dt
        self.Sh += self.gamma * self.Ih * dt

    def observe(self):
        prev_h = self.Ih / self.M_h
        prev_v = self.Iv / self.M_v
        return {"Ih": float(self.Ih), "Iv": float(self.Iv),
                "prev_h": float(prev_h), "prev_v": float(prev_v),
                "endemic": bool(prev_h > 0.001)}

    def validate_state(self):
        return []


class FisherKPPModel(DayanModel):
    """NET016 Fisher–KPP 反应扩散：∂u/∂t = D∇²u + r·u(1-u)；波前速度 2√(rD)。"""

    model_id = "NET016"
    clock_type = "fixed_step"

    def __init__(self, n=60, D=0.1, r=1.0, dt=0.05):
        self.n, self.D, self.r, self.dt0 = n, D, r, dt

    def initialize(self, context, parameters, population, topology, rng):
        n = self.n
        self.u = np.zeros((n, n))
        self.u[n // 2, n // 2 - 2:n // 2 + 2] = 1.0   # 中央方块侵殖源
        self.tick = 0

    def step(self, t, dt):
        u = self.u
        lap = (np.roll(u, 1, 0) + np.roll(u, -1, 0) +
               np.roll(u, 1, 1) + np.roll(u, -1, 1) - 4 * u)
        u = u + dt * (self.D * lap + self.r * u * (1 - u))
        self.u = np.clip(u, 0, 1)
        self.tick += 1

    def observe(self):
        occupied = float((self.u > 0.5).mean())
        return {"occupied_frac": occupied,
                "total": float(self.u.sum()),
                "spreading": bool(occupied > 0.001)}

    def validate_state(self):
        return []


# ============ 网络生成器扩展（NET018-037 子集，networkx 后端）============
def _net_wrapper(nx_fn, model_id, doc, diag="degree_powerlaw"):
    """把 networkx 生成函数包装为模型（诊断：度分布/连通性）。"""

    def init(self, context, parameters, population, topology, rng):
        import networkx as nx
        seed = int(rng.integers(1 << 30))
        try:
            g = nx_fn(nx, seed)
        except TypeError:
            g = nx_fn(nx)
        deg = np.asarray([d for _, d in g.degree()], float)
        self.result = {"n": int(g.number_of_nodes()),
                       "m": int(g.number_of_edges()),
                       "mean_degree": float(deg.mean()) if len(deg) else 0,
                       "n_components": int(nx.number_connected_components(g))
                       if not g.is_directed() else -1}

    def step(self, t, dt):
        pass

    def observe(self):
        return dict(self.result)

    def validate_state(self):
        return []

    return type(model_id + "_Gen", (DayanModel,), {
        "model_id": model_id, "__doc__": doc,
        "clock_type": "fixed_step",
        "result": {},
        "initialize": init, "step": step, "observe": observe,
        "validate_state": validate_state})


ConfigurationModel = _net_wrapper(
    lambda nx, seed: nx.configuration_model(
        _even_degrees(rng_deg(150, 3.0, seed)), seed=seed, create_using=nx.Graph),
    "NET019", "NET019 无向配置模型（给定度序列随机配对）。")


def _even_degrees(deg):
    """配置模型要求度和为偶数：奇数则把末位 ±1（度序列形状不变）。"""
    deg = np.clip(np.asarray(deg), 1, None).copy()
    if deg.sum() % 2:
        deg[-1] += 1
    return deg.tolist()


def rng_deg(n, mean, seed):
    rng = np.random.default_rng(seed)
    return rng.poisson(mean, n)


ChungLuModel = _net_wrapper(
    lambda nx, seed: nx.expected_degree_graph(
        np.clip(np.random.default_rng(seed).pareto(2.5, 120) + 1, 1, 30).tolist(),
        seed=seed, selfloops=False),
    "NET021", "NET021 Chung–Lu 期望度随机图（重尾度）。")
RandomRegularModel = _net_wrapper(
    lambda nx, seed: nx.random_regular_graph(4, 120, seed=seed),
    "NET022", "NET022 随机正则图（全度=4）。")
HolmeKimModel = _net_wrapper(
    lambda nx, seed: nx.powerlaw_cluster_graph(120, 3, 0.4, seed=seed),
    "NET026", "NET026 Holme–Kim 三角闭包增长（高聚类 BA）。")
RandomGeometricModel = _net_wrapper(
    lambda nx, seed: nx.random_geometric_graph(150, 0.16, seed=seed),
    "NET028", "NET028 硬阈值随机几何图。")
WaxmanModel = _net_wrapper(
    lambda nx, seed: nx.waxman_graph(120, beta=0.5, alpha=0.05, seed=seed),
    "NET031", "NET031 Waxman 空间网络模型。")
SBMModel = _net_wrapper(
    lambda nx, seed: nx.stochastic_block_model(
        [40, 40, 40],
        [[0.5, 0.05, 0.02], [0.05, 0.4, 0.05], [0.02, 0.05, 0.5]],
        seed=seed),
    "NET032", "NET032 随机块模型 SBM（三社团）。")
def _kronecker(nx, seed):
    base = nx.to_numpy_array(nx.barabasi_albert_graph(8, 3, seed=seed))
    A = base
    for _ in range(2):
        A = np.kron(A, base)
    return nx.from_numpy_array((A > 0).astype(float))


KroneckerModel = _net_wrapper(_kronecker,
    "NET036", "NET036 随机 Kronecker 图（2^k 网格幂迭代）。")
ForestFireNetModel = _net_wrapper(
    lambda nx, seed: nx.barabasi_albert_graph(100, 2, seed=seed),
    "NET048", "NET048 Forest Fire 网络增长（BA 代理：重尾等价近似）。")

# NET024 Newman-Watts 加捷径小世界
NewmanWattsModel = _net_wrapper(
    lambda nx, seed: nx.newman_watts_strogatz_graph(120, 4, 0.1, seed=seed),
    "NET024", "NET024 Newman–Watts 加捷径小世界。")


ALL_NET_MODELS = {
    "NET001": Rule30Model, "NET002": Rule90Model, "NET003": Rule110Model,
    "NET004": Rule184Model, "NET005": GameOfLifeModel,
    "NET006": GreenbergHastingsModel, "NET007": CyclicCAModel,
    "NET008": ForestFireModel, "NET016": FisherKPPModel,
    "NET051": SIModel, "NET054": SIRSNetModel, "NET056": SEIRSNetModel,
    "NET057": SEIRDNetModel, "NET058": SEIARNetModel,
    "NET059": SIRVitalNetModel, "NET060": SIRVNetModel,
    "NET063": EdgeSIRModel, "NET064": MarkovSIRModel,
    "NET066": ErlangStageSIRModel, "NET068": RossMacdonaldModel,
    "NET019": ConfigurationModel, "NET021": ChungLuModel,
    "NET022": RandomRegularModel, "NET024": NewmanWattsModel,
    "NET026": HolmeKimModel, "NET028": RandomGeometricModel,
    "NET031": WaxmanModel, "NET032": SBMModel, "NET036": KroneckerModel,
    "NET048": ForestFireNetModel,
}


def build_all_net():
    return {mid: cls() for mid, cls in ALL_NET_MODELS.items()}
