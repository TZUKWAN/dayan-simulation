"""DAYAN 经济家族批次 B：人口/迁移/婚配/健康/教育（目录 ECO057–ECO101）。

人口矩阵：Leslie（已有）、Lefkovitch 阶段结构、Rogers 多区域
死亡率与婚育：Lee–Carter、Gompertz–Makeham、Brass Logit、
Coale–McNeil 初婚、Hadwiger 生育
迁移：双约束引力（Wilson 最大熵）、辐射模型、Harris–Todaro
婚配：Becker 排序、Gale–Shapley 延迟接受
代际：Becker–Tomes 代际投资、代际收入 Markov 流动
健康经济：队列 Markov 奖励模型
教育：贝叶斯知识追踪 BKT
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


# ============ 人口矩阵 ============
class LefkovitchModel(DayanModel):
    """ECO058 Lefkovitch 阶段结构矩阵：n(t+1)=A n(t)，增长率=λ1（主特征值）。"""

    model_id = "ECO058"
    clock_type = "fixed_step"

    def __init__(self, A=None, stages=4, n0=(10, 5, 3, 2)):
        self.A = A if A is not None else np.array([
            [0.0, 1.2, 2.0, 2.5],
            [0.7, 0.0, 0.0, 0.0],
            [0.0, 0.6, 0.5, 0.0],
            [0.0, 0.0, 0.4, 0.6]])
        self.n = np.asarray(n0, float)

    def initialize(self, context, parameters, population, topology, rng):
        self.n = np.asarray(parameters.get("n0", (10, 5, 3, 2)), float)
        self.tick = 0

    def step(self, t, dt):
        self.n = self.A @ self.n
        self.tick += 1

    def observe(self):
        lam1 = float(max(abs(np.linalg.eigvals(self.A))))
        return {"total": float(self.n.sum()), "lambda1": lam1,
                "n": self.n.tolist()}

    def validate_state(self):
        return [] if (self.n >= 0).all() else ["负阶段数"]


class RogersMultiregionalModel(DayanModel):
    """ECO060 Rogers 多区域多状态人口：区域间迁移矩阵 k_i；总人口按主增长率增长。"""

    model_id = "ECO060"
    clock_type = "fixed_step"

    def __init__(self, regions=3, growth=(0.01, 0.02, -0.005), mig=0.03):
        self.regions = regions
        self.g = np.asarray(growth, float)
        self.m = mig
        self.pop = np.full(regions, 100.0)

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.pop = np.full(self.regions, parameters.get("p0", 100.0))
        self.R = None
        self.tick = 0

    def initialize_mig_matrix(self, rng):
        """重力式非对称迁移份额矩阵 R（行=来源，列=目的地，行和=1）。"""
        n = self.regions
        dist = rng.uniform(0.5, 5.0, (n, n))
        np.fill_diagonal(dist, np.inf)          # 不迁往自身
        attractiveness = self.pop / self.pop.sum()
        flow = attractiveness[None, :] * np.exp(-dist)
        R = flow / flow.sum(axis=1, keepdims=True)
        self.R = R

    def step(self, t, dt):
        # Rogers 多区域投影：pop_{t+1} = S·(pop - out + in)，非对称迁移矩阵
        if self.R is None:
            self.initialize_mig_matrix(self.rng_)
        out = self.m * dt * self.pop            # 各区迁出总量
        inm = self.R @ out                      # 按目的地份额分配 → 净迁移可非零
        self.pop = self.pop - out + inm
        self.pop = self.pop * (1 + self.g * dt)
        self.tick += 1

    def observe(self):
        return {"pop": self.pop.tolist(), "total": float(self.pop.sum())}

    def validate_state(self):
        return [] if (self.pop >= 0).all() else ["负人口"]


# ============ 死亡率与婚育 ============
class LeeCarterModel(DayanModel):
    """ECO061 Lee–Carter 死亡率：log m(x,t) = a_x + b_x·k_t（SVD 分解）。
    基准：合成数据重构残差远小于原方差。"""

    model_id = "ECO061"
    clock_type = "fixed_step"

    def __init__(self, ages=8, years=30):
        self.ages, self.years = ages, years
        self.resid_ratio = None

    def initialize(self, context, parameters, population, topology, rng):
        ax = rng.uniform(-5, -3, self.ages)
        bx = rng.uniform(0.5, 1.5, self.ages)
        kt = np.cumsum(rng.normal(-0.2, 0.5, self.years))
        logm = ax[:, None] + bx[:, None] * kt[None, :] + \
            rng.normal(0, 0.05, (self.ages, self.years))
        # LC 拟合：a = 行均值；SVD 第一主成分
        a_hat = logm.mean(axis=1, keepdims=True)
        center = logm - a_hat
        U, S, Vt = np.linalg.svd(center, full_matrices=False)
        b_hat = U[:, 0] * S[0]
        k_hat = Vt[0]
        recon = a_hat + b_hat[:, None] * k_hat[None, :]
        resid = ((logm - recon) ** 2).sum()
        total = ((logm - logm.mean()) ** 2).sum()
        self.resid_ratio = float(resid / total)

    def step(self, t, dt):
        pass

    def observe(self):
        return {"resid_ratio": self.resid_ratio,
                "good_fit": bool(self.resid_ratio < 0.05)}

    def validate_state(self):
        return []


class GompertzMakehamModel(DayanModel):
    """ECO064 Gompertz–Makeham：μ(x) = c + a·exp(b·x)；成人死亡率指数增长。"""

    model_id = "ECO064"
    clock_type = "fixed_step"

    def __init__(self, c=0.001, a=0.0002, b=0.09):
        self.c, self.a, self.b = c, a, b
        self.b_hat = None

    def initialize(self, context, parameters, population, topology, rng):
        ages = np.linspace(30, 90, 25)
        mu = self.c + self.a * np.exp(self.b * ages) + \
            rng.normal(0, self.c, 25) * 0.1
        mu = np.maximum(mu, 1e-8)
        log_mu_m_c = np.log(mu - self.c)
        coef = np.polyfit(ages, log_mu_m_c, 1)
        self.b_hat = float(coef[0])

    def step(self, t, dt):
        pass

    def observe(self):
        return {"b": self.b, "b_hat": self.b_hat,
                "err": abs(self.b - self.b_hat) if self.b_hat else None}

    def validate_state(self):
        return []


class BrassLogitModel(DayanModel):
    """ECO063 Brass 关系 Logit：logit(F_x) = α + β·logit(F_x^std) 线性关系。
    合成双生命表验证线性拟合 R²。"""

    model_id = "ECO063"
    clock_type = "fixed_step"

    def __init__(self, alpha=-0.5, beta=1.2):
        self.alpha, self.beta = alpha, beta
        self.r2 = None

    @staticmethod
    def _logit(p):
        p = np.clip(p, 1e-6, 1 - 1e-6)
        return np.log(p / (1 - p))

    def initialize(self, context, parameters, population, topology, rng):
        x = np.linspace(0.02, 0.98, 40)
        std = 1 / (1 + np.exp(-self._logit(x)))  # 标准表（自映射=恒等）
        target = 1 / (1 + np.exp(-(self.alpha + self.beta * self._logit(x))))
        X = self._logit(std)
        y = self._logit(target)
        coef = np.polyfit(X, y, 1)
        pred = np.polyval(coef, X)
        ss_res = ((y - pred) ** 2).sum()
        ss_tot = ((y - y.mean()) ** 2).sum()
        self.r2 = float(1 - ss_res / ss_tot)

    def step(self, t, dt):
        pass

    def observe(self):
        return {"alpha": self.alpha, "beta": self.beta, "fit_r2": self.r2}

    def validate_state(self):
        return []


class CoaleMcNeilModel(DayanModel):
    """ECO065 Coale–McNeil 初婚年龄密度：G(a) 标准曲线，均值/方差已知。"""

    model_id = "ECO065"
    clock_type = "fixed_step"

    def __init__(self, a0=15.0, k=1.2, mu=0.8):
        self.a0, self.k, self.mu = a0, k, mu
        self.mean_age = None
        self.std_age = None

    def initialize(self, context, parameters, population, topology, rng):
        ages = np.linspace(self.a0, self.a0 + 25, 500)
        z = (ages - self.a0 - self.k * self.mu) / self.k
        dens = (1 / self.k) * 0.7797 * np.exp(-1.1454 * (z + 0.196054)
                                              - np.exp(-2.2908 * (z + 0.196054)))
        dens /= dens.sum()
        self.mean_age = float((ages * dens).sum())
        self.std_age = float(np.sqrt(((ages - self.mean_age) ** 2 * dens).sum()))

    def step(self, t, dt):
        pass

    def observe(self):
        return {"mean_age": self.mean_age, "std_age": self.std_age,
                "peak_reasonable": bool(16 < self.mean_age < 26)}

    def validate_state(self):
        return []


class HadwigerModel(DayanModel):
    """ECO066 Hadwiger 生育曲线：g(a) = (β/b)·(a/α)^{β-1}·exp(-(a/α)-β²α/a) 单峰。"""

    model_id = "ECO066"
    clock_type = "fixed_step"

    def __init__(self, alpha=21.0, b=5.0, beta=1.3):
        self.alpha, self.b, self.beta = alpha, b, beta
        self.peak_age = None

    def initialize(self, context, parameters, population, topology, rng):
        ages = np.linspace(12, 50, 400)
        a = np.maximum(ages, 1e-6)
        g = (self.beta / self.b) * (a / self.alpha) ** (self.beta - 1) * \
            np.exp(-a / self.alpha - (self.beta ** 2) * self.alpha / a)
        self.peak_age = float(ages[np.argmax(g)])

    def step(self, t, dt):
        pass

    def observe(self):
        return {"peak_age": self.peak_age,
                "unimodal": bool(20 < self.peak_age < 32)}

    def validate_state(self):
        return []


# ============ 迁移 ============
class UnconstrainedGravityModel(DayanModel):
    """ECO067 unconstrained origin–destination flow with explicit scale and impedance."""
    model_id="ECO067"
    clock_type="fixed_step"

    def __init__(self, origin=(80.,120.), destination=(95.,105.), distance=((0.,8.),(8.,0.)),
                 origin_elasticity=1., destination_elasticity=1., distance_elasticity=1., scale=.001):
        self.origin,self.destination=np.asarray(origin,float),np.asarray(destination,float)
        self.distance=np.asarray(distance,float)
        self.origin_elasticity,self.destination_elasticity=origin_elasticity,destination_elasticity
        self.distance_elasticity,self.scale=distance_elasticity,scale
        n=len(self.origin)
        if (self.origin.shape!=(n,) or self.destination.shape!=(n,) or self.distance.shape!=(n,n)
                or not 2<=n<=100 or any(not np.isfinite(x).all() or np.any(x<0)
                                      for x in (self.origin,self.destination,self.distance))
                or min(origin_elasticity,destination_elasticity,distance_elasticity,scale)<0):
            raise ValueError("需要同维有限非负的起点人口、吸引量与距离矩阵")
        self.off_diagonal=~np.eye(n,dtype=bool)
        if np.any(self.distance[self.off_diagonal]<=0):
            raise ValueError("地理单位之间的距离必须为正")

    def initialize(self, context, parameters, population, topology, rng):
        weights=np.outer(self.origin**self.origin_elasticity,self.destination**self.destination_elasticity)
        with np.errstate(over='ignore', invalid='ignore'):
            flow=self.scale*weights/np.where(self.off_diagonal,self.distance,1.)**self.distance_elasticity
        self.flow=np.where(self.off_diagonal,flow,0.)
        if not np.isfinite(self.flow).all():
            raise ValueError("流量计算溢出")

    def step(self, t, dt):
        pass

    def observe(self):
        return {"od_flows":self.flow.tolist(),"outflow":self.flow.sum(axis=1).tolist(),
                "inflow":self.flow.sum(axis=0).tolist(),"total_flow":float(self.flow.sum())}

    def validate_state(self):
        return []


class WilsonGravityModel(DayanModel):
    """ECO069 Wilson 双约束最大熵空间交互：T_ij = A_i B_j O_i D_j exp(-βc_ij)，
    IPF 迭代使行列和闭合。基准：行和=O、列和=D。"""

    model_id = "ECO069"
    clock_type = "fixed_step"

    def __init__(self, n=6, beta=0.1):
        self.n, self.beta = n, beta
        rng = np.random.default_rng(5)
        self.O = rng.uniform(50, 200, n)
        self.D = self.O * (1 + rng.normal(0, 0.05, n))
        self.D *= self.O.sum() / self.D.sum()
        d = np.abs(np.subtract.outer(np.arange(n), np.arange(n))) + 1
        self.cost = d * 10.0

    def initialize(self, context, parameters, population, topology, rng):
        base = np.exp(-self.beta * self.cost)
        self.T = np.outer(self.O, self.D) * base
        self.T /= self.T.sum()
        self.T *= self.O.sum()
        self.tick = 0

    def step(self, t, dt):
        self.T *= self.O[:, None] / np.maximum(self.T.sum(axis=1), 1e-9)[:, None]
        self.T *= self.D[None, :] / np.maximum(self.T.sum(axis=0), 1e-9)[None, :]
        self.tick += 1

    def observe(self):
        row_err = float(np.abs(self.T.sum(axis=1) - self.O).max())
        col_err = float(np.abs(self.T.sum(axis=0) - self.D).max())
        return {"row_err": row_err, "col_err": col_err,
                "converged": bool(row_err < 0.1 and col_err < 0.1)}

    def validate_state(self):
        return []


class RadiationModel(DayanModel):
    """ECO070 Simini 辐射迁移：T_ij = T_i·(m_ij / (p_ij + Σ T_k)) 形式；
    验证：流量守恒与单调衰减（距离↑ 流量↓）。"""

    model_id = "ECO070"
    clock_type = "fixed_step"

    def __init__(self, n=8):
        self.n = n
        rng = np.random.default_rng(21)
        self.pop = rng.uniform(10, 100, n)
        d = np.abs(np.subtract.outer(np.arange(n), np.arange(n))) * 5.0 + 1
        self.dist = d
        self.T = np.zeros((n, n))

    def initialize(self, context, parameters, population, topology, rng):
        n = self.n
        for i in range(n):
            sorted_j = np.argsort(self.dist[i])
            for j in sorted_j:
                if j == i:
                    continue
                p_ij = self.dist[i, j]
                # 辐射分子：比 i、j 更近的人口和
                closer = self.pop[(self.dist[i] < p_ij) &
                                  (np.arange(n) != i)].sum()
                T_ij = self.pop[i] * self.pop[j] / \
                    ((self.pop[i] + closer) * (self.pop[i] + closer + self.pop[j]))
                self.T[i, j] = T_ij

    def step(self, t, dt):
        pass

    def observe(self):
        flat_d = []
        flat_t = []
        for i in range(self.n):
            for j in range(self.n):
                if i != j and self.T[i, j] > 0:
                    flat_d.append(self.dist[i, j])
                    flat_t.append(self.T[i, j])
        corr = float(np.corrcoef(flat_d, flat_t)[0, 1]) if len(flat_d) > 2 else 0
        return {"corr_dist_flow": corr,
                "total_flow": float(self.T.sum()),
                "decay": bool(corr < 0)}

    def validate_state(self):
        return []


class HarrisTodaroModel(DayanModel):
    """ECO071 Harris–Todaro 城乡迁移：w_u·E_u/N_u = w_r（期望收入均衡）。
    现代部门工资高于农村 → 迁移直至失业率消化差距。"""

    model_id = "ECO071"
    clock_type = "fixed_step"

    def __init__(self, w_u=50.0, w_r=20.0, N_u0=40.0, E_u0=30.0, N_r=100.0):
        self.w_u, self.w_r = w_u, w_r
        self.N_u, self.E_u, self.N_r = N_u0, E_u0, N_r

    def initialize(self, context, parameters, population, topology, rng):
        self.N_u = parameters.get("N_u0", self.N_u)
        self.E_u = parameters.get("E_u0", self.E_u)
        self.N_r = parameters.get("N_r", self.N_r)
        self.tick = 0

    def step(self, t, dt):
        expected_u = self.w_u * min(self.E_u, self.N_u) / max(self.N_u, 1e-9)
        # 迁移响应期望收入差
        mig = 0.05 * (expected_u - self.w_r)
        self.N_u = max(1.0, self.N_u + mig)
        self.N_r = max(1.0, self.N_r - mig)
        # 就业按需求调整
        self.E_u = 0.9 * self.E_u + 0.1 * (self.N_u * self.w_r / self.w_u)
        self.tick += 1

    def observe(self):
        expected = self.w_u * min(self.E_u, self.N_u) / max(self.N_u, 1e-9)
        unemp = max(0.0, (self.N_u - self.E_u) / max(self.N_u, 1e-9))
        return {"expected_u": float(expected), "w_r": float(self.w_r),
                "gap": float(expected - self.w_r), "unemp_rate": float(unemp)}

    def validate_state(self):
        return []


# ============ 婚配 ============
class BeckerMarriageModel(DayanModel):
    """ECO073 Becker 婚姻市场：正/负分类婚配（同质匹配按比较优势排序）。
    验证：所得效用矩阵下最优匹配为排序匹配。"""

    model_id = "ECO073"
    clock_type = "fixed_step"

    def __init__(self, n=10):
        self.n = n
        self.sorting = None

    def initialize(self, context, parameters, population, topology, rng):
        q_m = np.sort(rng.uniform(1, 10, self.n))   # 男质量
        q_f = np.sort(rng.uniform(1, 10, self.n))   # 女质量
        # 产出 Z = q_m·q_f（互补 → 正分类最优）
        Z = np.outer(q_m, q_f)
        # 贪心排序匹配（互补产出下等价于最优）
        order_m = np.argsort(-q_m)
        order_f = np.argsort(-q_f)
        Z_sorted = sum(Z[order_m[i], order_f[i]] for i in range(self.n))
        # 反向匹配
        Z_reverse = sum(Z[order_m[i], order_f[-1 - i]] for i in range(self.n))
        self.sorting = bool(Z_sorted >= Z_reverse)
        self.gain = float(Z_sorted - Z_reverse)

    def step(self, t, dt):
        pass

    def observe(self):
        return {"assortative_optimal": self.sorting, "gain": self.gain}

    def validate_state(self):
        return []


class GaleShapleyModel(DayanModel):
    """ECO074 Gale–Shapley 延迟接受：稳定匹配（无阻塞对）。"""

    model_id = "ECO074"
    clock_type = "fixed_step"

    def __init__(self, n=12):
        self.n = n
        self.stable = None

    def initialize(self, context, parameters, population, topology, rng):
        n = self.n
        pref_m = np.array([rng.permutation(n) for _ in range(n)])
        pref_f = np.array([rng.permutation(n) for _ in range(n)])
        rank_f = np.argsort(pref_f, axis=1)  # rank_f[f][m] = 男 m 在女 f 的排名
        rank_m = np.argsort(pref_m, axis=1)  # rank_m[m][f] = 女 f 在男 m 的排名
        f_partner = [-1] * n
        m_next = np.zeros(n, int)
        free = list(range(n))
        while free:
            m = free.pop()
            if m_next[m] >= n:
                continue
            f = pref_m[m][m_next[m]]
            m_next[m] += 1
            if f_partner[f] == -1:
                f_partner[f] = m
            else:
                cur = f_partner[f]
                if rank_f[f][m] < rank_f[f][cur]:
                    f_partner[f] = m
                    free.append(cur)
                else:
                    free.append(m)
        # 稳定性：无阻塞对 (m,f)：m 更偏好 f 于其当前，f 更偏好 m 于其当前
        m_partner = [-1] * n
        for f, m in enumerate(f_partner):
            if m >= 0:
                m_partner[m] = f
        blocking = 0
        for m in range(n):
            for f in range(n):
                fm = m_partner[m]
                mf = f_partner[f]
                if mf == m:
                    continue
                # 男 m 相比自己的配对 fm 更偏好女 f；女 f 相比配对 mf 更偏好男 m
                m_prefers = fm == -1 or rank_m[m][f] < rank_m[m][fm]
                f_prefers = mf == -1 or rank_f[f][m] < rank_f[f][mf]
                if m_prefers and f_prefers:
                    blocking += 1
        self.stable = bool(blocking == 0)
        self.blocking = blocking

    def step(self, t, dt):
        pass

    def observe(self):
        return {"stable": self.stable, "blocking_pairs": self.blocking}

    def validate_state(self):
        return []


# ============ 代际 ============
class BeckerTomesModel(DayanModel):
    """ECO076 Becker–Tomes 代际投资：I ∝ (1-α)·Y，收入弹性 α<1 →
    代际收入弹性 <1（均值回归）。"""

    model_id = "ECO076"
    clock_type = "fixed_step"

    def __init__(self, alpha=0.5, h_elast=0.3, generations=8):
        self.alpha, self.h_elast = alpha, h_elast
        self.generations = generations
        self.y = 1.0
        self.path = [1.0]

    def initialize(self, context, parameters, population, topology, rng):
        self.y = parameters.get("y0", 1.0)
        self.path = [self.y]

    def step(self, t, dt):
        # y_{t+1} = A·y_t^{α·h_elast} + 噪声项期望 → 对数弹性 α·h_elast
        elast = self.alpha * self.h_elast
        self.y = 0.8 * self.y ** elast + 0.4
        self.path.append(self.y)

    def observe(self):
        p = np.log(np.array(self.path))
        if len(p) > 3:
            ar = float(np.corrcoef(p[:-1], p[1:])[0, 1])
        else:
            ar = 0.0
        return {"y": float(self.y), "gen_elast": self.alpha * self.h_elast,
                "log_autocorr": ar, "mean_revert": bool(ar < 0.9)}

    def validate_state(self):
        return []


class IntergenerationalMarkovModel(DayanModel):
    """ECO077 代际收入阶层 Markov 流动：转移矩阵 P，遍历后分布收敛。
    基准：谱隙>0 → 收敛；稳态分布满足 πP=π。"""

    model_id = "ECO077"
    clock_type = "fixed_step"

    def __init__(self, P=None):
        self.P = P if P is not None else np.array([
            [0.6, 0.3, 0.1],
            [0.3, 0.5, 0.2],
            [0.15, 0.35, 0.5]])
        self.dist = np.array([1.0, 0.0, 0.0])

    def initialize(self, context, parameters, population, topology, rng):
        self.dist = np.asarray(parameters.get("dist", [1.0, 0.0, 0.0]), float)
        self.tick = 0

    def step(self, t, dt):
        self.dist = self.dist @ self.P
        self.tick += 1

    def observe(self):
        evals = np.linalg.eigvals(self.P.T)
        gap = float(1 - np.max(np.abs(evals[1:])))
        pi = self.dist
        stat = pi @ self.P
        err = float(np.abs(stat - pi).max())
        return {"dist": self.dist.tolist(), "spectral_gap": gap,
                "stationary_err": err, "converged": bool(err < 1e-8)}

    def validate_state(self):
        return []


# ============ 健康经济 ============
class HealthMarkovModel(DayanModel):
    """ECO099 健康队列 Markov 奖励模型：健康/病/死 状态+周期成本/QALY。"""

    model_id = "ECO099"
    clock_type = "fixed_step"

    def __init__(self, P=None, costs=(0.0, 5.0, 0.0), qaly=(1.0, 0.5, 0.0)):
        self.P = P if P is not None else np.array([
            [0.90, 0.08, 0.02],
            [0.00, 0.85, 0.15],
            [0.00, 0.00, 1.00]])
        self.costs, self.qaly = costs, qaly
        self.dist = np.array([1.0, 0.0, 0.0])
        self.total_cost = 0.0
        self.total_qaly = 0.0

    def initialize(self, context, parameters, population, topology, rng):
        self.dist = np.array([1.0, 0.0, 0.0])
        self.total_cost = self.total_qaly = 0.0
        self.tick = 0

    def step(self, t, dt):
        self.total_cost += float(self.dist @ np.array(self.costs))
        self.total_qaly += float(self.dist @ np.array(self.qaly))
        self.dist = self.dist @ self.P
        self.tick += 1

    def observe(self):
        return {"dead": float(self.dist[2]), "total_cost": self.total_cost,
                "total_qaly": self.total_qaly,
                "ICER_finite": bool(self.total_qaly > 0)}

    def validate_state(self):
        return [] if abs(self.P.sum(axis=1) - 1).max() < 1e-9 else ["转移矩阵行和≠1"]


# ============ 教育 ============
class BKTModel(DayanModel):
    """ECO091 贝叶斯知识追踪：P(L_{t+1}) = P(L_t)+(1-P)L_t·正确后验更新。
    基准：答对序列 → 掌握概率单调升；答错也升（学习参数）。"""

    model_id = "ECO091"
    clock_type = "fixed_step"

    def __init__(self, p0=0.1, learn=0.15, slip=0.1, guess=0.2, seq=30):
        self.p0, self.learn, self.slip, self.guess, self.seq = \
            p0, learn, slip, guess, seq
        self.p = p0
        self.history = []

    def initialize(self, context, parameters, population, topology, rng):
        self.rng = rng
        self.p = self.p0
        self.history = []
        self.tick = 0

    def step(self, t, dt):
        if self.tick >= self.seq:
            return
        self.tick += 1
        correct = self.rng.random() < (self.p * (1 - self.slip) +
                                       (1 - self.p) * self.guess)
        # 贝叶斯后验（含 slip/guess）
        like = (1 - self.slip) if correct else self.slip
        likg = self.guess if correct else (1 - self.guess)
        post = self.p * like / (self.p * like + (1 - self.p) * likg)
        self.p = post + (1 - post) * self.learn
        self.history.append({"correct": bool(correct), "p": float(self.p)})

    def observe(self):
        p_path = [h["p"] for h in self.history]
        return {"p_now": float(self.p),
                "p_rising": bool(len(p_path) > 10 and
                                 p_path[-1] > p_path[5]),
                "n_correct": sum(h["correct"] for h in self.history)}

    def validate_state(self):
        return []
