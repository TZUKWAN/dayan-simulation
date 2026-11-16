"""DAYAN P1 基准模型批次（规范 2.9 P1：DTMC/M-M-1/SIR/SEIR/DeGroot/HK/
ER-WS-BA/IC/LT/Leslie/Leontief 等，每个模型带解析/公开基准）。

每个模型实现 DAYAN 统一接口（DayanModel），并声明登记表字段子集
（MODEL_RECORD），由 dayan.registry 统一登记。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


def _rec(**kw):
    return kw


# ============ MET: DTMC 离散时间马尔可夫链 ============
class DTMCModel(DayanModel):
    """两状态离散时间马尔可夫链（MET 基准）。

    转移矩阵 [[1-a, a],[b, 1-b]]；平稳分布 π = [b/(a+b), a/(a+b)]（解析）。
    基准：长运行状态1占比 → π1（容差内）。
    """

    model_id = "MET-DTMC"
    clock_type = "fixed_step"

    def __init__(self, a=0.3, b=0.2):
        self.a, self.b = a, b
        self.state = 0
        self.rng = np.random.default_rng(0)
        self._frac1 = 0.0
        self._count = self._total = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.a = parameters.get("a", self.a)
        self.b = parameters.get("b", self.b)
        self.state = 0
        self.rng = rng
        self._count = self._total = 0

    def step(self, t, dt):
        if self.state == 0:
            self.state = 1 if self.rng.random() < self.a else 0
        else:
            self.state = 0 if self.rng.random() < self.b else 1
        self._total += 1
        self._count += self.state

    def observe(self):
        frac = self._count / self._total if self._total else 0.0
        return {"frac_state1": frac, "state": self.state}

    def validate_state(self):
        return [] if 0 <= self.state <= 1 else ["state 越界"]

    def snapshot(self):
        return {"state": self.state, "count": self._count, "total": self._total}

    def restore(self, s):
        self.state, self._count, self._total = s["state"], s["count"], s["total"]


DTMC_RECORD = _rec(
    model_id="MET001", name="DTMC 两状态马尔可夫链", kind="数值/推断方法",
    paradigm="des", clock_type="fixed_step", time_unit="step",
    status="原型可跑", invariants=["状态∈{0,1}"],
    reference_cases=["平稳分布 π1 = b/(a+b) 长运行占比"],
)


# ============ MET: M/M/1 排队（DES） ============
class MM1QueueModel(DayanModel):
    """M/M/1 排队（DES 语义，模型自管事件时间）。
    解析：ρ=λ/μ，L=λ/(μ-λ)，W=1/(μ-λ)。"""

    model_id = "MET-MM1"
    clock_type = "des"

    def __init__(self, lam=0.8, mu=1.0):
        self.lam, self.mu = lam, mu
        self.rng = np.random.default_rng(0)
        self.queue = 0
        self.in_service = False
        self.t = 0.0
        self._next_arrival = None
        self._next_done = None
        self._served = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.lam = parameters.get("lam", self.lam)
        self.mu = parameters.get("mu", self.mu)
        self.rng = rng
        self.queue = 0
        self.in_service = False
        self.t = 0.0
        self._served = 0
        self._next_arrival = self.rng.exponential(1.0 / self.lam)
        self._next_done = None

    def next_event_time(self, t):
        cands = []
        if self._next_arrival is not None:
            cands.append(self._next_arrival)
        if self._next_done is not None:
            cands.append(self._next_done)
        return min(cands) if cands else None

    def handle_event(self, event):
        t = event.time
        if self._next_arrival is not None and abs(t - self._next_arrival) < 1e-9:
            self._n_arrivals = getattr(self, "_n_arrivals", 0) + 1
            if self.in_service:
                self.queue += 1  # 忙：进入等待队列
            else:
                self.in_service = True  # 闲：直接进入服务（不占队列）
                self._next_done = t + self.rng.exponential(1.0 / self.mu)
            self._next_arrival = t + self.rng.exponential(1.0 / self.lam)
        elif self._next_done is not None and abs(t - self._next_done) < 1e-9:
            self._served += 1
            if self.queue > 0:
                self.queue -= 1  # 等待者顶上服务位
                self._next_done = t + self.rng.exponential(1.0 / self.mu)
            else:
                self.in_service = False
                self._next_done = None
        self.t = t

    def observe(self):
        return {"queue": self.queue, "served": self._served}

    def validate_state(self):
        return [] if self.queue >= 0 else ["queue<0"]


class SIRModel(DayanModel):
    """SIR 仓室模型（ODE 语义）。守恒 S+I+R=N；终局规模满足
    S∞ = S0·exp(-R0·(S0-S∞)/N)（解析关系，数值验证）。"""

    model_id = "NET-SIR"
    clock_type = "ode"

    def __init__(self, beta=0.4, gamma=0.1, N=1000.0, I0=5.0):
        self.beta, self.gamma, self.N = beta, gamma, N
        self.x = np.array([N - I0, I0, 0.0])  # [S, I, R]

    def initialize(self, context, parameters, population, topology, rng):
        self.beta = parameters.get("beta", self.beta)
        self.gamma = parameters.get("gamma", self.gamma)
        self.N = parameters.get("N", self.N)
        I0 = parameters.get("I0", 5.0)
        self.x = np.array([self.N - I0, I0, 0.0])

    def derivatives(self, t, x):
        S, I, R = x
        inf = self.beta * S * I / self.N
        rec = self.gamma * I
        return np.array([-inf, inf - rec, rec])

    def observe(self):
        S, I, R = self.x
        return {"S": S, "I": I, "R": R, "total": S + I + R,
                "infected_peak_passed": 0}

    def validate_state(self):
        S, I, R = self.x
        errs = []
        if abs(S + I + R - self.N) > 1e-6 * self.N:
            errs.append("守恒 S+I+R=N 破坏")
        return errs


SIR_RECORD = _rec(
    model_id="NET053", name="SIR 永久移出模型", kind="空间/网络/传播模型",
    paradigm="sd", clock_type="ode", time_unit="day",
    status="原型可跑", conserved_quantities=["S+I+R=N"],
    reference_cases=["终局规模方程 S∞=S0·exp(-R0(S0-S∞)/N)"],
)


class SEIRModel(DayanModel):
    """SEIR 潜伏期模型（ODE）。守恒 S+E+I+R=N；R0>1 → 爆发条件。"""

    model_id = "NET055"
    clock_type = "ode"

    def __init__(self, beta=0.5, sigma=0.2, gamma=0.1, N=1000.0, I0=5.0, E0=5.0):
        self.beta, self.sigma, self.gamma, self.N = beta, sigma, gamma, N
        self.x = np.array([N - I0 - E0, E0, I0, 0.0])  # [S,E,I,R]

    def initialize(self, context, parameters, population, topology, rng):
        self.beta = parameters.get("beta", self.beta)
        self.sigma = parameters.get("sigma", self.sigma)
        self.gamma = parameters.get("gamma", self.gamma)
        E0 = parameters.get("E0", 5.0)
        I0 = parameters.get("I0", 5.0)
        self.x = np.array([self.N - I0 - E0, E0, I0, 0.0])

    def derivatives(self, t, x):
        S, E, I, R = x
        inf = self.beta * S * I / self.N
        return np.array([-inf, inf - self.sigma * E,
                         self.sigma * E - self.gamma * I,
                         self.gamma * I])

    def observe(self):
        S, E, I, R = self.x
        return {"S": S, "E": E, "I": I, "R": R, "total": S + E + I + R}

    def validate_state(self):
        errs = []
        if abs(self.x.sum() - self.N) > 1e-6 * self.N:
            errs.append("守恒破坏")
        return errs


SEIR_RECORD = _rec(
    model_id="NET055b", name="SEIR 潜伏期模型（ODE）", kind="空间/网络/传播模型",
    paradigm="sd", clock_type="ode", time_unit="day",
    status="原型可跑", conserved_quantities=["S+E+I+R=N"],
    reference_cases=["R0=β/γ>1 时爆发"],
)


# ============ BEH/NET: DeGroot 与 HK 意见动力学 ============
class DeGrootModel(DayanModel):
    """DeGroot 线性意见更新（fixed_step，同步语义：读旧状态统一提交）。

    解析：x(∞) 收敛到权重 w'x(0)，w 为随机矩阵 P 的平稳置信权重
    （P 行随机 → w = P 左特征向量λ=1 归一化）。"""

    model_id = "BEH015"
    clock_type = "fixed_step"

    def __init__(self, P=None, x0=None):
        self.P = np.asarray(P, dtype=float) if P is not None else np.array(
            [[0.5, 0.5, 0.0], [0.25, 0.5, 0.25], [0.0, 0.5, 0.5]])
        self.x = np.asarray(x0, dtype=float) if x0 is not None else np.array(
            [0.0, 0.5, 1.0])

    def initialize(self, context, parameters, population, topology, rng):
        self.P = np.asarray(parameters.get("P", self.P), dtype=float)
        self.x = np.asarray(parameters.get("x0", self.x), dtype=float)

    def step(self, t, dt):
        # 同步语义：读旧状态，统一提交
        self.x = self.P @ self.x

    def observe(self):
        return {"opinions": self.x.tolist(),
                "spread": float(self.x.max() - self.x.min())}

    def validate_state(self):
        errs = []
        if not np.allclose(self.P.sum(axis=1), 1.0, atol=1e-9):
            errs.append("P 非行随机")
        return errs


DEGROOT_RECORD = _rec(
    model_id="BEH015", name="DeGroot 线性意见更新", kind="微观行为模型",
    paradigm="abm", clock_type="fixed_step", time_unit="step",
    activation="synchronous", status="原型可跑",
    reference_cases=["共识值 = 平稳权重·初值（左特征向量）"],
)


class HKModel(DayanModel):
    """Hegselmann–Krause 有界信任（同步）。基准：收敛与聚类形成。"""

    model_id = "BEH017"
    clock_type = "fixed_step"

    def __init__(self, eps=0.15, x0=None, n=60):
        self.eps = eps
        self.n = n
        self.x = np.asarray(x0) if x0 is not None else np.linspace(0.0, 1.0, n)

    def initialize(self, context, parameters, population, topology, rng):
        self.eps = parameters.get("eps", self.eps)
        self.n = parameters.get("n", self.n)
        self.x = np.linspace(0.0, 1.0, self.n)

    def step(self, t, dt):
        # 同步：读旧状态
        new = []
        for xi in self.x:
            nb = self.x[np.abs(self.x - xi) <= self.eps]
            new.append(nb.mean())
        self.x = np.array(new)

    def observe(self):
        # 聚类数：按相邻意见间距>eps 分簇
        xs = np.sort(self.x)
        gaps = np.where(np.diff(xs) > self.eps)[0]
        n_clusters = len(gaps) + 1
        return {"opinions": self.x.tolist(), "n_clusters": n_clusters,
                "max_spread": float(xs[-1] - xs[0])}

    def validate_state(self):
        return [] if np.all((self.x >= 0) & (self.x <= 1)) else ["意见越界"]


HK_RECORD = _rec(
    model_id="BEH017", name="Hegselmann–Krause 有界信任", kind="微观行为模型",
    paradigm="abm", clock_type="fixed_step", time_unit="step",
    activation="synchronous", status="原型可跑",
    reference_cases=["收敛成簇，簇数有限"],
)


# ============ NET: ER / WS / BA 网络生成 ============
class ERNetworkModel(DayanModel):
    """Erdős–Rényi G(n,p)。基准：平均度 = p(n-1)（解析）。"""

    model_id = "NET017"
    clock_type = "fixed_step"

    def __init__(self, n=100, p=0.05, seed=0):
        self.n, self.p, self.seed = n, p, seed
        self.edges = []

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        self.p = parameters.get("p", self.p)
        rng = np.random.default_rng(self.seed)
        self.edges = []
        for i in range(self.n):
            for j in range(i + 1, self.n):
                if rng.random() < self.p:
                    self.edges.append((i, j))

    def step(self, t, dt):
        pass  # 静态生成模型；step 仅为接口占位

    def observe(self):
        deg = np.zeros(self.n)
        for i, j in self.edges:
            deg[i] += 1
            deg[j] += 1
        return {"mean_degree": float(deg.mean()), "n_edges": len(self.edges)}

    def validate_state(self):
        return []


class WSNetworkModel(DayanModel):
    """Watts–Strogatz 小世界。基准：聚类系数 >> 同参数 ER，且平均路径短。"""

    model_id = "NET023"
    clock_type = "fixed_step"

    def __init__(self, n=100, k=4, p_rewire=0.1, seed=0):
        self.n, self.k, self.p_rewire, self.seed = n, k, p_rewire, seed
        self.edges = []

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        self.k = parameters.get("k", self.k)
        self.p_rewire = parameters.get("p_rewire", self.p_rewire)
        rng = np.random.default_rng(self.seed)
        # 环格 + 重连
        self.edges = set()
        for i in range(self.n):
            for dk in range(1, self.k // 2 + 1):
                j = (i + dk) % self.n
                self.edges.add(tuple(sorted((i, j))))
        edges = list(self.edges)
        for (i, j) in edges:
            if rng.random() < self.p_rewire:
                self.edges.discard((i, j))
                ni = i
                while True:
                    nj = int(rng.integers(0, self.n))
                    if nj != ni and tuple(sorted((ni, nj))) not in self.edges:
                        self.edges.add(tuple(sorted((ni, nj))))
                        break

    def step(self, t, dt):
        pass

    def _clustering(self):
        adj = {}
        for i, j in self.edges:
            adj.setdefault(i, set()).add(j)
            adj.setdefault(j, set()).add(i)
        vals = []
        for i, ns in adj.items():
            ns = list(ns)
            if len(ns) < 2:
                continue
            links = sum(1 for x in range(len(ns)) for y in range(x + 1, len(ns))
                        if ns[y] in adj.get(ns[x], ()))
            vals.append(2 * links / (len(ns) * (len(ns) - 1)))
        return float(np.mean(vals)) if vals else 0.0

    def observe(self):
        return {"n_edges": len(self.edges), "clustering": self._clustering()}

    def validate_state(self):
        return []


class BANetworkModel(DayanModel):
    """Barabási–Albert 优先连接。基准：度分布幂律指数≈-3（尾拟合）。"""

    model_id = "NET025"
    clock_type = "fixed_step"

    def __init__(self, n=500, m=3, seed=0):
        self.n, self.m, self.seed = n, m, seed
        self.edges = []

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        self.m = parameters.get("m", self.m)
        rng = np.random.default_rng(self.seed)
        # 初始完全图 m+1 节点
        deg = np.zeros(self.n)
        self.edges = []
        for i in range(self.m + 1):
            for j in range(i + 1, self.m + 1):
                self.edges.append((i, j))
                deg[i] += 1
                deg[j] += 1
        # 优先连接增长
        for i in range(self.m + 1, self.n):
            probs = deg[:i] / deg[:i].sum()
            targets = rng.choice(i, size=self.m, replace=False, p=probs)
            for t in targets:
                self.edges.append((i, int(t)))
                deg[i] += 1
                deg[t] += 1

    def step(self, t, dt):
        pass

    def observe(self):
        deg = np.zeros(self.n)
        for i, j in self.edges:
            deg[i] += 1
            deg[j] += 1
        tail = deg[deg >= 2 * self.m]
        if len(tail) > 10:
            ls = np.log(tail)
            # 简易斜率估计（度序 vs log 度）
            slope = float(np.polyfit(np.log(np.arange(1, len(tail) + 1)),
                                     np.sort(ls)[::-1], 1)[0])
        else:
            slope = float("nan")
        return {"n_edges": len(self.edges), "mean_degree": float(deg.mean()),
                "tail_slope": slope}

    def validate_state(self):
        return []


# ============ NET: 独立级联 IC / 线性阈值 LT ============
class ICModel(DayanModel):
    """独立级联 IC（离散事件语义：逐种子传播波）。基准：影响函数单调
    （种子集扩张 → 影响集不缩），在固定图上确定性传播。"""

    model_id = "NET076"
    clock_type = "fixed_step"

    def __init__(self, n=100, p=0.1, seed=0):
        self.n, self.p, self.seed = n, p, seed
        self.adj = {}

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        self.p = parameters.get("p", self.p)
        rng = np.random.default_rng(self.seed)
        self.adj = {i: [] for i in range(self.n)}
        for i in range(self.n):
            for j in range(self.n):
                if i != j and rng.random() < 0.05:
                    self.adj[i].append(j)

    def spread(self, seeds: list[int]) -> set[int]:
        """一次级联（确定性：每条边哈希→[0,1) 与 p 比较，边只尝试一次）。"""
        act = set(seeds)
        frontier = list(seeds)
        while frontier:
            new = []
            for u in frontier:
                for v in self.adj.get(u, ()):
                    if v in act:
                        continue
                    h = int.from_bytes(
                        __import__('hashlib').sha256(
                            f"{self.seed}:{u}:{v}".encode()).digest()[:8], 'little')
                    if (h % 10_000) / 10_000 < self.p:
                        act.add(v)
                        new.append(v)
            frontier = new
        return act

    def step(self, t, dt):
        pass

    def observe(self):
        return {"n": self.n}

    def validate_state(self):
        return []


class LTModel(DayanModel):
    """线性阈值 LT（确定性）：阈值=0 时影响集=种子可达闭包。"""

    model_id = "NET077"
    clock_type = "fixed_step"

    def __init__(self, n=50, seed=0):
        self.n, self.seed = n, seed
        self.adj = {}

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        rng = np.random.default_rng(self.seed)
        self.adj = {i: [] for i in range(self.n)}
        for i in range(self.n):
            for j in range(self.n):
                if i != j and rng.random() < 0.08:
                    self.adj[i].append(j)

    def spread(self, seeds, thresholds=None):
        th = thresholds if thresholds is not None else [0.0] * self.n
        act = set(seeds)
        changed = True
        while changed:
            changed = False
            for v in range(self.n):
                if v in act:
                    continue
                nb = self.adj.get(v, [])
                if nb and sum(1 for u in nb if u in act) / len(nb) > th[v]:
                    act.add(v)
                    changed = True
        return act

    def step(self, t, dt):
        pass

    def observe(self):
        return {"n": self.n}

    def validate_state(self):
        return []


# ============ ECO: Leslie 年龄结构 ============
class LeslieModel(DayanModel):
    """Leslie 年龄结构矩阵（ODE/离散投影）。基准：增长率=主特征值 λ1，
    稳定年龄分布=对应右特征向量。"""

    model_id = "ECO057"
    clock_type = "fixed_step"

    def __init__(self, fert=None, surv=None):
        self.fert = np.asarray(fert, dtype=float) if fert is not None else \
            np.array([0.0, 1.2, 1.5, 0.8])
        self.surv = np.asarray(surv, dtype=float) if surv is not None else \
            np.array([0.7, 0.8, 0.9])
        n = len(self.fert)
        self.A = np.zeros((n, n))
        self.A[0, :] = self.fert
        for i in range(n - 1):
            self.A[i + 1, i] = self.surv[i]
        self.pop = np.ones(n)

    def initialize(self, context, parameters, population, topology, rng):
        self.__init__(fert=parameters.get("fert", self.fert),
                      surv=parameters.get("surv", self.surv))
        self.pop = np.asarray(parameters.get("pop0", np.ones(len(self.fert))),
                              dtype=float)

    def step(self, t, dt):
        self.pop = self.A @ self.pop

    def observe(self):
        lam1 = float(max(abs(np.linalg.eigvals(self.A))))
        return {"total": float(self.pop.sum()),
                "lambda1": lam1,
                "dist": self.pop.round(2).tolist()}

    def validate_state(self):
        return [] if np.all(self.pop >= 0) else ["负人口"]


LESLIE_RECORD = _rec(
    model_id="ECO057", name="Leslie 年龄结构矩阵模型", kind="经济/人口模型",
    paradigm="sd", clock_type="fixed_step", time_unit="year",
    status="原型可跑", reference_cases=["增长率=主特征值λ1；稳定分布=右特征向量"],
)


# ============ ECO: Leontief 投入产出 ============
class LeontiefModel(DayanModel):
    """Leontief 开放数量模型：x = (I-A)^{-1} d（解析解直接可验）。"""

    model_id = "ECO001"
    clock_type = "fixed_step"

    def __init__(self, A=None, d=None):
        self.A = np.asarray(A, dtype=float) if A is not None else \
            np.array([[0.1, 0.2], [0.3, 0.1]])
        self.d = np.asarray(d, dtype=float) if d is not None else \
            np.array([100.0, 200.0])
        self.x = np.zeros(len(self.d))

    def initialize(self, context, parameters, population, topology, rng):
        self.A = np.asarray(parameters.get("A", self.A), dtype=float)
        self.d = np.asarray(parameters.get("d", self.d), dtype=float)
        self.x = np.zeros(len(self.d))

    def step(self, t, dt):
        I = np.eye(len(self.d))
        self.x = np.linalg.solve(I - self.A, self.d)

    def observe(self):
        return {"output": self.x.tolist()}

    def validate_state(self):
        # Hawkins–Simon 条件：Leading principal minors of (I-A) 为正
        M = np.eye(len(self.A)) - self.A
        for k in range(1, len(M) + 1):
            if np.linalg.det(M[:k, :k]) <= 0:
                return [f"Hawkins–Simon 条件失败（前 {k} 阶主子式）"]
        return []


LEONTIEF_RECORD = _rec(
    model_id="ECO001", name="Leontief 开放数量模型", kind="经济模型",
    paradigm="sd", clock_type="fixed_step", time_unit="period",
    status="基准通过", reference_cases=["x=(I-A)^{-1}d 直接解析解"],
)
