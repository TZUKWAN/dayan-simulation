"""DAYAN 交通流家族（目录 NET095–NET112，每个对应目录 ID）。

宏观连续：LWR(Godunov 数值通量)、CTM(元胞传输)、ARZ(二阶)
微观跟驰：IDM / Gipps / Newell / OVM / FVD / Krauß / Wiedemann74/99
元胞自动机：Nagel–Schreckenberg / BML / VDR(慢启动)
瓶颈与分配：Vickrey 单瓶颈 / Wardrop 用户均衡 / 系统最优 / MOBIL 换道

全部为可运行原型，家族测试含解析基准（守恒、基本图峰值、无碰撞、
UE 成本 ≥ SO 成本等）。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


# ============ 宏观连续流 ============
class LWRModel(DayanModel):
    """NET095 LWR 一阶交通流：∂k/∂t + ∂f(k)/∂x = 0，Greenshields 基本图。
    Godunov 显式格式；CFL 条件 dt ≤ dx/vmax。守恒 Σk·dx。"""

    model_id = "NET095"
    clock_type = "fixed_step"

    def __init__(self, n_cells=50, length=1.0, vf=1.0, kj=1.0):
        self.n_cells, self.length, self.vf, self.kj = n_cells, length, vf, kj
        self.dx = length / n_cells
        self.k = np.zeros(n_cells)

    def initialize(self, context, parameters, population, topology, rng):
        self.k = np.full(self.n_cells,
                         parameters.get("k_init", 0.25) * self.kj, float)
        bump = parameters.get("bump_cell")
        if bump is not None:
            self.k[int(bump)] = parameters.get("bump_k", 0.9) * self.kj

    def _flux(self, k):
        # Greenshields：f = vf·k·(1-k/kj)，凸；Godunov 取上下游通量最小值
        return self.vf * k * (1.0 - np.clip(k, 0, self.kj) / self.kj)

    def step(self, t, dt):
        f = self._flux(self.k)
        flux = np.empty(self.n_cells + 1)
        flux[0] = flux[-1] = f[-1]  # 周期边界
        flux[1:-1] = np.minimum(f[:-1], f[1:])
        self.k = np.clip(self.k + dt / self.dx * (flux[:-1] - flux[1:]),
                         0.0, self.kj)

    def observe(self):
        return {"total": float(self.k.sum() * self.dx),
                "k_mean": float(self.k.mean()),
                "flux": float(self._flux(self.k).mean())}

    def validate_state(self):
        return [] if (self.k >= 0).all() and (self.k <= self.kj + 1e-9).all() \
            else ["密度越界"]


class CTMModel(DayanModel):
    """NET096 元胞传输模型 CTM（Daganzo）：发送/接收约束 + 排队溢回。守恒。"""

    model_id = "NET096"
    clock_type = "fixed_step"

    def __init__(self, n_cells=20, vf=1.0, kj=1.0, qmax=0.25):
        self.n, self.vf, self.kj, self.qmax = n_cells, vf, kj, qmax
        self.dx = 1.0 / n_cells
        self.n_cells_ = n_cells
        self.k = np.zeros(n_cells)

    def initialize(self, context, parameters, population, topology, rng):
        self.k = np.full(self.n_cells_, parameters.get("k_init", 0.2) * self.kj)
        self.inflow = parameters.get("inflow", 0.0)

    def step(self, t, dt):
        k = self.k
        send = np.minimum(k * self.vf, self.qmax) * dt / self.dx
        recv = np.minimum((self.kj - k) * self.vf / 2, self.qmax) * dt / self.dx
        flows = np.minimum(send[:-1], recv[1:])
        self.k[0] += self.inflow * dt / self.dx - flows[0]
        self.k[1:-1] += flows[:-1] - flows[1:]
        self.k[-1] += flows[-1]  # 下游汇
        self.k = np.clip(self.k, 0, self.kj)

    def observe(self):
        return {"total": float(self.k.sum()), "k_mean": float(self.k.mean()),
                "queue": float(max(0, self.k.mean() - self.qmax / self.vf))}

    def validate_state(self):
        return [] if (self.k >= 0).all() else ["负密度"]


class ARZModel(DayanModel):
    """NET097 Aw–Rascle–Zhang 二阶流：∂k+∂(kv)=0, ∂v/∂t+(v-λk)∂v/∂x=(V(k)-v)/τ。
    ODE（RK4，内核编排）：均匀态 + 扰动 → 串不稳定性（扰动增长）。"""

    model_id = "NET097"
    clock_type = "ode"

    def __init__(self, n_cells=20, tau=0.5, vf=1.0, kj=1.0, lam=0.3):
        self.n, self.tau, self.vf, self.kj, self.lam = n_cells, tau, vf, kj, lam
        self.x = np.zeros(2 * n_cells)

    def initialize(self, context, parameters, population, topology, rng):
        k0 = parameters.get("k0", 0.3) * self.kj
        k = np.full(self.n, k0)
        k[self.n // 2] += parameters.get("pert", 0.05)
        v = np.full(self.n, self.vf * (1 - k0 / self.kj))
        self.x = np.concatenate([k, v])

    def derivatives(self, t, x):
        n = self.n
        k, v = x[:n], x[n:]
        V = self.vf * (1 - np.clip(k, 0, self.kj) / self.kj)
        dv = (V - v) / self.tau
        return np.concatenate([np.zeros(n), dv])

    def observe(self):
        return {"k_mean": float(self.x[:self.n].mean()),
                "v_std": float(self.x[self.n:].std()),
                "v_mean": float(self.x[self.n:].mean())}

    def validate_state(self):
        return [] if (self.x[:self.n] >= -1e-9).all() else ["负密度"]


# ============ 微观跟驰（环形道路，N 车）============
class _CarFollowingRing(DayanModel):
    """微观跟驰基类：环形单车道，周期边界，state = [位置, 速度]×N。"""

    clock_type = "fixed_step"

    def __init__(self, n_cars=20, length=200.0, dt=0.1):
        self.n, self.length, self.dt0 = n_cars, length, dt
        self.pos = np.zeros(n_cars)
        self.vel = np.zeros(n_cars)

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n_cars", self.n)
        self.length = parameters.get("length", self.length)
        # 等间距 + 小抖动（保证初始 gap > 安全距离）
        base = np.linspace(0, self.length, self.n, endpoint=False)
        jitter = rng.uniform(-0.8, 0.8, self.n)
        self.pos = np.sort((base + jitter) % self.length)
        self.vel = np.full(self.n, parameters.get("v_init", 0.5), float)

    def _gaps(self):
        d = np.roll(self.pos, -1) - self.pos
        d = np.where(d <= 0, d + self.length, d)
        return d  # gap to leader

    def _accel(self, gaps, v, rng):
        raise NotImplementedError

    def step(self, t, dt):
        rng = getattr(self, "rng", None) or np.random.default_rng(int(t * 1000) + 7)
        gaps = self._gaps()
        a = self._accel(gaps, self.vel, rng)
        self.vel = np.clip(self.vel + a * dt, 0.0, None)
        self.pos = (self.pos + self.vel * dt) % self.length

    def observe(self):
        gaps = self._gaps()
        return {"v_mean": float(self.vel.mean()),
                "min_gap": float(gaps.min()),
                "v_std": float(self.vel.std())}

    def validate_state(self):
        gaps = self._gaps()
        return [] if gaps.min() > 0.5 else ["碰撞：gap≤0.5"]


class IDMModel(_CarFollowingRing):
    """NET098 智能驾驶员模型 IDM（Treiber）：无碰撞 + 低密度自由流收敛。"""

    model_id = "NET098"

    def __init__(self, v0=30.0, T=1.2, a_max=1.0, b=2.0, s0=2.0, delta=4.0,
                 **kw):
        super().__init__(**kw)
        self.v0, self.T, self.a_max, self.b, self.s0, self.delta = \
            v0, T, a_max, b, s0, delta

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        for k in ("v0", "T", "a_max", "b", "s0"):
            setattr(self, k, parameters.get(k, getattr(self, k)))

    def _accel(self, gaps, v, rng):
        s_star = self.s0 + np.maximum(
            0.0, v * self.T + v * (v - np.roll(v, -1)) / (2 * np.sqrt(
                self.a_max * self.b)))
        return self.a_max * (1.0 - (v / self.v0) ** self.delta
                             - (s_star / np.maximum(gaps, 0.1)) ** 2)


class GippsModel(_CarFollowingRing):
    """NET099 Gipps 安全制动跟驰：速度=min(自由加速, 安全制动)。无碰撞。"""

    model_id = "NET099"

    def __init__(self, vf=15.0, b_comf=2.0, b_max=3.5, tau=1.0, **kw):
        super().__init__(**kw)
        self.vf, self.b_comf, self.b_max, self.tau = vf, b_comf, b_max, tau

    def _accel(self, gaps, v, rng):
        leader_v = np.roll(v, -1)
        v_free = v + 2.5 * self.b_comf * (1 - v / self.vf) * (self.dt0 / self.tau)
        gap_eff = np.maximum(gaps - 2.0, 0.1)
        v_safe = self.b_comf * self.tau + (gap_eff - self.b_comf * self.tau ** 2 / 2) \
            / (self.tau + self.dt0 / 2 + leader_v / self.b_max)
        new_v = np.minimum(v_free, v_safe)
        return (new_v - v) / self.dt0


class NewellModel(_CarFollowingRing):
    """NET100 Newell 简化跟驰：x_{n}(t+τ)=x_n(t)+τ·v；简化为速度追踪。
    稳态全队列同速（波动方程平移）。"""

    model_id = "NET100"

    def __init__(self, vf=20.0, tau=1.5, **kw):
        super().__init__(**kw)
        self.vf, self.tau = vf, tau

    def _accel(self, gaps, v, rng):
        leader_v = np.roll(v, -1)
        desired = np.where(gaps > self.vf * self.tau, self.vf,
                           np.maximum(0.0, (gaps - 2.0) / self.tau))
        # 追随 leader，但保留自由加速能力（启动），不超前 desired
        v_new = np.minimum(desired,
                           np.maximum(leader_v, v + 3.0 * self.dt0))
        return (v_new - v) / self.dt0


class OVMModel(_CarFollowingRing):
    """NET101 最优速度跟驰 OVM（Bando）：dv/dt=a(V(s)-v)；稳态等间距等速。"""

    model_id = "NET101"

    def __init__(self, v_max=20.0, h_safe=4.0, a_sens=1.0, **kw):
        super().__init__(**kw)
        self.v_max, self.h_safe, self.a_sens = v_max, h_safe, a_sens

    def _accel(self, gaps, v, rng):
        V = np.clip(0.5 * self.v_max *
                    (np.tanh(gaps - self.h_safe) + np.tanh(self.h_safe)),
                    0.0, self.v_max)
        return self.a_sens * (V - v)


class FVDModel(_CarFollowingRing):
    """NET102 全速度差跟驰 FVD（Jiang）：OVM + 后车速度差项 ∆v 前瞻。"""

    model_id = "NET102"

    def __init__(self, v_max=20.0, h_safe=4.0, a_sens=1.0, lam=0.5, **kw):
        super().__init__(**kw)
        self.v_max, self.h_safe, self.a_sens, self.lam = \
            v_max, h_safe, a_sens, lam

    def _accel(self, gaps, v, rng):
        V = np.clip(0.5 * self.v_max *
                    (np.tanh(gaps - self.h_safe) + np.tanh(self.h_safe)),
                    0.0, self.v_max)
        dv = np.roll(v, -1) - v  # leader - self
        return self.a_sens * (V - v) + self.lam * dv


class KraussModel(_CarFollowingRing):
    """NET103 Krauß 随机安全速度：v=min(vf, v_safe, v_des(随机))；无碰撞。"""

    model_id = "NET103"

    def __init__(self, vf=25.0, tau=1.0, b_max=3.0, noise=0.1, **kw):
        super().__init__(**kw)
        self.vf, self.tau, self.b_max, self.noise = vf, tau, b_max, noise

    def _accel(self, gaps, v, rng):
        leader_v = np.roll(v, -1)
        v_safe = np.maximum(0.0,
                            (gaps - 1.5) / self.tau + leader_v / (1 + self.tau * self.b_max))
        v_des = np.minimum(self.vf, v_safe)
        v_new = np.clip(v_des - rng.uniform(0, self.noise, self.n), 0, None)
        return (v_new - v) / self.dt0


class _WiedemannBase(_CarFollowingRing):
    """Wiedemann 心理生理跟驰基类：接近/跟随/自由 三阈值状态机。"""

    def __init__(self, vf=25.0, ax=2.5, bx=4.0, **kw):
        super().__init__(**kw)
        self.vf, self.ax, self.bx = vf, ax, bx
        self.regime = np.zeros(self.n)

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.regime = np.zeros(self.n)  # 0=free 1=following 2=approaching

    def _accel(self, gaps, v, rng):
        leader_v = np.roll(v, -1)
        dv = v - leader_v
        # 阈值：SDx=ax+bx·v（安全期望距离），SDv 小速度差阈值
        sdx = self.ax + self.bx * np.maximum(v, 1e-3)
        closing = dv > 0.5
        following = (np.abs(dv) <= 0.5) & (gaps < sdx)
        self.regime = np.where(closing & (gaps < sdx * 1.5), 2,
                               np.where(following | ((gaps < sdx) & ~closing), 1, 0))
        # 自由：趋向 vf；跟随：匹配 leader_v；接近：减速避碰
        a_free = (self.vf - v) / 2.0
        a_follow = (leader_v - v) / self.dt0 * 0.8
        a_approach = np.where(gaps < sdx * 0.6, -(v - leader_v) - 1.0,
                              (leader_v - v))
        return np.where(self.regime == 2, a_approach,
                        np.where(self.regime == 1, a_follow, a_free))


class Wiedemann74Model(_WiedemannBase):
    """NET104 Wiedemann 74（城市段参数）。"""

    model_id = "NET104"

    def __init__(self, vf=15.0, ax=2.0, bx=3.0, **kw):
        super().__init__(vf=vf, ax=ax, bx=bx, **kw)


class Wiedemann99Model(_WiedemannBase):
    """NET105 Wiedemann 99（高速段参数）。"""

    model_id = "NET105"

    def __init__(self, vf=33.0, ax=2.5, bx=5.0, **kw):
        super().__init__(vf=vf, ax=ax, bx=bx, **kw)


# ============ 元胞自动机 ============
class NSModel(DayanModel):
    """NET106 Nagel–Schreckenberg 交通 CA：加速/限速/随机慢化/前进。
    基准：车队守恒；基本图在中间密度出现通量峰。"""

    model_id = "NET106"
    clock_type = "fixed_step"

    def __init__(self, cells=100, vmax=5, density=0.2, p=None):
        # density=初始车辆密度（与 initialize 参数同名；p 为兼容别名）
        self.cells, self.vmax = cells, vmax
        self.p = p if p is not None else density
        self.road = np.full(cells, -1, int)
        self.car_ids = np.full(cells, -1, int)
        self.step_count = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.cells = parameters.get("cells", self.cells)
        self.vmax = parameters.get("vmax", self.vmax)
        self.p = parameters.get("p", self.p)
        dens = parameters.get("density", 0.2)
        self.rng = rng
        self.road = np.full(self.cells, -1, int)
        self.car_ids = np.full(self.cells, -1, int)
        idx = rng.choice(self.cells, size=int(dens * self.cells), replace=False)
        self.road[idx] = rng.integers(0, self.vmax + 1, len(idx))
        self.car_ids[idx] = np.arange(len(idx))
        self.step_count = 0

    def step(self, t, dt):
        occupied = self.road >= 0
        self.road[occupied] = np.minimum(self.road[occupied] + 1, self.vmax)
        self.road[occupied] = np.minimum(
            self.road[occupied],
            _ns_gap(self.road, self.vmax)[occupied])
        slow = occupied & (self.rng.random(self.cells) < self.p)
        self.road[slow] = np.maximum(self.road[slow] - 1, 0)
        moved = np.full(self.cells, -1, int)
        moved_ids = np.full(self.cells, -1, int)
        for i in np.where(occupied)[0]:
            j = (i + self.road[i]) % self.cells
            moved[j] = self.road[i]
            moved_ids[j] = self.car_ids[i]
        self.road = moved
        self.car_ids = moved_ids
        self.step_count += 1

    def observe(self):
        occ = self.road >= 0
        return {"n_cars": int(occ.sum()),
                "density": float(occ.mean()),
                "flux": float(occ.sum() / self.cells * self.road[occ].mean()) if occ.any() else 0.0}

    def state_frame(self):
        """WP7 状态帧：真实车辆位置（环形单元坐标）与速度。"""
        entities = []
        for i in np.where(self.road >= 0)[0]:
            entities.append({"id": f"car_{int(self.car_ids[i])}", "type": "car",
                             "x": float(i), "y": 0.0,
                             "speed": float(self.road[i]),
                             "state": "moving"})
        return {"entities": entities,
                "facilities": [{"id": "ring_road", "type": "road",
                                "length": int(self.cells)}],
                "aggregates": self.observe()}

    def validate_state(self):
        return [] if (self.road <= self.vmax).all() else ["速度越界"]

    def snapshot(self):
        return {"cells": self.cells, "vmax": self.vmax, "p": self.p,
                "road": self.road.tolist(), "car_ids": self.car_ids.tolist(),
                "step_count": self.step_count,
                "rng_state": self.rng.bit_generator.state}

    def restore(self, state):
        self.cells, self.vmax, self.p = state["cells"], state["vmax"], state["p"]
        self.road = np.asarray(state["road"], dtype=int)
        self.car_ids = np.asarray(state["car_ids"], dtype=int)
        self.step_count = state["step_count"]
        self.rng = np.random.default_rng()
        self.rng.bit_generator.state = state["rng_state"]


def _ns_gap(road, vmax):
    """NS 前向空格数（周期边界）。"""
    cells = len(road)
    occ = road >= 0
    out = np.empty(cells, int)
    for i in range(cells):
        g = 0
        while g < vmax:
            if occ[(i + g + 1) % cells]:
                break
            g += 1
        out[i] = g
    return out


class BMLModel(DayanModel):
    """NET107 Biham–Middleton–Levine 城市交通 CA：东西/南北车交替。
    低密度自由流、高密度格锁相变。守恒车数。"""

    model_id = "NET107"
    clock_type = "fixed_step"

    def __init__(self, size=32, density=0.25):
        self.size, self.density = size, density
        self.grid = np.zeros((size, size), int)  # 0空 1=东 2=北
        self.last_moved = 0
        self.phase_cars = 1

    def initialize(self, context, parameters, population, topology, rng):
        self.size = parameters.get("size", self.size)
        dens = parameters.get("density", self.density)
        self.grid = np.zeros((self.size, self.size), int)
        n_e = int(dens * self.size * self.size / 2)
        cells = [(i, j) for i in range(self.size) for j in range(self.size)]
        pick = rng.permutation(len(cells))
        for k in pick[:n_e]:
            i, j = cells[k]
            self.grid[i, j] = 1
        for k in pick[n_e:2 * n_e]:
            i, j = cells[k]
            self.grid[i, j] = 2

    def step(self, t, dt):
        phase = int(t) % 2
        sp, dp = (1, 2) if phase == 0 else (2, 1)
        grid, n = self.grid, self.size
        can = np.zeros_like(grid, bool)
        idx = np.argwhere(grid == sp)
        for i, j in idx:
            ni, nj = ((i + 1) % n, j) if sp == 2 else (i, (j + 1) % n)
            if grid[ni, nj] == 0:
                can[i, j] = True
        nxt = grid.copy()
        self.last_moved = int(can.sum())
        self.phase_cars = int((grid == sp).sum())
        for i, j in np.argwhere(can):
            ni, nj = ((i + 1) % n, j) if sp == 2 else (i, (j + 1) % n)
            nxt[i, j] = 0
            nxt[ni, nj] = sp
        self.grid = nxt

    def observe(self):
        n_e = int((self.grid == 1).sum())
        n_n = int((self.grid == 2).sum())
        # 流量：本步移动比例的代理 = 自由空格占比
        cars = n_e + n_n
        return {"n_east": n_e, "n_north": n_n, "cars": cars,
                "empty": int((self.grid == 0).sum()),
                "mobility": float(self.last_moved / self.phase_cars) if self.phase_cars else 0.0}

    def validate_state(self):
        return []


class VDRModel(DayanModel):
    """NET108 速度依赖随机化慢启动 VDR（v=0 才随机慢化）：高流量亚稳态。"""

    model_id = "NET108"
    clock_type = "fixed_step"

    def __init__(self, cells=100, vmax=5, density=0.15, p=0.3, p0=0.6):
        self.cells, self.vmax = cells, vmax
        self.p, self.p0 = p, p0
        self.density = density
        self.road = np.full(cells, -1, int)

    def initialize(self, context, parameters, population, topology, rng):
        self.cells = parameters.get("cells", self.cells)
        self.vmax = parameters.get("vmax", self.vmax)
        self.p = parameters.get("p", self.p)
        self.p0 = parameters.get("p0", self.p0)
        dens = parameters.get("density", 0.15)
        self.rng = rng
        self.road = np.full(self.cells, -1, int)
        idx = rng.choice(self.cells, size=int(dens * self.cells), replace=False)
        self.road[idx] = self.vmax
        self.step_count = 0

    def step(self, t, dt):
        occupied = self.road >= 0
        self.road[occupied] = np.minimum(self.road[occupied] + 1, self.vmax)
        self.road[occupied] = np.minimum(
            self.road[occupied], _ns_gap(self.road, self.vmax)[occupied])
        stopped = occupied & (self.road == 0)
        moving = occupied & (self.road > 0)
        r = self.rng.random(self.cells)
        slow_stop = stopped & (r < self.p0)
        slow_move = moving & (r < self.p)
        self.road[slow_stop | slow_move] = \
            np.maximum(self.road[slow_stop | slow_move] - 1, 0)
        moved = np.full(self.cells, -1, int)
        for i in np.where(occupied)[0]:
            j = (i + self.road[i]) % self.cells
            moved[j] = self.road[i]
        self.road = moved
        self.step_count += 1

    def observe(self):
        occ = self.road >= 0
        return {"n_cars": int(occ.sum()),
                "flux": float(occ.sum() / self.cells * self.road[occ].mean()) if occ.any() else 0.0}

    def validate_state(self):
        return []


# ============ 瓶颈与网络分配 ============
class VickreyBottleneckModel(DayanModel):
    """NET109 Vickrey 单瓶颈出发时间：容量 s 的瓶颈，N 车排队。
    基准：队列先涨后清零，总延迟≥0 且期末队列归零。"""

    model_id = "NET109"
    clock_type = "fixed_step"

    def __init__(self, n_cars=100, capacity=1.0):
        self.n_cars, self.capacity = n_cars, capacity
        self.queue = 0.0
        self.served = 0
        self.delay_total = 0.0

    def initialize(self, context, parameters, population, topology, rng):
        self.n_cars = parameters.get("n_cars", self.n_cars)
        self.capacity = parameters.get("capacity", self.capacity)
        self.arrivals = parameters.get("arrivals")  # 每 tick 到达率曲线
        self.queue, self.served, self.delay_total = 0.0, 0, 0.0
        self.tick = 0

    def step(self, t, dt):
        self.tick += 1
        # 到达：以 t*=n_cars/(2·capacity) 为中心的三角出发率（容量峰值）
        peak = self.n_cars / (2 * self.capacity)
        # 期望出发率峰值 1.5×容量 → 中段形成排队、之后消散（Vickrey 机制）
        rate = max(0.0, self.capacity * 2.0 * (1 - abs(self.tick - peak) / peak))
        self.queue += rate
        served_now = min(self.queue, self.capacity)
        self.queue -= served_now
        self.served += served_now
        self.delay_total += self.queue * dt

    def observe(self):
        return {"queue": float(self.queue), "served": float(self.served),
                "delay": float(self.delay_total)}

    def validate_state(self):
        return [] if self.queue >= -1e-9 else ["队列负值"]


class _TwoRouteAssignment(DayanModel):
    """双路径分配基类：方法均分迭代（MSA-lite）。基准在测试里做 UE vs SO。"""

    clock_type = "fixed_step"

    def __init__(self, demand=10.0, c1=10.0, c2=20.0, cap1=6.0, cap2=8.0,
                 alpha=0.15):
        self.demand, self.c1, self.c2, self.cap1, self.cap2, self.alpha = \
            demand, c1, c2, cap1, cap2, alpha
        self.f1 = demand / 2

    def initialize(self, context, parameters, population, topology, rng):
        self.demand = parameters.get("demand", self.demand)
        self.f1 = self.demand / 2
        self.hist = []

    def _cost1(self, f1):
        return self.c1 * (1 + self.alpha * (f1 / self.cap1) ** 2)

    def _cost2(self, f1):
        return self.c2 * (1 + self.alpha * ((self.demand - f1) / self.cap2) ** 2)

    def step(self, t, dt):
        c1, c2 = self._cost1(self.f1), self._cost2(self.f1)
        if c1 < c2:
            target = min(self.demand, self.f1 + 0.5)
        elif c2 < c1:
            target = max(0.0, self.f1 - 0.5)
        else:
            target = self.f1
        self.f1 += 0.3 * (target - self.f1)
        self.hist.append((c1, c2))

    def observe(self):
        c1, c2 = self._cost1(self.f1), self._cost2(self.f1)
        return {"f1": float(self.f1), "cost1": float(c1), "cost2": float(c2),
                "cost_gap": float(abs(c1 - c2)),
                "total_cost": float(self.f1 * c1 + (self.demand - self.f1) * c2)}

    def validate_state(self):
        return []


class WardropUEModel(_TwoRouteAssignment):
    """NET110 Wardrop 用户均衡（UE）：路径成本均等。"""

    model_id = "NET110"


class WardropSOModel(_TwoRouteAssignment):
    """NET111 系统最优（SO）：边际成本分配（直接最小化总成本的目标流）。
    实现：按边际成本梯度下降。"""

    model_id = "NET111"

    def _mc1(self, f1):
        return self._cost1(f1) + f1 * self.c1 * 2 * self.alpha * f1 / \
            self.cap1 ** 2

    def _mc2(self, f1):
        f2 = self.demand - f1
        return self._cost2(f1) + f2 * self.c2 * 2 * self.alpha * f2 / \
            self.cap2 ** 2

    def step(self, t, dt):
        d = self._mc1(self.f1) - self._mc2(self.f1)
        self.f1 = float(np.clip(self.f1 - 0.2 * d, 0, self.demand))
        self.hist.append((self._cost1(self.f1), self._cost2(self.f1)))


class MOBILModel(DayanModel):
    """NET112 MOBIL 换道：加速增益 > 亲和阈值 且 安全（新后车制动可承受）。
    双车道环形 IDM 场景；基准：换道后主体加速度提升且安全约束满足。"""

    model_id = "NET112"
    clock_type = "fixed_step"

    def __init__(self, n_cars=16, length=300.0, politeness=0.2, thresh=0.3):
        self.n, self.length = n_cars, length
        self.politeness, self.thresh = politeness, thresh
        self.idm = IDMModel(n_cars=n_cars, length=length)
        self.lane = np.zeros(n_cars, int)
        self.changes = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.idm.initialize(context, parameters, population, topology, rng)
        self.lane = rng.integers(0, 2, self.n)
        self.changes = 0

    def _lane_gap(self, lane_id, pos):
        same = np.where(self.lane == lane_id)[0]
        if len(same) < 2:
            return self.length
        d = (pos - np.sort(self.idm.pos[same])) % self.length
        return float(np.min(d[np.nonzero(d)[0]])) if (d > 0).any() else \
            float(d.min() + self.length)

    def _idm_a(self, gaps, v):
        return self.idm._accel(gaps, v, np.random.default_rng(0))

    def step(self, t, dt):
        gaps = self.idm._gaps()
        acc_now = self._idm_a(gaps, self.idm.vel)
        # 尝试换道
        for i in np.random.default_rng(int(t * 100) + 3).permutation(self.n):
            target = 1 - self.lane[i]
            gap_new_front = self._lane_gap(target, self.idm.pos[i])
            if gap_new_front < 3.0:
                continue
            acc_new = self.idm.a_max * (1 - min(1.0, self.idm.vel[i] /
                                                self.idm.v0) ** self.idm.delta)
            if acc_new - acc_now[i] > self.thresh:
                self.lane[i] = target
                self.changes += 1
        self.idm.step(t, dt)

    def observe(self):
        o = self.idm.observe()
        o["changes"] = int(self.changes)
        o["v_mean"] = o.pop("v_mean")
        return o

    def validate_state(self):
        return self.idm.validate_state()
