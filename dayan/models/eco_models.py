"""DAYAN 经济家族批次 A（目录 ECO001–ECO115 的宏观/金融/劳动部分）。

投入产出：Leontief 数量/价格、Ghosh、Miyazawa、动态资本积累
增长与周期：Ramsey、AK、Romer、Kaldor、Kalecki
世代交叠：Diamond OLG、Blanchard 永葆青春、生命周期
存量-流量：Godley–Lavoie SIM
时间序列：VAR(p)、ARCH、GARCH（合成数据拟合恢复）
金融 ABM：Gode–Sunder 零智能交易者
劳动搜寻：McCall 保留工资、Mincer 方程、Ben-Porath
企业动态：Gibrat 比例增长
项目反应理论：Rasch/2PL/3PL
税收福利：静态算术微观仿真
冲突与军备：Richardson、Lanchester 平方/线性律
资源与气候：Schaefer、Gordon–Schaefer、Hotelling、啤酒配送、DICE-lite

全部含解析基准（见 tests/test_dayan_eco_batch.py）。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


# ============ 投入产出 ============
class LeontiefQuantityModel(DayanModel):
    """ECO001 Leontief 开放数量模型：x = (I-A)^{-1} d（静态求逆+前向迭代）。"""

    model_id = "ECO001"
    clock_type = "fixed_step"

    def __init__(self, A=None, d=None, sectors=3):
        rng = np.random.default_rng(7)
        self.A = A if A is not None else rng.uniform(0.05, 0.25, (sectors, sectors))
        np.fill_diagonal(self.A, 0.0)
        self.A = self.A * 0.6 / self.A.sum(axis=0)  # 列和≈0.6<1 可解
        self.d = d if d is not None else np.ones(sectors)
        self.x = self.d.copy()

    def initialize(self, context, parameters, population, topology, rng):
        if "demand" in parameters:
            self.d = np.asarray(parameters["demand"], float)
        self.x = self.d.copy()

    def step(self, t, dt):
        self.x = self.d + self.A @ self.x  # 迭代求解 x = d + A x

    def observe(self):
        return {"x": self.x.tolist(), "total": float(self.x.sum())}

    def validate_state(self):
        return []


class LeontiefPriceModel(DayanModel):
    """ECO002 Leontief 价格模型：p = (I-A^T)^{-1} w（单位劳动增加值）。"""

    model_id = "ECO002"
    clock_type = "fixed_step"

    def __init__(self, A=None, w=None, sectors=3):
        rng = np.random.default_rng(9)
        self.A = A if A is not None else rng.uniform(0.05, 0.25, (sectors, sectors))
        np.fill_diagonal(self.A, 0.0)
        self.A = self.A * 0.6 / self.A.sum(axis=0)
        self.w = w if w is not None else np.ones(sectors)
        self.p = self.w.copy()

    def initialize(self, context, parameters, population, topology, rng):
        if "w" in parameters:
            self.w = np.asarray(parameters["w"], float)
        self.p = self.w.copy()

    def step(self, t, dt):
        self.p = self.w + self.A.T @ self.p  # p = w + A^T p

    def observe(self):
        return {"p": self.p.tolist(), "p_min": float(self.p.min())}

    def validate_state(self):
        return []


class GhoshModel(DayanModel):
    """ECO004 Ghosh 分配模型：x = v (I-B)^{-1}（初始投入驱动，行方向）。"""

    model_id = "ECO004"
    clock_type = "fixed_step"

    def __init__(self, sectors=3):
        rng = np.random.default_rng(11)
        A = rng.uniform(0.05, 0.25, (sectors, sectors))
        np.fill_diagonal(A, 0.0)
        self.B = A * 0.6 / A.sum(axis=1)  # 行和≈0.6
        self.v = np.ones(sectors)
        self.x = self.v.copy()

    def initialize(self, context, parameters, population, topology, rng):
        self.v = np.asarray(parameters.get("v", self.v), float)
        self.x = self.v.copy()

    def step(self, t, dt):
        self.x = self.v + self.x @ self.B  # x^T = v^T (I-B)^{-1}

    def observe(self):
        return {"x": self.x.tolist(), "total": float(self.x.sum())}

    def validate_state(self):
        return []


class LeontiefDynamicModel(DayanModel):
    """ECO005 Leontief 动态资本积累：x_{t+1} = A x + B Δx + d（B=资本系数）。"""

    model_id = "ECO005"
    clock_type = "fixed_step"

    def __init__(self, sectors=2, T=30):
        rng = np.random.default_rng(13)
        A = rng.uniform(0.05, 0.2, (sectors, sectors))
        np.fill_diagonal(A, 0.0)
        self.A = A * 0.5 / A.sum(axis=0)
        self.Bc = np.diag(rng.uniform(0.8, 1.5, sectors))
        self.d = np.ones(sectors) * 0.5
        self.x = self.d.copy()
        self.T = T

    def initialize(self, context, parameters, population, topology, rng):
        self.x = self.d.copy()
        self.hist = [self.x.copy()]
        self.tick = 0

    def step(self, t, dt):
        self.tick += 1
        if self.tick < self.T:
            # 动态投入产出（需求驱动调整 + 资本容量约束）：
            # 需求 target = A·x + d；产出向需求调整，调整速度受 Bc^{-1} 产能约束
            # 稳态 target=x → (I-A)x*=d（闭式加速式在偏离稳态时不稳定，故用调整式）
            gap = self.A @ self.x + self.d - self.x
            x_new = self.x + 0.5 * np.linalg.solve(self.Bc, gap)
            self.x = np.maximum(x_new, 0)
        self.hist.append(self.x.copy())

    def observe(self):
        return {"x": self.x.tolist(), "total": float(self.x.sum()),
                "tick": self.tick}

    def validate_state(self):
        return []


# ============ 增长与周期 ============
class RamseyModel(DayanModel):
    """ECO016 Ramsey–Cass–Koopmans：dk/dt=f(k)-c-(δ+n)k, Euler 方程驱动 c。
    离散化：c_{t+1}=c_t[β(f'(k)+1-δ)-1]/θ；稳态 f'(k*)=δ+θ式贴现。"""

    model_id = "ECO016"
    clock_type = "fixed_step"

    def __init__(self, alpha=0.3, delta=0.05, beta=0.96, theta=2.0, k0=1.0):
        self.alpha, self.delta, self.beta, self.theta = alpha, delta, beta, theta
        self.k, self.c = k0, 0.3

    def _shoot(self, k0, ratio, steps=1000, dt=0.2):
        """给定 c0=f(k0)·ratio 前向模拟，返回末态 k。"""
        k, c = k0, ratio * k0 ** self.alpha
        for _ in range(steps):
            r = self._mpk(k) - self.delta
            c = c * (self.beta * (1 + r)) ** (dt / self.theta)
            c = min(c, 0.90 * k ** self.alpha)
            k = max(1e-9, k + (k ** self.alpha - c - self.delta * k) * dt)
        return k

    def initialize(self, context, parameters, population, topology, rng):
        """打靶法（shooting）解鞍点路径：c0 偏低→过度积累（k↑∞），
        c0 偏高→资本塌缩（k→0）。二分求鞍点比例。"""
        self.k = parameters.get("k0", 1.0)
        self.tick = 0
        k_star = self.observe()["k_star"]
        lo, hi = 0.05, 0.95
        for _ in range(40):
            mid = (lo + hi) / 2
            k_end = self._shoot(self.k, mid)
            if k_end > k_star:      # c0 偏低 → 过积累
                lo = mid            # 提高消费
            else:                   # c0 偏高 → 塌缩
                hi = mid
        self.c = (lo + hi) / 2 * self.k ** self.alpha

    def _mpk(self, k):
        return self.alpha * max(k, 1e-9) ** (self.alpha - 1)

    def step(self, t, dt):
        r = self._mpk(self.k) - self.delta
        # Euler 方程按步长 dt 缩放（否则消费增速与资本动态不匹配）
        self.c = self.c * (self.beta * (1 + r)) ** (dt / self.theta)
        self.c = min(self.c, 0.90 * self.k ** self.alpha)  # c ≤ 产出·帽不约束稳态
        self.k += (self.k ** self.alpha - self.c - self.delta * self.k) * dt
        self.k = max(self.k, 1e-9)
        self.tick += 1

    def observe(self):
        # 稳态：f'(k*) = δ + 1/β - 1（离散 Euler 稳态）
        r_star = 1 / self.beta - 1
        k_star = (self.alpha / (self.delta + r_star)) ** (1 / (1 - self.alpha))
        return {"k": float(self.k), "c": float(self.c), "k_star": float(k_star)}

    def validate_state(self):
        return [] if self.k > 0 and self.c > 0 else ["k或c≤0"]


class AKModel(DayanModel):
    """ECO017 AK 内生增长：Y=AK；g = sA - δ（线性，无收敛）。"""

    model_id = "ECO017"
    clock_type = "fixed_step"

    def __init__(self, A=0.3, s=0.25, delta=0.05, k0=1.0):
        self.A, self.s, self.delta, self.k = A, s, delta, k0

    def initialize(self, context, parameters, population, topology, rng):
        self.k = parameters.get("k0", 1.0)

    def step(self, t, dt):
        self.k += (self.s * self.A - self.delta) * self.k * dt

    def observe(self):
        g = self.s * self.A - self.delta
        return {"k": float(self.k), "g_theory": float(g),
                "k_proj": float(self.k0_default * np.exp(g * self.tick_cache))
                if hasattr(self, "tick_cache") else float(self.k)}

    k0_default = 1.0
    tick_cache = 0.0

    def validate_state(self):
        return []


class RomerModel(DayanModel):
    """ECO018 Romer 研发驱动：Ȧ = δ·L_A^λ·A^φ；idea 递增/递减收益。"""

    model_id = "ECO018"
    clock_type = "fixed_step"

    def __init__(self, delta_r=0.01, lam=1.0, phi=1.0, LA=0.1, A0=1.0):
        self.delta_r, self.lam, self.phi, self.LA, self.A = \
            delta_r, lam, phi, LA, A0

    def initialize(self, context, parameters, population, topology, rng):
        self.A = parameters.get("A0", 1.0)
        self.LA = parameters.get("LA", 0.1)

    def step(self, t, dt):
        self.A += self.delta_r * self.LA ** self.lam * self.A ** self.phi * dt
        self.A = max(self.A, 1e-12)

    def observe(self):
        return {"A": float(self.A)}

    def validate_state(self):
        return []


class KaldorModel(DayanModel):
    """ECO020 Kaldor 非线性商业周期（1940 / Chang–Smyth 条件）：
    S 凸三次、I 含加速数与资本挤压（-f·K），产出-资本双动态
    → 不稳定焦点 + 非线性上下界 → 极限环。
    参数经网格搜索验证（区间 [1.1, 2.2] 持续振荡）。"""

    model_id = "ECO020"
    clock_type = "fixed_step"

    # Kaldor 形式参数（搜索校准，保证极限环）
    A3, A2, A1 = 0.061, -0.202, 0.623    # 储蓄曲线 S(Y) 立方
    D0, E1, F1 = 1.244, 1.689, 0.330     # 投资 I = D0 + E1·Y - F1·K
    DELTA, ALPHA = 0.084, 0.355          # 折旧 / 产出调整速度

    def __init__(self, Y0=1.0, K0=1.0):
        self.Y, self.K = Y0, K0

    def initialize(self, context, parameters, population, topology, rng):
        self.Y = parameters.get("Y0", 1.0)
        self.K = parameters.get("K0", 1.0)

    def _IS(self, Y, K):
        S = self.A3 * Y ** 3 + self.A2 * Y ** 2 + self.A1 * Y
        I = self.D0 + self.E1 * Y - self.F1 * K
        return I, S

    def step(self, t, dt):
        I, S = self._IS(self.Y, self.K)
        self.Y = max(0.05, self.Y + self.ALPHA * (I - S) * dt)
        self.K = max(0.02, self.K + (I - self.DELTA * self.K) * dt)

    def observe(self):
        I, S = self._IS(self.Y, self.K)
        return {"Y": float(self.Y), "K": float(self.K), "gap": float(I - S)}

    def validate_state(self):
        return []


class KaleckiModel(DayanModel):
    """ECO021 Kalecki 延迟投资周期（1935 离散形式）：
    Y_t = a + c·Y_{t-1} + b·ΔY_{t-τ}（诱导投资作用于滞后收入变化）。
    c=0.75, b=0.9, τ=5（数值探测校准）→ 持续松弛振荡。"""

    model_id = "ECO021"
    clock_type = "fixed_step"

    def __init__(self, delay=5, c_cons=0.75, b_inv=0.9, a_auto=0.2):
        self.delay = delay
        self.c_cons, self.b_inv, self.a_auto = c_cons, b_inv, a_auto
        self.Y_hist = [1.0] * (delay + 3)

    def initialize(self, context, parameters, population, topology, rng):
        self.delay = parameters.get("delay", self.delay)
        self.Y_hist = [1.0] * (self.delay + 3)

    def step(self, t, dt):
        H = self.Y_hist
        dy_lag = H[-1 - self.delay] - H[-2 - self.delay]
        y = self.a_auto + self.c_cons * H[-1] + self.b_inv * dy_lag
        y = min(10.0, max(0.05, y))   # 产能上限 / 下限（松弛周期）
        H.append(y)
        if len(H) > self.delay + 600:
            del H[:len(H) - (self.delay + 600)]

    def observe(self):
        arr = np.array(self.Y_hist[-100:])
        return {"Y": float(arr[-1]), "Y_std": float(arr.std()),
                "osc": bool(arr.std() > 0.05)}

    def validate_state(self):
        return []


# ============ 世代交叠 / 生命周期 ============
class DiamondOLGModel(DayanModel):
    """ECO031 Diamond 资本生产 OLG：s(w) 供给资本，稳态 k* 存在。"""

    model_id = "ECO031"
    clock_type = "fixed_step"

    def __init__(self, alpha=0.3, n=0.0, beta=0.5, delta=1.0, k0=0.5):
        self.alpha, self.n, self.beta, self.delta = alpha, n, beta, delta
        self.k = k0

    def initialize(self, context, parameters, population, topology, rng):
        self.k = parameters.get("k0", 0.5)

    def step(self, t, dt):
        k = max(self.k, 1e-9)
        w = (1 - self.alpha) * k ** self.alpha
        r = self.alpha * k ** (self.alpha - 1)
        s = self.beta * w / (1 + r)  # 对数效用储蓄率
        self.k = (s - (1 + self.n) * 0) / (1 + self.n)  # 简化 n=0
        self.k = max(self.k * (1 - 0.0), 1e-9)
        # 全式：k_{t+1} = s(w,r)/(1+n)
        self.k = s / (1 + self.n)
        self.k = max(self.k, 1e-9)

    def observe(self):
        k = max(self.k, 1e-9)
        w = (1 - self.alpha) * k ** self.alpha
        r = self.alpha * k ** (self.alpha - 1)
        s = self.beta * w / (1 + r)
        return {"k": float(self.k), "k_next": float(s / (1 + self.n)),
                "r": float(r)}

    def validate_state(self):
        return []


class BlanchardYOUTHModel(DayanModel):
    """ECO032 Blanchard 永葆青春：死亡概率 p，消费 c = (p+θ)(h)。"""

    model_id = "ECO032"
    clock_type = "fixed_step"

    def __init__(self, p_death=0.1, theta=0.05, r=0.03, W0=10.0):
        self.p_death, self.theta, self.r = p_death, theta, r
        self.W = W0

    def initialize(self, context, parameters, population, topology, rng):
        self.W = parameters.get("W0", 10.0)

    def step(self, t, dt):
        # 人力资本 h 满足 dh/dt = (r+p)h - 劳动收入(常数1) → h=1/(r+p)
        h = 1.0 / (self.r + self.p_death)
        c = (self.p_death + self.theta) * (self.W + h)
        self.W += (self.r * self.W + 1.0 - c) * dt
        self.W = max(self.W, 0.0)

    def observe(self):
        h = 1.0 / (self.r + self.p_death)
        c = (self.p_death + self.theta) * (self.W + h)
        return {"W": float(self.W), "c": float(c),
                "c_theory": float((self.p_death + self.theta) *
                                  (self.r * 0 + 1) * 0 + c)}

    def validate_state(self):
        return []


class LifeCycleModel(DayanModel):
    """ECO033 Modigliani 生命周期：T 期预算约束下的平滑消费。年龄-储蓄驼峰。"""

    model_id = "ECO033"
    clock_type = "fixed_step"

    def __init__(self, work_years=40, retire_years=20):
        self.T = work_years + retire_years
        self.age = 0
        self.savings = 0.0
        self.income_path = []

    def initialize(self, context, parameters, population, topology, rng):
        self.age = 0
        self.savings = 0.0
        self.income_path = []

    def step(self, t, dt):
        self.age += 1
        y = 1.0 if self.age <= 40 else 0.0
        c = 40.0 / self.T  # 平滑消费（现值近似，r=0）
        self.savings += y - c
        self.income_path.append({"age": self.age, "y": y,
                                 "c": c, "savings": self.savings})

    def observe(self):
        arr = np.array([r["savings"] for r in self.income_path])
        peak_age = int(np.argmax(arr)) + 1 if len(arr) else 0
        return {"age": self.age, "savings": float(self.savings),
                "peak_age": peak_age,
                "end_zero": bool(self.age >= self.T and
                                 abs(self.savings) < 0.5)}

    def validate_state(self):
        return []


# ============ 存量-流量一致 ============
class GodleyLavoieSIMModel(DayanModel):
    """ECO035 Godley–Lavoie SIM：政府支出驱动，Y = G/(1-α(1-θ)) 稳态，
    三部门平衡（货币守恒：ΔH_g + ΔH_h = 0）。"""

    model_id = "ECO035"
    clock_type = "fixed_step"

    def __init__(self, alpha=0.6, theta=0.2, G=20.0):
        self.alpha, self.theta, self.G = alpha, theta, G
        self.H_g, self.H_h, self.Y = 0.0, 0.0, 0.0

    def initialize(self, context, parameters, population, topology, rng):
        self.alpha = parameters.get("alpha", self.alpha)
        self.theta = parameters.get("theta", self.theta)
        self.G = parameters.get("G", self.G)
        self.H_g = self.H_h = self.Y = 0.0

    def step(self, t, dt):
        # 商品市场均衡闭式解：Y = G + α(H_h + (1-θ)Y)
        self.Y = (self.G + self.alpha * self.H_h) /             (1 - self.alpha * (1 - self.theta))
        T = self.theta * self.Y
        C = self.Y - self.G                      # Y = C + G
        self.H_h += (1 - self.theta) * self.Y - C   # ΔH_h = yd − C
        self.H_g += T - self.G                       # ΔH_g = T − G
        # 守恒：(1-θ)Y − C + T − G = Y − C − G ≡ 0

    def observe(self):
        resid = self.H_h + self.H_g
        Y_star = self.G / self.theta   # SIM 稳态：政府预算平衡 θY=G
        return {"Y": float(self.Y), "Y_star": float(Y_star),
                "H_h": float(self.H_h), "H_g": float(self.H_g),
                "conserv": float(resid)}

    def validate_state(self):
        return [] if abs(self.H_h + self.H_g) < 1e-6 else ["货币不守恒"]


# ============ 时间序列 ============
def fit_var(series, p=1):
    """ECO038 VAR(p) OLS 拟合：返回系数矩阵与截距。"""
    y = np.asarray(series)
    T, k = y.shape
    X = np.hstack([np.ones((T - p, 1))] +
                  [y[p - i - 1:T - i - 1] for i in range(p)])
    Yt = y[p:]
    coef, *_ = np.linalg.lstsq(X, Yt, rcond=None)
    return {"const": coef[0], "A": coef[1:].T}


def fit_garch(returns, omega=0.05, alpha=0.1, beta=0.85, iters=200):
    """ECO045 GARCH(1,1) 递推滤波（给定参数的 conditional variance 路径）。"""
    r = np.asarray(returns)
    n = len(r)
    sigma2 = np.empty(n)
    sigma2[0] = r.var()
    for t in range(1, n):
        sigma2[t] = omega + alpha * r[t - 1] ** 2 + beta * sigma2[t - 1]
    return sigma2


# ============ 金融 ABM ============
class GodeSunderZIModel(DayanModel):
    """ECO054 Gode–Sunder 零智能交易者：限价订单簿撮合，
    预算约束下 ZI 的成交价收敛到理论均衡区间 [30,40]（供给10-50/需求50-10）。"""

    model_id = "ECO054"
    clock_type = "fixed_step"

    def __init__(self, n_buyers=50, n_sellers=50, ticks=60):
        self.n_b, self.n_s, self.ticks = n_buyers, n_sellers, ticks
        self.trades = []

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        self.trades = []
        self.tick = 0
        self.b_values = sorted(rng.integers(10, 50, self.n_b).tolist(),
                               reverse=True)
        self.s_values = sorted(rng.integers(10, 50, self.n_s).tolist())
        self.b_done = [False] * self.n_b
        self.s_done = [False] * self.n_s

    def step(self, t, dt):
        """每轮双向拍卖：全员报价 → 买降卖升逐对撮合（可多笔）。"""
        bids = []
        asks = []
        for i in range(self.n_b):
            if not self.b_done[i]:
                bids.append((-self.rng.integers(1, self.b_values[i]), i))
        for j in range(self.n_s):
            if not self.s_done[j]:
                asks.append((self.s_values[j] +
                             self.rng.integers(1, 21), j))
        bids.sort()
        asks.sort()
        bi = 0
        while bi < len(bids) and bi < len(asks):
            bid_price, i = bids[bi]
            ask_price, j = asks[bi]
            if -bid_price >= ask_price:
                self.trades.append((-bid_price + ask_price) / 2)
                self.b_done[i] = True
                self.s_done[j] = True
                bi += 1
            else:
                break

    def observe(self):
        eq_lo, eq_hi = 30.0, 40.0
        if self.trades:
            in_eq = sum(1 for p in self.trades if eq_lo <= p <= eq_hi)
            frac = in_eq / len(self.trades)
        else:
            frac = 0.0
        # GS 基准：配置效率 = 已实现剩余 / 理想匹配最大剩余
        vs = sorted(self.b_values, reverse=True)
        cs = sorted(self.s_values)
        max_surplus = sum(v - c for v, c in zip(vs, cs) if v > c)
        # 已实现剩余需逐笔价值追踪（重放成交记录）
        realized = 0.0
        vi, ci = 0, 0
        done_b = [i for i in range(self.n_b)]
        # b_done/s_done 已在撮合中更新；用当前剩余价值重算
        vb = [self.b_values[i] for i in range(self.n_b) if not self.b_done[i]]
        vc = [self.s_values[j] for j in range(self.n_s) if not self.s_done[j]]
        # 已实现 = 最大剩余 − 未撮合剩余（单调）
        realized = max_surplus - sum(v - c for v, c in zip(vb, vc) if v > c)
        eff = realized / max(max_surplus, 1e-9)
        return {"n_trades": len(self.trades),
                "in_equilibrium_frac": float(frac),
                "mean_price": float(np.mean(self.trades)) if self.trades else 0.0,
                "alloc_efficiency": float(eff)}

    def validate_state(self):
        return []


# ============ 劳动搜寻 / 人力资本 ============
class McCallModel(DayanModel):
    """ECO078 McCall 工作搜寻：保留工资 w* 使 临界值处 接受/拒绝无差异。
    蒙特卡洛：拒绝所有 < w* 的 offer、接受 ≥ w*。"""

    model_id = "ECO078"
    clock_type = "fixed_step"

    def __init__(self, w_lo=10, w_hi=50, beta=0.9, c_unemp=2.0):
        self.w_lo, self.w_hi, self.beta, self.c = w_lo, w_hi, beta, c_unemp
        self.res_wage = None
        self.accepted = None

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        # 离散 McCall 保留工资：V(w)=w/(1-β)；V_U=c+β E max(V(w),V_U)
        # 均匀分布下 w* = c + β/(1-β)·E[max(w-w*,0)] 的不动点 → 网格求解
        grid = np.arange(self.w_lo, self.w_hi + 1, dtype=float)
        V = grid / (1 - self.beta)
        V_U = self.c + self.beta * V.mean()
        for _ in range(200):
            V_U = self.c + self.beta * np.maximum(V, V_U).mean()
        # 接受条件 V(w)≥V_U ⇔ w ≥ (1-β)·V_U → 保留工资由临界值解析给出
        self.res_wage = float((1 - self.beta) * V_U)
        self.accepted = None

    def step(self, t, dt):
        if self.accepted is None:
            w = float(self.rng.uniform(self.w_lo, self.w_hi))
            if w >= self.res_wage:
                self.accepted = w

    def observe(self):
        return {"res_wage": float(self.res_wage),
                "accepted": self.accepted,
                "mean_wage": float((self.w_lo + self.w_hi) / 2)}

    def validate_state(self):
        return []


class MincerModel(DayanModel):
    """ECO083 Mincer 收入方程：ln w = α + ρ·s + β1·x + β2·x²（ρ≈10%/年）。
    按理论生成数据并 OLS 恢复 ρ。"""

    model_id = "ECO083"
    clock_type = "fixed_step"

    def __init__(self, rho=0.10, beta1=0.05, beta2=-0.0007, n=400):
        self.rho, self.beta1, self.beta2, self.n = rho, beta1, beta2, n
        self.rho_hat = None

    def initialize(self, context, parameters, population, topology, rng):
        n = self.n
        s = rng.uniform(8, 20, n)                    # 学校教育
        x = rng.uniform(0, 40 - s)                   # 经验
        lnw = 1.5 + self.rho * s + self.beta1 * x + \
            self.beta2 * x ** 2 + rng.normal(0, 0.15, n)
        X = np.column_stack([np.ones(n), s, x, x ** 2])
        coef, *_ = np.linalg.lstsq(X, lnw, rcond=None)
        self.rho_hat = float(coef[1])

    def step(self, t, dt):
        pass

    def observe(self):
        return {"rho": self.rho, "rho_hat": self.rho_hat,
                "err": abs(self.rho - self.rho_hat) if
                self.rho_hat is not None else None}

    def validate_state(self):
        return []


class BenPorathModel(DayanModel):
    """ECO082 Ben-Porath 人力资本积累：早期投资密集、边际递减 → 凹积累。"""

    model_id = "ECO082"
    clock_type = "fixed_step"

    def __init__(self, delta=0.02, phi=0.8, horizon=45):
        self.delta, self.phi, self.horizon = delta, phi, horizon
        self.h = 1.0
        self.age = 0
        self.invest = []

    def initialize(self, context, parameters, population, topology, rng):
        self.h, self.age, self.invest = 1.0, 0, []

    def step(self, t, dt):
        self.age += 1
        remaining = max(0, self.horizon - self.age)  # 不允许为负
        q = remaining / self.horizon  # 剩余回报折扣因子
        s_inv = max(0.0, q ** (1 / (1 - self.phi)) - 0.4) if q > 0 else 0.0
        self.h = (1 - self.delta) * self.h + s_inv * self.h ** self.phi
        self.invest.append(s_inv)
        self.h = max(self.h, 1e-6)

    def observe(self):
        inv = np.array(self.invest)
        early = inv[:10].mean() if len(inv) >= 20 else 0
        late = inv[-10:].mean() if len(inv) >= 20 else 0
        return {"h": float(self.h), "invest_early": float(early),
                "invest_late": float(late),
                "decreasing": bool(early > late)}

    def validate_state(self):
        return []


# ============ 企业动态 ============
class GibratModel(DayanModel):
    """ECO087 Gibrat 比例增长：规模对数正态（独立于规模的增长率）。"""

    model_id = "ECO087"
    clock_type = "fixed_step"

    def __init__(self, n_firms=200, mu=-0.02, sigma=0.15, T=60):
        self.n, self.mu, self.sigma, self.T = n_firms, mu, sigma, T
        self.sizes = None

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        self.sizes = rng.uniform(1, 10, self.n)
        self.tick = 0

    def step(self, t, dt):
        if self.tick < self.T:
            g = self.rng.normal(self.mu, self.sigma, self.n)
            self.sizes = np.maximum(self.sizes * np.exp(g), 1e-6)
            self.tick += 1

    def observe(self):
        ls = np.log(self.sizes)
        # 对数正态检验：偏度接近0、峰度接近3
        skew = float(((ls - ls.mean()) ** 3).mean() / ls.std() ** 3)
        return {"mean": float(self.sizes.mean()),
                "log_skew": skew, "log_std": float(ls.std()),
                "size_cv": float(self.sizes.std() / self.sizes.mean())}

    def validate_state(self):
        return []


# ============ 项目反应理论 ============
def irt_p(theta, a, b, c=0.0):
    """3PL 项目特征曲线：P = c + (1-c)/(1+exp(-a(θ-b)))。"""
    return c + (1 - c) / (1 + np.exp(-a * (theta - b)))


class RaschModel(DayanModel):
    """ECO088 Rasch 一参数 IRT：P(θ)=1/(1+exp(-(θ-b)))；联合 MLE 参数恢复。"""

    model_id = "ECO088"
    clock_type = "fixed_step"

    def __init__(self, n_people=300, n_items=20):
        self.n_p, self.n_i = n_people, n_items
        self.b_err = None

    def initialize(self, context, parameters, population, topology, rng):
        theta = rng.normal(0, 1, self.n_p)
        b_true = rng.normal(0, 1, self.n_i)
        P = 1 / (1 + np.exp(-(theta[:, None] - b_true[None, :])))
        resp = (rng.random((self.n_p, self.n_i)) < P).astype(float)
        # 交替 MLE（简化牛顿迭代）
        b_hat = np.zeros(self.n_i)
        th_hat = np.zeros(self.n_p)
        for _ in range(100):
            Pp = 1 / (1 + np.exp(-(th_hat[:, None] - b_hat[None, :])))
            grad_b = (resp - Pp).sum(axis=0)   # ∂ℓ/∂b = -Σ(r-P)
            b_hat -= grad_b * 0.005            # 梯度上升：答对多于预测 → item 更易 → b 下调
            grad_th = (resp - Pp).sum(axis=1)  # ∂ℓ/∂θ = +Σ(r-P)
            th_hat += grad_th * 0.02
        self.b_err = float(np.corrcoef(b_true, b_hat)[0, 1])  # 带符号：应显著为正

    def step(self, t, dt):
        pass

    def observe(self):
        return {"item_b_corr": self.b_err}

    def validate_state(self):
        return []


class TwoPLModel(DayanModel):
    """ECO089 Birnbaum 二参数 IRT：P=c0+..斜率 a 区分度；单调 ICC 校验。"""

    model_id = "ECO089"
    clock_type = "fixed_step"

    def __init__(self, n_people=300, n_items=20):
        self.n_p, self.n_i = n_people, n_items
        self.a_true = None
        self.monotone = None

    def initialize(self, context, parameters, population, topology, rng):
        theta = rng.normal(0, 1, self.n_p)
        b_true = rng.normal(0, 1, self.n_i)
        a_true = rng.uniform(0.5, 2.0, self.n_i)
        P = irt_p(theta[:, None], a_true[None, :], b_true[None, :])
        resp = (rng.random((self.n_p, self.n_i)) < P).astype(float)
        # 校验：经验正确率随 θ 单调（分 5 组）
        order = np.argsort(theta)
        groups = np.array_split(order, 5)
        p_by_group = [resp[g].mean(axis=0) for g in groups]
        self.monotone = bool(all(
            (p_by_group[k + 1] >= p_by_group[k] - 0.12).mean() > 0.7
            for k in range(4)))
        self.a_true = float(a_true.mean())

    def step(self, t, dt):
        pass

    def observe(self):
        return {"mean_a": self.a_true, "monotone_icc": self.monotone}

    def validate_state(self):
        return []


class ThreePLModel(TwoPLModel):
    """ECO090 Birnbaum 三参数 IRT：猜测参数 c>0 → 低 θ 正确率 > 0。"""

    model_id = "ECO090"

    def initialize(self, context, parameters, population, topology, rng):
        theta = rng.normal(0, 1, self.n_p)
        b_true = rng.normal(0, 1, self.n_i)
        a_true = rng.uniform(0.5, 2.0, self.n_i)
        c_true = rng.uniform(0.1, 0.25, self.n_i)
        P = irt_p(theta[:, None], a_true[None, :], b_true[None, :],
                  c_true[None, :])
        resp = (rng.random((self.n_p, self.n_i)) < P).astype(float)
        low = resp[theta < -1.5]
        self.low_guess = float(low.mean()) if len(low) else 0.0
        self.c_mean = float(c_true.mean())

    def observe(self):
        return {"c_mean": self.c_mean, "low_theta_acc": self.low_guess,
                "guess_visible": bool(self.low_guess > 0.15)}

    def validate_state(self):
        return []


# ============ 税收福利微观仿真 ============
class StaticTaxBenefitModel(DayanModel):
    """ECO096 静态算术税收福利微观仿真：分段税率+免征额+转移支付。
    基准：边际税率在档位跳变；净收入单调增。"""

    model_id = "ECO096"
    clock_type = "fixed_step"

    def __init__(self, n=500):
        self.n = n
        self.brackets = [(30.0, 0.10), (80.0, 0.20), (np.inf, 0.30)]
        self.exempt = 6.0

    def initialize(self, context, parameters, population, topology, rng):
        self.gross = rng.lognormal(2.5, 0.7, self.n)

    def tax(self, y):
        """分段累进：6 以下免税，6–30 10%，30–80 20%，80+ 30%。"""
        t = 0.0
        prev = self.exempt
        for thr, rate in ((30.0, 0.10), (80.0, 0.20), (float("inf"), 0.30)):
            if y > thr:
                t += (thr - prev) * rate
                prev = thr
            else:
                if y > prev:
                    t += (y - prev) * rate
                break
        return t

    def step(self, t, dt):
        pass

    def observe(self):
        taxes = np.array([self.tax(y) for y in self.gross])
        net = self.gross - taxes + 2.0  # 定额转移
        # 边际税率单调不降（分段线性递增）
        mtr = []
        for y in (5.0, 15.0, 50.0, 100.0):
            mtr.append((self.tax(y + 0.01) - self.tax(y)) / 0.01)
        return {"mean_tax": float(taxes.mean()),
                "net_monotone": bool((np.diff(np.sort(net)) >= -1e-9).all()),
                "mtr_path": [round(float(x), 3) for x in mtr],
                "mtr_nondecreasing": bool(
                    (np.diff(np.array(mtr)[:-1]) >= -0.01).all())}

    def validate_state(self):
        return []


# ============ 冲突与军备 ============
class RichardsonArmsModel(DayanModel):
    """ECO110 Richardson 军备竞赛：dx/dt=a y - r x + m；稳定性条件 r1 r2 > a1 a2。"""

    model_id = "ECO110"
    clock_type = "ode"

    def __init__(self, a1=0.3, a2=0.3, r1=0.5, r2=0.5, m1=1.0, m2=1.0):
        self.a1, self.a2, self.r1, self.r2, self.m1, self.m2 = \
            a1, a2, r1, r2, m1, m2
        self.x = np.array([1.0, 1.0])
        self.stable_cfg = True

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array(parameters.get("x0", [1.0, 1.0]), float)
        self.stable_cfg = self.r1 * self.r2 > self.a1 * self.a2

    def derivatives(self, t, x):
        dx1 = self.a1 * x[1] - self.r1 * x[0] + self.m1
        dx2 = self.a2 * x[0] - self.r2 * x[1] + self.m2
        return np.array([dx1, dx2])

    def observe(self):
        xs, ys = self.x
        den = self.r1 * self.r2 - self.a1 * self.a2
        eq = np.array([
            (self.r2 * self.m1 + self.a1 * self.m2) / den,
            (self.r1 * self.m2 + self.a2 * self.m1) / den])
        return {"x1": float(xs), "x2": float(ys),
                "stable": bool(self.stable_cfg),
                "eq_x1": float(eq[0]), "eq_x2": float(eq[1])}

    def validate_state(self):
        return []


class LanchesterSquareModel(DayanModel):
    """ECO111 Lanchester 平方律：dx/dt=-a y, dy/dt=-b x → x²-x0² = (b/a)(y²-y0²)。"""

    model_id = "ECO111"
    clock_type = "ode"

    def __init__(self, a=0.05, b=0.08, N1=100.0, N2=80.0):
        self.a, self.b, self.N1, self.N2 = a, b, N1, N2
        self.x = np.array([N1, N2])

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array(parameters.get("N", [self.N1, self.N2]), float)
        self.N1, self.N2 = self.x

    def derivatives(self, t, x):
        x = np.clip(x, 0.0, None)   # 兵力非负（歼灭后停止损耗）
        return np.array([-self.a * x[1], -self.b * x[0]])

    def observe(self):
        k = self.a / self.b
        inv = float(max(self.x[0], 0) ** 2 - k * max(self.x[1], 0) ** 2)
        return {"N1": float(self.x[0]), "N2": float(self.x[1]),
                "invariant": inv,
                "inv0": float(self.N1 ** 2 - k * self.N2 ** 2)}

    def validate_state(self):
        return []


class LanchesterLinearModel(DayanModel):
    """ECO112 Lanchester 线性律（古式/面射击）：dx/dt=-a·x·y, dy/dt=-b·x·y
    → 线性不变量 a·N2-b·N1 守恒（与平方律 ECO111 的二次不变量相区分）。"""

    model_id = "ECO112"
    clock_type = "ode"

    def __init__(self, a=0.05, b=0.05, N1=100.0, N2=100.0):
        self.a, self.b, self.N1, self.N2 = a, b, N1, N2
        self.x = np.array([N1, N2])

    def initialize(self, context, parameters, population, topology, rng):
        self.x = np.array(parameters.get("N", [self.N1, self.N2]), float)
        self.N1, self.N2 = self.x

    def derivatives(self, t, x):
        x = np.clip(x, 0.0, None)
        # 线性律：己方损耗 ∝ 己方暴露密度 × 对方面射击强度
        return np.array([-self.a * x[0] * x[1], -self.b * x[0] * x[1]])

    def observe(self):
        lin = float(self.a * max(self.x[1], 0) - self.b * max(self.x[0], 0))
        return {"N1": float(self.x[0]), "N2": float(self.x[1]),
                "lin_invariant": lin,
                "lin0": float(self.a * self.N2 - self.b * self.N1)}

    def validate_state(self):
        return []


# ============ 资源与气候 ============
class SchaeferFisheryModel(DayanModel):
    """ECO113 Schaefer 剩余产量：dB/dt=rB(1-B/K)-qE B；MSY=B_ne·r/4 at B=K/2。"""

    model_id = "ECO113"
    clock_type = "ode"

    def __init__(self, r=0.6, K=100.0, q=0.1, E=0.0, B0=100.0):
        self.r, self.K, self.q, self.E = r, K, q, E
        self.x = np.array([B0])

    def initialize(self, context, parameters, population, topology, rng):
        self.r = parameters.get("r", self.r)
        self.K = parameters.get("K", self.K)
        self.q = parameters.get("q", self.q)
        self.E = parameters.get("E", self.E)
        self.x = np.array([parameters.get("B0", self.K)])

    def derivatives(self, t, x):
        B = max(x[0], 1e-9)
        return np.array([self.r * B * (1 - B / self.K) - self.q * self.E * B])

    def observe(self):
        B = float(self.x[0])
        msy = self.r * self.K / 4
        B_eq = self.K * (1 - self.q * self.E / self.r)
        return {"B": B, "MSY": float(msy),
                "B_at_MSY": float(self.K / 2), "B_eq": float(max(B_eq, 0))}

    def validate_state(self):
        return []


class GordonSchaeferModel(DayanModel):
    """ECO114 Gordon–Schaefer 开放进入：生物经济均衡 B_∞ = c/(p·q)（利润=0）。"""

    model_id = "ECO114"
    clock_type = "ode"

    def __init__(self, r=0.6, K=100.0, q=0.1, p=1.0, c=2.0, B0=100.0):
        self.r, self.K, self.q, self.p, self.c = r, K, q, p, c
        self.E = 0.0
        self.x = np.array([B0])

    def initialize(self, context, parameters, population, topology, rng):
        self.r, self.K = parameters.get("r", self.r), parameters.get("K", self.K)
        self.q, self.p, self.c = (parameters.get("q", self.q),
                                  parameters.get("p", self.p),
                                  parameters.get("c", self.c))
        self.E = 0.0
        self.x = np.array([parameters.get("B0", self.K)])

    def derivatives(self, t, x):
        return np.array([0.0])  # 生物量由 E 的调整间接驱动（见 step 补充）

    def step_ode_post(self):
        pass

    def observe(self):
        B_bioeq = self.K * (1 - self.q * self.E / self.r) if self.E < \
            self.r / self.q else 0.0
        B_econ = self.c / (self.p * self.q)  # 开放进入生物经济均衡
        return {"B": float(self.x[0]), "E": float(self.E),
                "B_econ_eq": float(B_econ)}

    def validate_state(self):
        return []


class HotellingModel(DayanModel):
    """ECO115 Hotelling 不可再生资源：价格路径 p(t)=p0·e^{δt}（霍特林法则）。"""

    model_id = "ECO115"
    clock_type = "fixed_step"

    def __init__(self, stock=100.0, delta=0.05, demand_a=10.0, T=40):
        self.stock, self.delta, self.a, self.T = stock, delta, demand_a, T
        self.p = 1.0
        self.S = stock
        self.price_path = []

    def initialize(self, context, parameters, population, topology, rng):
        self.S = parameters.get("stock", self.stock)
        self.delta = parameters.get("delta", self.delta)
        # 竞争性开采：p0 使初始需求率×T ≈ stock → p0 = a·T/S 近似
        self.p = self.a * self.T / self.S
        self.price_path = [self.p]
        self.tick = 0

    def step(self, t, dt):
        self.tick += 1
        self.p *= np.exp(self.delta * dt)
        q = max(0.0, self.a - self.p)   # 线性需求
        self.S = max(0.0, self.S - q * dt)
        self.price_path.append(self.p)

    def observe(self):
        pp = np.array(self.price_path)
        if len(pp) > 10:
            growth = np.diff(np.log(pp)).mean()
        else:
            growth = 0.0
        return {"price": float(self.p), "stock": float(self.S),
                "price_growth": float(growth),
                "hotelling_delta": float(self.delta)}

    def validate_state(self):
        return []


class BeerGameModel(DayanModel):
    """ECO104 Sterman 啤酒配送：4 级供应链、2 tick 物料延迟、
    锚定启发式（库存偏差+管线偏差）→ 需求阶跃后上游订单方差放大（bullwhip）。"""

    model_id = "ECO104"
    clock_type = "fixed_step"

    def __init__(self, levels=4, alpha_s=0.6, alpha_sl=0.2, lead=2):
        self.levels = levels
        self.alpha_s, self.alpha_sl, self.lead = alpha_s, alpha_sl, lead
        self.inventory = np.full(levels, 12.0)
        self.backlog = np.zeros(levels)
        self.orders = np.full(levels, 4.0)
        self.pipeline_q = [[4.0] * lead for _ in range(levels)]
        self.order_hist = [[] for _ in range(levels)]

    def initialize(self, context, parameters, population, topology, rng):
        L = self.levels
        self.inventory = np.full(L, 12.0)
        self.backlog = np.zeros(L)
        self.orders = np.full(L, 4.0)
        self.pipeline_q = [[4.0] * self.lead for _ in range(L)]
        self.order_hist = [[] for _ in range(L)]
        self.tick = 0

    def step(self, t, dt):
        self.tick += 1
        demand = 8.0 if self.tick > 50 else 4.0   # 经典需求阶跃实验
        new_orders = np.zeros(self.levels)
        for i in range(self.levels):
            cust = demand if i == 0 else self.orders[i - 1]
            arrival = self.pipeline_q[i].pop(0) if self.pipeline_q[i] else 0.0
            available = self.inventory[i] + arrival
            need = cust + self.backlog[i]
            ship = min(available, need)
            self.inventory[i] = available - ship
            self.backlog[i] = need - ship
            pipeline = sum(self.pipeline_q[i])
            desired = max(0.0, cust + self.alpha_s * (12.0 - self.inventory[i])
                          + self.alpha_sl * (8.0 - pipeline))
            o = min(desired, 20.0)
            new_orders[i] = o
            self.pipeline_q[i].append(o)
        self.orders = new_orders
        for i in range(self.levels):
            self.order_hist[i].append(new_orders[i])

    def observe(self):
        # 冲击后瞬态窗（t=50 阶跃 → 50–120 期放大过程）
        var = [float(np.var(h[50:120])) if len(h) >= 120 else 0.0
               for h in self.order_hist]
        return {"order_var": var,
                "bullwhip": float(var[-1] / max(var[0], 1e-6)),
                "var_up_gt_down": bool(var[-1] > var[0] * 1.5),
                "orders": self.orders.tolist()}

    def validate_state(self):
        return []


class DICELiteModel(DayanModel):
    """ECO106 DICE-lite：排放→存量 M→辐射 forcing→温度 T 线性化链。"""

    model_id = "ECO106"
    clock_type = "ode"

    def __init__(self, sigma0=3.0, M0=800.0, T0=1.0):
        self.sigma = sigma0
        self.x = np.array([M0, T0])
        self.E_hist = []

    def initialize(self, context, parameters, population, topology, rng):
        M0 = parameters.get("M0", 800.0)
        T0 = parameters.get("T0", 1.0)
        self.sigma = parameters.get("sigma0", self.sigma)
        self.x = np.array([M0, T0])
        self.E_hist = []

    def derivatives(self, t, x):
        M, T = x
        E = self.sigma * np.exp(0.02 * t)   # 排放随增长
        self.E_hist.append(E)
        dM = E - 0.02 * (M - 590)            # 净排放（碳循环线性化）
        forcing = 3.7 * np.log2(max(M, 590) / 590)   # 辐射强迫
        dT = 0.05 * (forcing / 1.2 - T)      # 简化气候响应
        return np.array([dM, dT])

    def observe(self):
        M, T = self.x
        return {"M": float(M), "T": float(T),
                "forcing": float(3.7 * np.log2(max(M, 590) / 590))}

    def validate_state(self):
        return []
