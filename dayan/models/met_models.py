"""DAYAN 方法论工具家族（目录 MET001–MET064）。

积分器：Euler / RK4 / RK45(Dormand–Prince) / Radau(隐式Newton) /
       BDF(隐式多步) / 刚性切换
随机积分：Euler–Maruyama / Milstein / SSA(通用) / 下一反应 / τ-leaping / 稀疏化
蒙特卡洛：plain / importance / stratified / LHS / Sobol(Halton) /
         CRN / 对偶变量
实验设计：全因子 / 部分因子 / 中心复合 CCD / Box–Behnken
MCMC 与 ABC：Metropolis–Hastings / Gibbs / HMC / ABC 拒绝 / SMC-ABC
估计：模拟矩 SMM / 间接推断 / KOH 贝叶斯校准(GP) / CMA-ES /
     差分演化 / GP 贝叶斯优化 / NSGA-II
滤波与同化：Kalman / EKF / EnKF / Bootstrap PF / APF / PMH / 4D-Var
敏感性：局部导数 / Morris / Sobol 方差分解 / FAST / PAWN / Shapley
不确定性：Bootstrap / 后验预测检查 / 校准诊断
人口合成：IPF / IPU / 加权记录抽样 / 准随机无放回 / 组合优化合成
"""
from __future__ import annotations

import numpy as np
from scipy.stats import qmc


# ============ 常微分积分器（收敛阶基准用）============
def euler(f, y0, T, n):
    """MET001 显式 Euler：局部误差 O(dt²) 全局 O(dt)。"""
    y = np.asarray(y0, float).copy()
    dt = T / n
    for _ in range(n):
        y = y + dt * np.asarray(f(0.0, y))
    return y


def rk4(f, y0, T, n):
    """MET002 经典 RK4：全局 O(dt⁴)。"""
    y = np.asarray(y0, float).copy()
    dt = T / n
    for i in range(n):
        t = i * dt
        k1 = np.asarray(f(t, y))
        k2 = np.asarray(f(t + dt / 2, y + dt / 2 * k1))
        k3 = np.asarray(f(t + dt / 2, y + dt / 2 * k2))
        k4 = np.asarray(f(t + dt, y + dt * k3))
        y = y + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
    return y


def rk45_dormand_prince(f, y0, T, tol=1e-6, h0=0.1):
    """MET003 Dormand–Prince 自适应（嵌入 5(4)，步长控制）。"""
    y = np.asarray(y0, float).copy()
    t = 0.0
    h = h0
    while t < T - 1e-12:
        h = min(h, T - t)
        k1 = np.asarray(f(t, y))
        k2 = np.asarray(f(t + h / 5, y + h * k1 / 5))
        k3 = np.asarray(f(t + 3 * h / 10, y + h * (3 * k1 / 40 + 9 * k2 / 40)))
        k4 = np.asarray(f(t + 4 * h / 5, y + h * (44 * k1 / 45 - 56 * k2 / 15
                                                  + 32 * k3 / 9)))
        k5 = np.asarray(f(t + 8 * h / 9, y + h * (19372 * k1 / 6561
                                                  - 25360 * k2 / 2187
                                                  + 64448 * k3 / 6561
                                                  - 212 * k4 / 729)))
        k6 = np.asarray(f(t + h, y + h * (9017 * k1 / 3168 - 355 * k2 / 33
                                          + 46732 * k3 / 5247 + 49 * k4 / 176
                                          - 5103 * k5 / 18656)))
        k7 = np.asarray(f(t + h, y + h * (35 * k1 / 384 + 500 * k3 / 1113
                                          + 125 * k4 / 192 - 2187 * k5 / 6784
                                          + 11 * k6 / 84)))
        y5 = y + h * (35 * k1 / 384 + 500 * k3 / 1113 + 125 * k4 / 192
                      - 2187 * k5 / 6784 + 11 * k6 / 84)
        y4 = y + h * (5179 * k1 / 57600 + 7571 * k3 / 16695 + 393 * k4 / 640
                      - 92097 * k5 / 339200 + 187 * k6 / 2100 + k7 / 40)
        err = np.max(np.abs(y5 - y4)) + 1e-12
        if err < tol:
            y = y5
            t += h
        h *= min(5.0, max(0.2, 0.9 * (tol / err) ** 0.2))
    return y


def radau_implicit(f, y0, T, n, jac_eps=1e-6):
    """MET004 单阶段全隐式（Radau 简化型，L-稳定，一阶）：刚性问题稳定。"""
    y = np.asarray(y0, float).copy()
    dt = T / n
    c = 1.0
    b = 1.0
    for _ in range(n):
        g = y.copy()  # 牛顿迭代初值：阶段值
        for _ in range(8):
            F = g - y - dt * c * np.asarray(f(0, g))
            if np.max(np.abs(F)) < 1e-10:
                break
            n_dim = len(y)
            J = np.empty((n_dim, n_dim))
            for j in range(n_dim):
                gp = g.copy()
                gp[j] += jac_eps
                J[:, j] = (np.asarray(f(0, gp)) - np.asarray(f(0, g))) / jac_eps
            A = np.eye(n_dim) - dt * c * J
            g = g - np.linalg.solve(A, F)
        y = y + dt * b * np.asarray(f(0, g))
    return y


def bdf1_implicit(f, y0, T, n, jac_eps=1e-6):
    """MET005 后向微分公式（隐式 Euler = BDF1）：Newton 迭代。"""
    y = np.asarray(y0, float).copy()
    dt = T / n
    for _ in range(n):
        g = y.copy()
        for _ in range(10):
            F = g - y - dt * np.asarray(f(0, g))
            if np.max(np.abs(F)) < 1e-10:
                break
            n_dim = len(y)
            J = np.empty((n_dim, n_dim))
            for j in range(n_dim):
                gp = g.copy()
                gp[j] += jac_eps
                J[:, j] = (np.asarray(f(0, gp)) - np.asarray(f(0, g))) / jac_eps
            g = g - np.linalg.solve(np.eye(n_dim) - dt * J, F)
        y = g
    return y


def stiff_switching(f, y0, T, n, stiff_bound=2.0):
    """MET006 自动刚性切换：估计 |λ|max·dt 超阈用隐式，否则显式。"""
    y = np.asarray(y0, float).copy()
    dt = T / n
    eps = 1e-6
    for _ in range(n):
        f0 = np.atleast_1d(np.asarray(f(0.0, y), float))
        J = np.empty((len(y), len(y)))
        for j in range(len(y)):
            yp = y.copy()
            yp[j] += eps
            J[:, j] = (np.atleast_1d(np.asarray(f(0.0, yp), float)) - f0) / eps
        lam = float(np.max(np.abs(np.linalg.eigvals(J))))
        if lam * dt > stiff_bound:
            y = bdf1_implicit(f, y, dt, 1)
        else:
            y = rk4(f, y, dt, 1)
    return y


# ============ 随机积分与化学 Master 方程 ============
def euler_maruyama(drift, diff, x0, T, n, rng):
    """MET007 Euler–Maruyama：强收敛 O(√dt)。"""
    x = np.asarray(x0, float).copy()
    dt = T / n
    sq = np.sqrt(dt)
    for _ in range(n):
        dW = rng.normal(0, 1, size=np.shape(x)) * sq
        x = x + np.asarray(drift(0, x)) * dt + np.asarray(diff(0, x)) * dW
    return x


def milstein(drift, diff_prime, diff, x0, T, n, rng):
    """MET008 Milstein：强收敛 O(dt)。"""
    x = np.asarray(x0, float).copy()
    dt = T / n
    sq = np.sqrt(dt)
    for _ in range(n):
        dW = rng.normal(0, 1, size=np.shape(x)) * sq
        x = (x + np.asarray(drift(0, x)) * dt
             + np.asarray(diff(0, x)) * dW
             + 0.5 * np.asarray(diff_prime(0, x)) * np.asarray(diff(0, x))
             * (dW ** 2 - dt))
    return x


def gillespie_ssa(intensities, apply_rule, n0, T, rng):
    """MET009 Gillespie 直接法（通用 n 通道）。返回 (末态, 事件数)。"""
    n = n0
    t = 0.0
    events = 0
    while t < T:
        a = np.asarray(intensities(n), float)
        total = a.sum()
        if total <= 0:
            break
        tau = rng.exponential(1 / total)
        if t + tau > T:
            break
        which = int(rng.choice(len(a), p=a / total))
        n = apply_rule(n, which)
        t += tau
        events += 1
    return n, events


def next_reaction_method(intensities, apply_rule, n0, T, rng):
    """MET010 Gibson–Bruck 下一反应：各通道预生成绝对时间，取最小。"""
    n = n0
    t = 0.0
    events = 0
    times = [rng.exponential(1 / max(a, 1e-12)) if a > 0 else np.inf
             for a in np.asarray(intensities(n), float)]
    while True:
        i = int(np.argmin(times))
        if times[i] > T:
            break
        t = times[i]
        n = apply_rule(n, i)
        events += 1
        a = np.asarray(intensities(n), float)
        times = [t + rng.exponential(1 / max(ai, 1e-12)) if ai > 0 else np.inf
                 for ai in a]
    return n, events


def tau_leaping(intensities, apply_rule, n0, T, tau, rng):
    """MET011 泊松 τ-leaping：每 τ 以 Poisson(a·τ) 通道计数推进。"""
    n = n0
    t = 0.0
    while t < T:
        a = np.asarray(intensities(n), float)
        k = rng.poisson(np.maximum(a * tau, 0))
        for ch, kk in enumerate(k):
            for _ in range(int(kk)):
                n = apply_rule(n, ch)
        t += tau
    return n


def thinning_nhpp(lam_t, T, lam_max, rng):
    """MET012 Lewis–Shedler 稀疏化：均匀包络采样+接受。返回事件时刻。"""
    events = []
    t = 0.0
    while t < T:
        t += rng.exponential(1 / lam_max)
        if t > T:
            break
        if rng.random() * lam_max < lam_t(t):
            events.append(t)
    return events


# ============ 蒙特卡洛采样 ============
def mc_plain(f, rng, n=20000):
    """MET013 简单蒙特卡洛：∫₀¹f。"""
    x = rng.random(n)
    vals = f(x)
    return float(vals.mean()), float(vals.std() / np.sqrt(n))


def mc_importance(f_target, g_pdf, g_sampler, rng, n=20000):
    """MET014 重要性抽样：E_p[f] = E_g[f·p/g]。"""
    x = g_sampler(n, rng)
    w = f_target(x) * np.where(g_pdf(x) > 0, 1 / np.maximum(g_pdf(x), 1e-12), 0)
    return float(w.mean()), float(w.std() / np.sqrt(n))


def mc_stratified(f, m=10, n_per=2000, rng=None):
    """MET015 分层抽样：每层均匀采样，方差 ≤ plain。"""
    rng = rng or np.random.default_rng(0)
    total = 0.0
    var = 0.0
    for i in range(m):
        x = (i + rng.random(n_per)) / m
        v = f(x)
        total += v.mean() / m
        var += (v.var() / n_per) / m ** 2
    return float(total), float(np.sqrt(var))


def lhs(f, n=4000, dim=1, rng=None):
    """MET016 拉丁超立方：分层置换，覆盖性优于 plain。"""
    rng = rng or np.random.default_rng(0)
    samp = qmc.LatinHypercube(d=dim, seed=rng.integers(1 << 30)).random(n)
    return float(f(samp[:, 0]).mean())


def halton_points(n, dim=1):
    """MET018 Halton 准随机点（van der Corput 逆基）。"""
    eng = qmc.Halton(d=dim, scramble=False)
    return eng.random(n)


def mc_halton(f, n=4096):
    """MET017 Sobol/Halton 准蒙特卡洛（低差异序列）。"""
    pts = halton_points(n, 1)
    return float(f(pts[:, 0]).mean())


def mc_sobol(f, n=4096, dim=1):
    """MET017b Sobol 序列。"""
    eng = qmc.Sobol(d=dim, scramble=True)
    pts = eng.random(n)
    return float(f(pts[:, 0]).mean())


def mc_crn(f1, f2, n=8000, rng=None):
    """MET019 共同随机数：配对差分降方差。返回差估计与朴素差。"""
    rng = rng or np.random.default_rng(0)
    x = rng.random(n)
    d = f2(x) - f1(x)
    # 朴素：独立采样
    x1 = rng.random(n)
    x2 = rng.random(n)
    naive = f2(x2).mean() - f1(x1).mean()
    return float(d.mean()), float(abs(naive))


def mc_antithetic(f, n=8000, rng=None):
    """MET020 对偶变量：f(u)+f(1-u) 平均降方差。"""
    rng = rng or np.random.default_rng(0)
    u = rng.random(n // 2)
    vals = (f(u) + f(1 - u)) / 2
    return float(vals.mean())


# ============ 实验设计 ============
def doe_full_factorial(levels_per_factor, f):
    """MET021 全因子：所有水平组合。"""
    grids = np.meshgrid(*[np.linspace(0, 1, k) for k in levels_per_factor])
    pts = np.stack([g.ravel() for g in grids], axis=1)
    return pts, np.array([f(p) for p in pts])


def doe_fractional(f, n_runs=8, k=4):
    """MET022 部分因子：2^(k-分辨率) 的 L8 正交表近似（Hadamard 行）。"""
    H = np.array([[1 if bin(i & j).count("1") % 2 == 0 else -1
                   for j in range(k)] for i in range(n_runs)], float)
    X = (H + 1) / 2
    return X, np.array([f(row) for row in X])


def doe_ccd(f, k=3):
    """MET023 中心复合设计：角点+轴点+中心。"""
    corners = np.array(list(__import__("itertools").product(
        *[[0, 1]] * k)), float)
    center = np.full((1, k), 0.5)
    axial = []
    for j in range(k):
        p = np.full(k, 0.5)
        p[j] = 0.0
        axial.append(p.copy())
        p[j] = 1.0
        axial.append(p.copy())
    pts = np.vstack([corners, axial, center])
    return pts, np.array([f(p) for p in pts])


def doe_box_behnken(f, k=3):
    """MET024 Box–Behnken：边中点设计（k=3 → 12 点+中心）。"""
    mids = []
    for i, j in __import__("itertools").combinations(range(k), 2):
        base = np.full(k, 0.5)
        for vi in (0.0, 1.0):
            for vj in (0.0, 1.0):
                p = base.copy()
                p[i], p[j] = vi, vj
                mids.append(p)
    pts = np.vstack([np.array(mids), np.full((3, k), 0.5)])
    return pts, np.array([f(p) for p in pts])


# ============ MCMC 与 ABC ============
def metropolis_hastings(log_target, n=6000, burn=1000, x0=0.0, step=0.8,
                        rng=None):
    """MET025 MH：平稳分布抽样（均值/方差收敛检验）。"""
    rng = rng or np.random.default_rng(0)
    x = x0
    lp = log_target(x)
    out = []
    for i in range(n + burn):
        prop = x + rng.normal(0, step)
        lpp = log_target(prop)
        if np.log(rng.random() + 1e-300) < lpp - lp:
            x, lp = prop, lpp
        if i >= burn:
            out.append(x)
    return np.array(out)


def gibbs_normal(n=4000, burn=500, rng=None, rho=0.6):
    """MET026 Gibbs：二元正态条件分布轮换。"""
    rng = rng or np.random.default_rng(0)
    x, y = 0.0, 0.0
    out = []
    for i in range(n + burn):
        x = rng.normal(rho * y, np.sqrt(1 - rho ** 2))
        y = rng.normal(rho * x, np.sqrt(1 - rho ** 2))
        if i >= burn:
            out.append((x, y))
    return np.array(out)


def hmc_normal(n=3000, burn=300, L=12, eps=0.12, rng=None):
    """MET027 Hamiltonian 蒙特卡洛（标准正态目标，解析梯度）。"""
    rng = rng or np.random.default_rng(0)
    q = np.array([1.5])
    out = []
    for i in range(n + burn):
        p = rng.normal(size=1)
        q_new, p_new = q.copy(), p.copy()
        for _ in range(L):
            p_new = p_new - eps * q_new          # ∇U = q
            q_new = q_new + eps * p_new
        # 能量差（可反转积分误差）
        H0 = 0.5 * q @ q + 0.5 * p @ p
        H1 = 0.5 * q_new @ q_new + 0.5 * p_new @ p_new
        if np.log(rng.random() + 1e-300) < H0 - H1:
            q = q_new
        if i >= burn:
            out.append(q[0])
    return np.array(out)


def abc_rejection(sampler_fn, dist_fn, eps, n_accept=300, rng=None):
    """MET029 拒绝式 ABC：距离 ≤ ε 接受。"""
    rng = rng or np.random.default_rng(0)
    kept = []
    trials = 0
    while len(kept) < n_accept and trials < n_accept * 200:
        theta = rng.uniform(-1, 1)
        s = sampler_fn(theta, rng)
        if dist_fn(s) <= eps:
            kept.append(theta)
        trials += 1
    return np.array(kept), trials


def smc_abc(prior_sampler, sim_fn, dist_fn, schedule=(0.8, 0.4, 0.2),
            n_particles=300, rng=None):
    """MET030 序贯蒙特卡洛 ABC：逐级收缩 ε。"""
    rng = rng or np.random.default_rng(0)
    particles = [prior_sampler(rng) for _ in range(n_particles)]
    weights = np.full(n_particles, 1 / n_particles)
    for eps in schedule:
        kept = [p for p in particles if dist_fn(sim_fn(p, rng)) <= eps]
        if len(kept) < 10:
            kept = particles
        resample = rng.choice(kept, n_particles, replace=True)
        particles = [p + rng.normal(0, 0.1) for p in resample]
    return np.array(particles)


# ============ 估计 / 优化 ============
def simulated_moments(theta_sampler, sim_moments_fn, target_moments, rng,
                      n_theta=200):
    """MET036 模拟矩估计：网格上最小化矩距离。"""
    best, best_theta = np.inf, None
    for _ in range(n_theta):
        th = theta_sampler(rng)
        m = sim_moments_fn(th, rng)
        d = float(np.sum((np.asarray(m) - np.asarray(target_moments)) ** 2))
        if d < best:
            best, best_theta = d, th
    return best_theta, best


def cma_es(f, x0, sigma0=0.3, n_gen=60, pop=None, rng=None):
    """MET039 CMA-ES 简化（均值+全局协方差收缩步）。"""
    rng = rng or np.random.default_rng(0)
    x = np.asarray(x0, float).copy()
    sigma = sigma0
    pop = pop or 4 + int(3 * np.log(len(x) + 1))
    C = np.eye(len(x))
    for _ in range(n_gen):
        C = np.linalg.cholesky(C + 1e-9 * np.eye(len(x)))
        cand = [x + sigma * (C @ rng.standard_normal(len(x)))
                for _ in range(pop)]
        fits = [f(c) for c in cand]
        order = np.argsort(fits)
        best = np.mean([cand[i] for i in order[:max(1, pop // 2)]], axis=0)
        x = 0.7 * x + 0.3 * best
        sigma *= 0.95
    return x


def differential_evolution(f, bounds, pop_size=24, n_gen=80, rng=None):
    """MET040 差分演化（DE/rand/1/bin）。"""
    rng = rng or np.random.default_rng(0)
    d = len(bounds)
    pop = rng.uniform([b[0] for b in bounds], [b[1] for b in bounds],
                      (pop_size, d))
    fit = np.array([f(p) for p in pop])
    for _ in range(n_gen):
        for i in range(pop_size):
            a, b, c = rng.choice([j for j in range(pop_size) if j != i],
                                 3, replace=False)
            F = 0.7
            trial = pop[a] + F * (pop[b] - pop[c])
            cross = rng.random(d) < 0.9
            if not cross.any():
                cross[rng.integers(d)] = True
            trial = np.where(cross, trial, pop[i])
            trial = np.clip(trial, [b[0] for b in bounds],
                            [b[1] for b in bounds])
            ft = f(trial)
            if ft < fit[i]:
                pop[i], fit[i] = trial, ft
    return pop[int(np.argmin(fit))]


def gp_bayes_optimize(f, bounds, n_init=6, n_iter=25, rng=None):
    """MET041 高斯过程贝叶斯优化（RBF 核 + UCB 采集）。"""
    rng = rng or np.random.default_rng(0)
    lo, hi = bounds
    X = rng.uniform(lo, hi, (n_init, 1))
    y = np.array([f(x) for x in X])
    for _ in range(n_iter):
        def k(a, b, l=0.2):
            return float(np.exp(-float((a - b)) ** 2 / (2 * l ** 2)))
        n = len(X)
        K = np.array([[k(a, b) for b in X] for a in X]) + 1e-6 * np.eye(n)
        Kinv = np.linalg.inv(K)
        # UCB（最小化：μ - 2σ）
        grid = np.linspace(lo, hi, 200).reshape(-1, 1)
        Ks = np.array([[k(g, x) for x in X] for g in grid])
        mu_s = Ks @ Kinv @ y
        var_s = 1 - np.einsum("ij,jk,ik->i", Ks, Kinv, Ks)
        ucb = mu_s - 2 * np.sqrt(np.maximum(var_s, 0))
        xn = grid[int(np.argmin(ucb))].reshape(1, 1)
        X = np.vstack([X, xn])
        y = np.append(y, f(xn[0]))
    return float(X[int(np.argmin(y)), 0]), float(np.min(y))


def nsga2(f1, f2, bounds, pop_size=40, n_gen=50, rng=None):
    """MET042 NSGA-II 双目标：非支配排序 + 拥挤距离。"""
    rng = rng or np.random.default_rng(0)
    lo, hi = bounds
    pop = rng.uniform(lo, hi, pop_size)

    def dominates(a, b):
        fa, fb = f1(a), f1(b)
        ga, gb = f2(a), f2(b)
        return (fa <= fb and ga <= gb) and (fa < fb or ga < gb)

    for _ in range(n_gen):
        fronts = []
        remaining = list(pop)
        while remaining:
            front = [p for p in remaining
                     if not any(dominates(q, p) for q in remaining if q is not p)]
            fronts.append(front)
            remaining = [p for p in remaining if p not in front]
        pool = np.array(fronts[0] + (fronts[1] if len(fronts) > 1 else []),
                        float)
        off = pool + rng.normal(0, 0.1, pool.shape)
        pop = np.clip(np.concatenate([pop, off]), lo, hi)
        # 截断到 pop_size（按前沿层）
        scored = sorted(pop, key=lambda p: (f1(p) + f2(p)))
        pop = np.array(scored[:pop_size])
    fronts_final = [p for p in pop
                    if not any(dominates(q, p) for q in pop if q is not p)]
    return np.array(fronts_final)


# ============ 滤波与同化 ============
def kalman_filter(obs, q=0.1, r=1.0, x0=0.0):
    """MET043 Kalman：随机游走模型。返回 (估计序列, 末态方差)。"""
    x, P = x0, 1.0
    xs = []
    for z in obs:
        x_pred = x
        P_pred = P + q
        K = P_pred / (P_pred + r)
        x = x_pred + K * (z - x_pred)
        P = (1 - K) * P_pred
        xs.append(x)
    return np.array(xs), P


def extended_kalman(obs, f, h, F_jac, H_jac, q=0.01, r=0.5, x0=np.array([1.0])):
    """MET044 扩展 Kalman：非线性 f/h 线性化。"""
    x = np.asarray(x0, float).copy()
    P = np.eye(len(x))
    xs = []
    for z in obs:
        Fk = np.asarray(F_jac(x))
        x_pred = np.asarray(f(x))
        P_pred = Fk @ P @ Fk.T + q * np.eye(len(x))
        Hk = np.asarray(H_jac(x_pred))
        K = P_pred @ Hk.T / (Hk @ P_pred @ Hk.T + r)
        x = (x_pred + (K * (z - float(h(x_pred)))).ravel())
        P = (np.eye(len(x)) - K @ Hk) @ P_pred
        xs.append(x.ravel().copy())
    return np.array(xs), P


def enkf(obs, q=0.1, r=1.0, n_ens=200, x0=0.0, rng=None):
    """MET046 集合 Kalman（随机游走观测问题）。"""
    rng = rng or np.random.default_rng(0)
    ens = rng.normal(x0, 1.0, n_ens)
    xs = []
    for z in obs:
        ens = ens + rng.normal(0, np.sqrt(q), n_ens)          # 预报
        mean = ens.mean()
        var = ens.var() + r
        ens = ens + (z - ens) * (ens.var() / var)              # 更新（简化随机性）
        xs.append(float(mean))
    return np.array(xs), float(ens.var())


def bootstrap_particle_filter(obs, q=0.1, r=1.0, n=500, x0=0.0, rng=None):
    """MET047 Bootstrap 粒子滤波。"""
    rng = rng or np.random.default_rng(0)
    particles = rng.normal(x0, 1.0, n)
    weights = np.full(n, 1 / n)
    xs = []
    for z in obs:
        particles = particles + rng.normal(0, np.sqrt(q), n)
        weights = weights * np.exp(-0.5 * (z - particles) ** 2 / r) + 1e-300
        weights = weights / weights.sum()
        idx = rng.choice(n, n, p=weights)
        particles = particles[idx]
        weights = np.full(n, 1 / n)
        xs.append(float(np.average(particles, weights=weights)))
    return np.array(xs)


def auxiliary_pf(obs, q=0.1, r=1.0, n=500, x0=0.0, rng=None):
    """MET048 辅助粒子滤波：以预测似然预选父粒子。"""
    rng = rng or np.random.default_rng(0)
    particles = rng.normal(x0, 1.0, n)
    weights = np.full(n, 1 / n)
    xs = []
    for z in obs:
        # 辅助权重：预测似然
        aux = weights * np.exp(-0.5 * (z - particles) ** 2 / r) + 1e-300
        aux = aux / aux.sum()
        idx = rng.choice(n, n, p=aux)
        particles = particles[idx] + rng.normal(0, np.sqrt(q), n)
        weights = np.exp(-0.5 * (z - particles) ** 2 / r) + 1e-300
        weights = weights / weights.sum()
        xs.append(float(np.average(particles, weights=weights)))
    return np.array(xs)


def fourdvar(obs, f, x0, n_iter=40, gamma=0.05):
    """MET050 四维变分（伴随-free 数值梯度最速下降简化）。"""
    x = np.asarray(x0, float).copy()
    for _ in range(n_iter):
        # 数值梯度：扰动初值，模拟轨迹，末段观测失配
        g = np.zeros_like(x)
        eps = 1e-3
        for j in range(len(x)):
            xp = x.copy()
            xp[j] += eps
            traj_p = xp
            traj_0 = x
            for _ in range(5):
                traj_p = np.asarray(f(traj_p))
                traj_0 = np.asarray(f(traj_0))
            J = ((traj_p - obs[-1]) ** 2 - (traj_0 - obs[-1]) ** 2) / eps
            g[j] = J
        x = x - gamma * g
    return x


# ============ 敏感性 ============
def local_sensitivity(f, x0, eps=1e-5):
    """MET051 局部导数敏感性：∇f(x0) 归一化。"""
    x0 = np.asarray(x0, float)
    g = np.zeros(len(x0))
    for j in range(len(x0)):
        xp = x0.copy()
        xp[j] += eps
        g[j] = (f(xp) - f(x0)) / eps
    return g


def morris_screening(f, n_vars=4, n_traj=40, p=6, rng=None):
    """MET052 Morris 基本效应：μ* 排序识别重要因子。"""
    rng = rng or np.random.default_rng(0)
    delta = 2 / 3 * p / p
    ee = np.zeros((n_traj, n_vars))
    for k in range(n_traj):
        x = rng.integers(0, p, n_vars) / (p - 1)
        base = f(x)
        for j in range(n_vars):
            xp = x.copy()
            step = rng.choice([-1 / (p - 1), 1 / (p - 1)])
            xp[j] = np.clip(xp[j] + step, 0, 1)
            ee[k, j] = (f(xp) - base) / step
    mu_star = np.abs(ee).mean(axis=0)
    return mu_star


def sobol_indices(f, n_sob=4096, rng=None):
    """MET053 Sobol 方差分解（Saltelli 两矩阵）：一阶与总指标。"""
    rng = rng or np.random.default_rng(0)
    d = 2
    A = qmc.Sobol(d=d, seed=1).random(n_sob)
    B = qmc.Sobol(d=d, seed=2).random(n_sob)
    fA = np.array([f(x) for x in A])
    fB = np.array([f(x) for x in B])
    S1 = np.zeros(d)
    ST = np.zeros(d)
    V = float(fA.var())
    for j in range(d):
        AB = A.copy()
        AB[:, j] = B[:, j]
        fAB = np.array([f(x) for x in AB])
        BA = B.copy()
        BA[:, j] = A[:, j]
        fBA = np.array([f(x) for x in BA])
        S1[j] = float(np.mean(fB * (fAB - fA)) / V)
        ST[j] = float(0.5 * np.mean((fA - fAB) ** 2) / V)
    return S1, ST


def fast_sensitivity(f, n=1000, M=4):
    """MET054 扩展 FAST：频率基 Fourier 振幅（2 因子演示）。"""
    s1 = np.zeros(2)
    freqs = [M, M + 2]
    omegas = np.linspace(0, 2 * np.pi, n, endpoint=False)
    for k, w in enumerate(freqs):
        x = np.stack([0.5 + np.sin(w * omegas) / (2 * np.pi),
                      0.5 + np.sin(freqs[1 - k] * omegas) / (2 * np.pi)], axis=1)
        vals = np.array([f(xi) for xi in x])
        fc = np.abs(np.fft.fft(vals))[k] / n
        s1[k] = fc ** 2 * 2
    return s1 / max(s1.sum(), 1e-12)


def pawn_sensitivity(f, n=600, bins=10, rng=None):
    """MET055 PAWN 分布敏感性：条件 CDF 与无条件 CDF 的 KS 距离。"""
    rng = rng or np.random.default_rng(0)
    d = 2
    X = rng.random((n, d))
    y = np.array([f(x) for x in X])
    ks = np.zeros(d)
    for j in range(d):
        qs = np.quantile(X[:, j], np.linspace(0, 1, bins + 1))
        stat = 0.0
        for b in range(bins):
            mask = (X[:, j] >= qs[b]) & (X[:, j] <= qs[b + 1])
            if mask.sum() > 10:
                grid = np.linspace(y.min(), y.max(), 50)
                cdf_c = np.searchsorted(np.sort(y[mask]), grid) / mask.sum()
                cdf_a = np.searchsorted(np.sort(y), grid) / n
                stat = max(stat, float(np.abs(cdf_c - cdf_a).max()))
        ks[j] = stat
    return ks


def shapley_sensitivity(f, n_perm=30, baseline=None, rng=None):
    """MET056 Shapley 效应：随机置换边际贡献。"""
    rng = rng or np.random.default_rng(0)
    baseline = baseline if baseline is not None else np.zeros(2)
    d = len(baseline)
    sh = np.zeros(d)
    for _ in range(n_perm):
        perm = rng.permutation(d)
        x_prev = baseline.copy()
        f_prev = f(x_prev)
        for j in perm:
            x_next = x_prev.copy()
            x_next[j] = 1.0
            f_next = f(x_next)
            sh[j] += (f_next - f_prev) / n_perm
            x_prev, f_prev = x_next, f_next
    return sh


# ============ 不确定性与诊断 ============
def bootstrap_ci(data, stat_fn=np.mean, B=2000, alpha=0.05, rng=None):
    """MET057 非参数 Bootstrap 置信区间。"""
    rng = rng or np.random.default_rng(0)
    data = np.asarray(data)
    stats = np.array([stat_fn(data[rng.integers(0, len(data), len(data))])
                      for _ in range(B)])
    return float(np.quantile(stats, alpha / 2)), \
        float(np.quantile(stats, 1 - alpha / 2))


def posterior_predictive_check(obs, sim_post_predictive):
    """MET058 后验预测检查：观测统计量落在复制分布中位带内。"""
    obs_stat = float(np.mean(obs))
    sims = np.asarray(sim_post_predictive)
    p_val = float(np.mean(sims >= obs_stat))
    lo, hi = np.quantile(sims, [0.025, 0.975])
    return {"p_value": p_val, "inside_95": bool(lo <= obs_stat <= hi),
            "obs_stat": obs_stat}


def calibration_diagnosis(true_theta, est_theta, true_out, sim_out):
    """MET059 基于仿真的校准诊断：参数误差与输出失配。"""
    tt = np.asarray(true_theta, float)
    et = np.asarray(est_theta, float)
    to = np.asarray(true_out, float)
    so = np.asarray(sim_out, float)
    return {"param_err": float(np.abs(tt - et).max()),
            "output_mse": float(np.mean((to - so) ** 2)),
            "ok": bool(np.abs(tt - et).max() < 0.15 and
                       float(np.mean((to - so) ** 2)) < 0.05)}


# ============ 人口合成 ============
def ipf(seed_matrix, row_targets, col_targets, n_iter=100):
    """MET060 迭代比例拟合：行列和闭合。"""
    M = np.asarray(seed_matrix, float).copy()
    for _ in range(n_iter):
        M = M * (row_targets / np.maximum(M.sum(axis=1), 1e-12))[:, None]
        M = M * (col_targets / np.maximum(M.sum(axis=0), 1e-12))[None, :]
    return M


def ipu(weight_list, ind_constraints, hh_targets, n_iter=200, step=0.5):
    """MET061 迭代比例更新（IPU 简化梯度）：户权重拟合多约束。"""
    w = np.asarray(weight_list, float).copy()
    for _ in range(n_iter):
        # 每个约束类别：比例失配 → 权重更新
        for cat, (members, target) in ind_constraints.items():
            cur = float(w[members].sum())
            if cur > 1e-9:
                w[members] *= 1 + step * (target / cur - 1)
        w = np.maximum(w, 1e-6)
    return w


def weighted_record_sampling(weights, records, n_draw, rng=None):
    """MET062 加权记录抽样与整数化（最大余数法）。"""
    rng = rng or np.random.default_rng(0)
    w = np.asarray(weights, float)
    w = w / w.sum()
    counts = w * n_draw
    base = np.floor(counts).astype(int)
    frac = counts - base
    extra = n_draw - base.sum()
    order = np.argsort(-frac)
    base[order[:extra]] += 1
    out = []
    for rec, c in zip(records, base):
        out.extend([rec] * int(c))
    return out


def quasi_random_without_replacement(weights, n_draw, rng=None):
    """MET063 准随机无放回整数抽样：Bissonnette 式加权水塘。"""
    rng = rng or np.random.default_rng(0)
    w = np.asarray(weights, float)
    keys = rng.random(len(w)) ** (1 / np.maximum(w, 1e-12))
    order = np.argsort(-keys)[:n_draw]
    return order.tolist()


def combinatorial_optimization_synthesize(ind_pool, hh_types, target_marginals,
                                         n_iter=300, rng=None):
    """MET064 组合优化人口合成：随机交换最小化边际失配。"""
    rng = rng or np.random.default_rng(0)
    sel = list(rng.integers(0, len(ind_pool), size=sum(target_marginals)))
    tgt = np.asarray(target_marginals)

    def cost_of(s):
        return float(np.abs(np.bincount(s, minlength=len(ind_pool)) - tgt).sum())

    cur_cost = cost_of(sel)
    best_cost, best_sel = cur_cost, list(sel)
    for it in range(n_iter):
        i = int(rng.integers(0, len(sel)))
        c_new = int(rng.integers(0, len(ind_pool)))
        old = sel[i]
        sel[i] = c_new                 # 重派类别（swap 对边际是恒等操作）
        c = cost_of(sel)
        temp = max(0.05, 1.0 - it / n_iter)   # 退火降温
        if c < cur_cost or rng.random() < np.exp((cur_cost - c) / max(temp, 1e-9)):
            cur_cost = c
            if c < best_cost:
                best_cost, best_sel = c, list(sel)
        else:
            sel[i] = old               # 拒绝：恢复
    return best_sel, best_cost
