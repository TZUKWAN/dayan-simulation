"""DAYAN SYS 剩余条目（SYS004/008/009/011/012/016/020/023/024/027/033/043 等）。

新实现：GI/G/1 一般到达一般服务模拟、Gordon–Newell 封闭网络（乘积形式）、
BCMP 多类排队、有色 Petri 网、并行 DEVS、动态结构 DEVS、隐半马尔可夫（HSMM）。
并补 wrapper 映射：SYS004→有限容量多服务器、SYS008→M/D/1、SYS018→随机 PN、
SYS020→定时弧 PN、SYS027→DTMC、SYS033→Galton–Watson。
"""
from __future__ import annotations

from collections import deque

import numpy as np

from ..core import DayanModel
from .met_models import gillespie_ssa  # noqa: F401  (SYS018 用核心 SSA)
from .sys_models import (MD1QueueModel, PetriNetModel, TimedPetriModel)  # noqa: F401


class GIG1QueueModel(DayanModel):
    """SYS009 一般到达一般服务 GI/G/1：指数到达 + 均匀服务模拟；
    基准：Kingman 公式近似 Wq ≈ (ρ/(1-ρ))·(c_a²+c_s²)/2·E[S]。"""

    model_id = "SYS009"
    clock_type = "fixed_step"

    def __init__(self, lam=0.6, s_mean=1.0, c_s=0.3):
        self.lam, self.s_mean, self.c_s = lam, s_mean, c_s
        self.q = deque()
        self.busy_until = -1.0
        self.clock = 0.0
        self.wait_sum = 0.0
        self.n = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.q = deque()
        self.busy_until = -1.0
        self.clock = 0.0
        self.wait_sum = 0.0
        self.n = 0

    def _draw_service(self):
        # 均匀 [s_mean(1-c_s), s_mean(1+c_s)]
        w = self.s_mean * self.c_s
        return self.rng_.uniform(self.s_mean - w, self.s_mean + w)

    def step(self, t, dt):
        for _ in range(self.rng_.poisson(self.lam * dt)):
            if self.clock >= self.busy_until:
                self.busy_until = self.clock + self._draw_service()
            else:
                self.q.append(self.clock)
            self.n += 1
        while self.q and self.clock >= self.busy_until:
            self.wait_sum += self.clock - self.q.popleft()
            self.busy_until = self.clock + self._draw_service()
        self.clock += dt

    def observe(self):
        rho = self.lam * self.s_mean
        ca2 = 1.0  # 指数到达
        cs2 = (self.c_s ** 2) / 3.0        # U[m-w,m+w] 的 scv=var/mean²=c_s²/3
        wq_kingman = (rho / max(1 - rho, 1e-6)) * ((ca2 + cs2) / 2) * self.s_mean
        return {"Wq_sim": float(self.wait_sum / max(self.n, 1)),
                "Wq_kingman": float(wq_kingman)}

    def validate_state(self):
        return [] if self.lam * self.s_mean < 1 else ["ρ≥1"]


class GordonNewellModel(DayanModel):
    """SYS011 Gordon–Newell 封闭网络：N 个顾客在 K 站循环；
    均值分析（MVA）对照模拟吞吐。"""

    model_id = "SYS011"
    clock_type = "fixed_step"

    def __init__(self, N=6, mu=(1.0, 1.5), visit=(1.0, 0.6)):
        self.N, self.mu, self.visit = N, np.asarray(mu, float), \
            np.asarray(visit, float)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.n = np.zeros(len(self.mu), int)
        self.n[0] = self.N
        self.clock = 0.0
        self.done = 0
        self.clock0 = 0.0

    def _mva(self):
        """均值分析：逐站递推响应时间与吞吐。"""
        n_vec = np.zeros(len(self.mu))
        for n in range(1, self.N + 1):
            R = self.visit * (1 + n_vec) / self.mu
            X = n / R.sum()
            n_vec = X * R
        return float(X)

    def step(self, t, dt):
        k = len(self.mu)
        for i in range(k):
            if self.n[i] > 0:
                done = self.rng_.poisson(self.mu[i] * dt)
                for _ in range(min(done, self.n[i])):
                    self.n[i] -= 1
                    j = (i + 1) % k
                    self.n[j] += 1
                    if j == 0:
                        self.done += 1
        self.clock += dt

    def observe(self):
        X_mva = self._mva()
        X_sim = self.done / max(self.clock, 1e-9)
        return {"X_mva": float(X_mva), "X_sim": float(X_sim),
                "n": self.n.tolist()}

    def validate_state(self):
        return [] if self.n.sum() == self.N else ["闭环顾客数不守恒"]


class BCMPModel(DayanModel):
    """SYS012 BCMP 多类排队：两类顾客共享单站（处理器共享近似）；
    基准：MVA 两类均值 = λR/(1-ρ) 近似。"""

    model_id = "SYS012"
    clock_type = "fixed_step"

    def __init__(self, lam=(0.4, 0.3), mu=(1.0, 1.2)):
        self.lam = np.asarray(lam, float)
        self.mu = np.asarray(mu, float)
        self.n = np.zeros(2, int)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.n = np.zeros(2, int)
        self.clock = 0.0
        self.le = np.zeros(2)
        self.T = 0.0

    def step(self, t, dt):
        for c in range(2):
            for _ in range(self.rng_.poisson(self.lam[c] * dt)):
                self.n[c] += 1
            done = self.rng_.poisson(self.mu[c] * dt)
            self.n[c] = max(0, self.n[c] - done)
        self.T += dt
        self.le += self.n * dt

    def observe(self):
        rho = (self.lam / self.mu).sum()
        L_ps = self.lam / np.maximum(self.mu * (1 - rho), 1e-6)
        return {"L_sim": (self.le / max(self.T, 1e-9)).tolist(),
                "L_ps_formula": L_ps.tolist(), "rho": float(rho)}

    def validate_state(self):
        return []


class ColoredPetriModel(DayanModel):
    """SYS016 有色 Petri 网：token 带'颜色'（类型标签），变迁按颜色使能。
    基准：红/蓝 token 各自循环守恒。"""

    model_id = "SYS016"
    clock_type = "fixed_step"

    def __init__(self, n_colors=2, capacity=3):
        self.n_colors, self.capacity = n_colors, capacity
        # 库所 p0(红等待) --t_r--> p1(红完成); p2(蓝) --t_b--> p3(蓝完成)
        self.marking = {("p0", 0): capacity, ("p2", 1): capacity}

    def initialize(self, context, parameters, population, topology, rng):
        cap = int(parameters.get("capacity", self.capacity))
        self.marking = {("p0", 0): cap, ("p2", 1): cap}
        self.fired = 0

    def step(self, t, dt):
        # 每色循环：p_wait[c] --t_c--> p_done[c] -->（回收弧）--> p_wait[c]
        for c in range(self.n_colors):
            src = (f"p{2 * c}", c)
            dst = (f"p{2 * c + 1}", c)
            if self.marking.get(src, 0) > 0:
                self.marking[src] = self.marking.get(src, 0) - 1
                self.marking[dst] = self.marking.get(dst, 0) + 1
                self.fired += 1
                # 回收弧：完成的 token 回到等待库所（循环网）
                self.marking[dst] -= 1
                self.marking[src] = self.marking.get(src, 0) + 1

    def observe(self):
        per_color = {}
        for (p, c), v in self.marking.items():
            per_color.setdefault(c, 0)
            per_color[c] += v
        return {"marking": {f"{p}[c{c}]": v for (p, c), v in self.marking.items()},
                "per_color": per_color, "fired": self.fired}

    def validate_state(self):
        return []


class ParallelDEVModel(DayanModel):
    """SYS023 并行 DEVS：多原子同刻并发事件，归并后统一状态转移。
    基准：并发事件数 = 原子数 × 周期数。"""

    model_id = "SYS023"
    clock_type = "fixed_step"

    def __init__(self, n_atoms=4, period=2.0):
        self.n_atoms, self.period = n_atoms, period
        self.sigma = np.full(n_atoms, period)
        self.events = np.zeros(n_atoms)

    def initialize(self, context, parameters, population, topology, rng):
        self.sigma = np.full(self.n_atoms, self.period)
        self.events = np.zeros(self.n_atoms)
        self.clock = 0.0

    def step(self, t, dt):
        self.clock += dt
        self.sigma -= dt
        fired = self.sigma <= 0
        self.events[fired] += 1
        self.sigma[fired] = self.period      # 并发归并：同刻全部重推进

    def observe(self):
        return {"events_per_atom": self.events.tolist(),
                "total": int(self.events.sum()),
                "expected_total": int(self.clock / self.period * self.n_atoms)}

    def validate_state(self):
        return []


class DynamicStructureDEVModel(DayanModel):
    """SYS024 动态结构 DEVS：模型集合随事件增减（工作者按负载自增/自减）。
    基准：结构变化后守恒（队列+处理中+完成 = 到达总数）。"""

    model_id = "SYS024"
    clock_type = "fixed_step"

    def __init__(self, lam=2.0, mu=1.0):
        self.lam, self.mu = lam, mu
        self.workers = 1
        self.queue = deque()
        self.arrived = 0
        self.completed = 0
        self.busy = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.workers = 1
        self.queue = deque()
        self.arrived = self.completed = self.busy = 0
        self.clock = 0.0
        self.departs = []
        self.spawn_timer = 10.0

    def step(self, t, dt):
        for _ in range(self.rng_.poisson(self.lam * dt)):
            self.arrived += 1
            self.queue.append(self.clock)
        # 动态结构：队列长 → 加工作者；空闲多 → 减
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            if len(self.queue) > 3 and self.workers < 4:
                self.workers += 1
            elif len(self.queue) == 0 and self.workers > 1:
                self.workers -= 1
            self.spawn_timer = 10.0
        done = [d for d in self.departs if d <= self.clock]
        self.departs = [d for d in self.departs if d > self.clock]
        self.completed += len(done)
        self.busy -= len(done)
        while self.busy < self.workers and self.queue:
            self.queue.popleft()
            self.busy += 1
            self.departs.append(self.clock + self.rng_.exponential(1 / self.mu))
        self.clock += dt

    def observe(self):
        return {"workers": self.workers, "arrived": self.arrived,
                "completed": self.completed, "queued": len(self.queue),
                "conserv": int(self.arrived - self.completed - len(self.queue)
                               - self.busy)}

    def validate_state(self):
        return []


class HSMMModel(DayanModel):
    """SYS043 隐半马尔可夫（显式驻留）：几何驻留的 HSMM 前向滤波简化。"""

    model_id = "SYS043"
    clock_type = "fixed_step"

    def __init__(self, T=150):
        self.T = T
        self.result = {}

    def initialize(self, context, parameters, population, topology, rng):
        # 两态：驻留时长几何分布（均值 8 / 4），观测同 HMM
        A = np.array([[0.9, 0.1], [0.25, 0.75]])
        B = np.array([[0.85, 0.15], [0.2, 0.8]])
        s = np.zeros(self.T, int)
        o = np.zeros(self.T, int)
        stay = 0
        cur = int(rng.random() < 0.5)
        for t in range(self.T):
            if stay <= 0:
                cur = int(rng.random() < A[cur][1])
                stay = rng.geometric(0.3 if cur == 0 else 0.5)
            s[t] = cur
            o[t] = int(rng.random() < B[cur][1])
            stay -= 1
        # 前向滤波（观测更新 + 转移，驻留信息不显式建模——HSMM 近似）
        f = np.array([0.5, 0.5])
        fhist = []
        for t in range(self.T):
            if t > 0:
                f = A.T @ f
            like = B[:, o[t]]
            f = f * like
            f = f / max(f.sum(), 1e-12)
            fhist.append(f.copy())
        acc = float(np.mean([np.argmax(x) == r for x, r in zip(fhist, s)]))
        self.result = {"filter_acc": acc}

    def step(self, t, dt):
        pass

    def observe(self):
        return self.result

    def validate_state(self):
        return []


# ---- wrapper 映射（已有实现挂目录 ID）----
class Sys004FiniteCapacityModel(DayanModel):
    """SYS004 有限容量多服务器（容量 K 的 M/M/c/K，同 SYS005 机制）。"""

    model_id = "SYS004"

    def __init__(self, c=3, K=6, lam=2.5, mu=1.0):
        from .sys_models import MCLRQueueModel
        self._impl = MCLRQueueModel(c=c, K=K, lam=lam, mu=mu)

    def initialize(self, context, parameters, population, topology, rng):
        self._impl.initialize(context, parameters, population, topology, rng)

    def step(self, t, dt):
        self._impl.step(t, dt)

    def observe(self):
        return self._impl.observe()

    def validate_state(self):
        return self._impl.validate_state()


class Sys008DeterministicModel(DayanModel):
    """SYS008 确定服务单服务器（= M/D/1，SYS007 同机制）。"""

    model_id = "SYS008"

    def __init__(self, lam=0.6, mu=1.0):
        self._impl = MD1QueueModel(lam=lam, mu=mu)

    def initialize(self, context, parameters, population, topology, rng):
        self._impl.initialize(context, parameters, population, topology, rng)

    def step(self, t, dt):
        self._impl.step(t, dt)

    def observe(self):
        return self._impl.observe()

    def validate_state(self):
        return self._impl.validate_state()


class Sys018StochasticPetriModel(DayanModel):
    """SYS018 随机 Petri 网（指数变迁率 = SYS019 同机制别名）。"""

    model_id = "SYS018"

    def __init__(self, rates=(1.0, 1.0)):
        from .sys_models import StochasticPetriModel
        self._impl = StochasticPetriModel(rates=rates)

    def initialize(self, context, parameters, population, topology, rng):
        self._impl.initialize(context, parameters, population, topology, rng)

    def observe(self):
        return self._impl.observe()

    def validate_state(self):
        return self._impl.validate_state()

    @property
    def clock_type(self):
        return "jump"

    def event_intensities(self, t):
        return self._impl.event_intensities(t)

    def apply_jump(self, t, which):
        self._impl.apply_jump(t, which)


class Sys020TimedArcModel(DayanModel):
    """SYS020 定时弧 Petri 网（弧延迟 = SYS017 TimedPetri 同机制）。"""

    model_id = "SYS020"

    def __init__(self):
        pre = np.array([[1, 0], [0, 1]])
        post = np.array([[0, 1], [1, 0]])
        self._impl = TimedPetriModel(durations=(1.0, 2.0), pre=pre, post=post,
                                     m0=np.array([3, 0]))

    def initialize(self, context, parameters, population, topology, rng):
        self._impl.initialize(context, parameters, population, topology, rng)

    def step(self, t, dt):
        self._impl.step(t, dt)

    def observe(self):
        return self._impl.observe()

    def validate_state(self):
        return self._impl.validate_state()


class Sys027DTMCModel(DayanModel):
    """SYS027 离散时间 Markov 链（幂迭代稳态 + 轨迹频率）。"""

    model_id = "SYS027"
    clock_type = "fixed_step"

    def __init__(self, P=None):
        self.P = np.asarray(P, float) if P is not None else \
            np.array([[0.9, 0.1], [0.2, 0.8]])
        self.state = 0
        self.visits = np.zeros(len(self.P))

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.state = 0
        self.visits = np.zeros(len(self.P))

    def step(self, t, dt):
        self.visits[self.state] += 1
        self.state = int(rng_choice(self.rng_, self.P[self.state]))

    def observe(self):
        evals = np.linalg.eigvals(self.P.T)
        pi = np.abs(np.linalg.eig(self.P.T)[1][:, 0])
        pi = pi / pi.sum()
        freq = self.visits / max(self.visits.sum(), 1)
        return {"pi_analytic": pi.tolist(),
                "visit_freq": freq.tolist()}

    def validate_state(self):
        return []


def rng_choice(rng, p):
    return int(rng.choice(len(p), p=p / max(p.sum(), 1e-12)))


class Sys033GaltonWatsonModel(DayanModel):
    """SYS033 Galton–Watson 分枝过程（泊松后代）：E[Z_n]=m^n，m<1 灭绝。"""

    model_id = "SYS033"
    clock_type = "fixed_step"

    def __init__(self, m=0.5, n0=5):
        self.m, self.n0 = m, n0
        self.n = n0

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.n = int(parameters.get("n0", self.n0))

    def step(self, t, dt):
        self._gen = getattr(self, '_gen', 0) + 1
        if self.n > 0:
            children = self.rng_.poisson(self.m, self.n)
            self.n = int(children.sum())

    def observe(self):
        m, n0 = self.m, self.n0
        gen = int(getattr(self, "_gen", 0))
        return {"alive": self.n, "E_analytic": float(n0 * m ** gen),
                "extinct": bool(self.n == 0)}

    def validate_state(self):
        return []

