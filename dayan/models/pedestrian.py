"""DAYAN 行人家族（目录 NET113–NET120）。

社会力族：Helbing–Molnár 社会力 / 含接触排斥疏散 / 广义离心力
速度障碍族：VO / RVO / ORCA
元胞与步长：静态—动态地板场 CA / 最优步长 OSM

家族测试：疏散完成、无墙体穿透、无碰撞、地板场最短路径、
OSM 到达目标等解析/结构性基准。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel

R_PED = 0.3  # 行人半径（m）


def _wall_repulse(pos, bounds, k_wall=8.0, decay=0.15):
    """四面墙的短程指数排斥力（Helbing 形式，力程~0.5m）。
    pos (n,2), bounds (xmin,ymin,xmax,ymax)。"""
    xmin, ymin, xmax, ymax = bounds
    f = np.zeros_like(pos)
    for dim, lo, hi in ((0, xmin, xmax), (1, ymin, ymax)):
        d_lo = np.maximum(pos[:, dim] - lo, 0.02)
        d_hi = np.maximum(hi - pos[:, dim], 0.02)
        f[:, dim] += k_wall * np.exp(-d_lo / decay)
        f[:, dim] -= k_wall * np.exp(-d_hi / decay)
    return f


class _PedBase(DayanModel):
    """行人基类：矩形房间 + 出口（y=ymax 边中段），state=位置/速度。"""

    clock_type = "fixed_step"

    def __init__(self, n=30, bounds=(0, 0, 12, 12), exit_half=1.5,
                 v_des=1.5, dt=0.05):
        self.n, self.bounds, self.exit_half = n, bounds, exit_half
        self.v_des, self.dt0 = v_des, dt
        self.pos = np.zeros((n, 2))
        self.vel = np.zeros((n, 2))
        self.evacuated = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        self.v_des = parameters.get("v_des", self.v_des)
        xmin, ymin, xmax, ymax = self.bounds
        self.pos = np.stack([rng.uniform(xmin + 1, xmax - 1, self.n),
                             rng.uniform(ymin + 1, ymax - 2, self.n)], axis=1)
        self.vel = np.zeros((self.n, 2))
        self.evacuated = 0
        self.exited_at = np.full(self.n, -1)
        self.rng = rng

    def _exit_y(self):
        return self.bounds[3]

    def _directions(self):
        """指向出口中点 (xmax/2, ymax) 的单位方向。"""
        target = np.array([ (self.bounds[0] + self.bounds[2]) / 2.0,
                            self.bounds[3] ])
        d = target - self.pos
        dist = np.linalg.norm(d, axis=1, keepdims=True)
        return d / np.maximum(dist, 0.05), dist[:, 0]

    def _wall_forces_exit_aware(self):
        """四面墙排斥，但出口带宽内无顶墙排斥（出口是开口）。"""
        f = _wall_repulse(self.pos, self.bounds)
        ex_mid = (self.bounds[0] + self.bounds[2]) / 2.0
        in_band = np.abs(self.pos[:, 0] - ex_mid) <= self.exit_half + 0.8
        f[in_band, 1] = np.minimum(f[in_band, 1], 0.0)
        return f

    def _pair_forces(self):
        return np.zeros_like(self.pos)

    def _step_forces(self, rng):
        raise NotImplementedError

    def step(self, t, dt):
        alive = self.exited_at < 0
        if not alive.any():
            return
        force = np.zeros((self.n, 2))
        force[alive] = self._step_forces(self.rng)[alive]
        # 期望速度投影
        e_hat, dist = self._directions()
        speed = np.clip(self.v_des * np.ones(self.n), 0, None)
        drive = (speed[:, None] * e_hat - self.vel) / 0.5
        force = force + drive
        self.vel = self.vel + force * dt
        sp = np.linalg.norm(self.vel, axis=1, keepdims=True)
        vmax = self.v_des * 1.6
        over = sp[:, 0] > vmax
        if over.any():
            self.vel[over] *= (vmax / sp[over])
        self.pos = self.pos + self.vel * dt
        # 出口判定
        ex_mid = (self.bounds[0] + self.bounds[2]) / 2.0
        at_exit = alive & (self.pos[:, 1] >= self.bounds[3] - 0.4) & \
            (np.abs(self.pos[:, 0] - ex_mid) <= self.exit_half)
        self.exited_at[at_exit] = int(t / dt)
        self.evacuated = int((self.exited_at >= 0).sum())
        # 出口的个体退场（移到场外）
        gone = self.exited_at >= 0
        self.pos[gone] = -100.0

    def observe(self):
        alive = self.exited_at < 0
        pos_a = self.pos[alive]
        sep = None
        if alive.sum() > 1:
            d = np.linalg.norm(pos_a[:, None, :] - pos_a[None, :, :], axis=-1)
            np.fill_diagonal(d, np.inf)
            sep = float(d.min()) if d.size else None
        return {"evacuated": self.evacuated, "alive": int(alive.sum()),
                "min_separation": sep,
                "in_bounds": bool((pos_a[:, 0] > self.bounds[0] - 0.2).all() and
                                  (pos_a[:, 0] < self.bounds[2] + 0.2).all() and
                                  (pos_a[:, 1] > self.bounds[1] - 0.2).all())}

    def state_frame(self):
        """WP7 状态帧：真实行人位置/速度/进出状态。"""
        entities = []
        for i in range(self.n):
            exited = self.exited_at[i] >= 0
            entities.append({
                "id": f"ped_{i}", "type": "pedestrian",
                "x": float(self.pos[i, 0]), "y": float(self.pos[i, 1]),
                "speed": float(np.linalg.norm(self.vel[i])),
                "state": "exited" if exited else "moving"})
        return {"entities": entities,
                "space":{"bounds":list(map(float,self.bounds)),"unit":"m"},
                "facilities": [{"id":"room","type":"model_facility","kind":"room","label":"模型房间边界","role":"context",
                                "x":float((self.bounds[0]+self.bounds[2])/2),"y":float((self.bounds[1]+self.bounds[3])/2),
                                "width":float(self.bounds[2]-self.bounds[0]),"depth":float(self.bounds[3]-self.bounds[1])},
                               {"id": "exit", "type": "model_facility","kind":"exit","label":"模型出口","role":"modeled",
                                "width":float(self.exit_half*2),"depth":.25,
                                "x": float((self.bounds[0] + self.bounds[2]) / 2),
                                "y": float(self.bounds[3])}],
                "aggregates": self.observe()}

    def validate_state(self):
        return []


class SocialForceModel(_PedBase):
    """NET113 Helbing–Molnár 社会力：心理排斥 + 墙排斥 + 驱动力。全疏散。"""

    model_id = "NET113"

    def _step_forces(self, rng):
        f = np.zeros_like(self.pos)
        # 行人-行人 社会排斥（0.3m 强、随距离指数衰减）
        for i in range(self.n):
            if self.exited_at[i] >= 0:
                continue
            d = self.pos - self.pos[i]
            dist = np.linalg.norm(d, axis=1)
            dist[i] = np.inf
            near = dist < 1.2
            if near.any():
                mag = 2.0 * np.exp(-(dist[near] - 2 * R_PED) / 0.3)
                f[i] += -(mag[:, None] * d[near] /
                          np.maximum(dist[near], 0.05)[:, None]).sum(axis=0)
        f += self._wall_forces_exit_aware()
        return f


class ContactEvacModel(SocialForceModel):
    """NET114 疏散社会力，带基于几何重叠的法向接触排斥项。"""

    model_id = "NET114"

    def _step_forces(self, rng):
        f = super()._step_forces(rng)
        # 接触项：重叠时强推挤（身体不可压缩）
        for i in range(self.n):
            if self.exited_at[i] >= 0:
                continue
            d = self.pos - self.pos[i]
            dist = np.linalg.norm(d, axis=1)
            dist[i] = np.inf
            overlap = 2 * R_PED - dist
            hit = overlap > 0
            if hit.any():
                push = 12.0 * overlap[hit]
                f[i] += -(push[:, None] * d[hit] /
                          np.maximum(dist[hit], 0.05)[:, None]).sum(axis=0)
        return f


class CentrifugalModel(_PedBase):
    """NET115 广义离心力行人模型：排斥力 ∝ 1/distance（Yu et al.）。
    基准：任意时刻最小间距 ≥ 2r×0.8（离心力防穿模）。"""

    model_id = "NET115"

    def _step_forces(self, rng):
        f = np.zeros_like(self.pos)
        for i in range(self.n):
            if self.exited_at[i] >= 0:
                continue
            d = self.pos - self.pos[i]
            dist = np.linalg.norm(d, axis=1)
            dist[i] = np.inf
            near = dist < 1.5
            if near.any():
                mag = 1.5 / np.maximum(dist[near] - 2 * R_PED, 0.1)
                f[i] += -(mag[:, None] * d[near] /
                          np.maximum(dist[near], 0.05)[:, None]).sum(axis=0)
        f += self._wall_forces_exit_aware()
        return f


# ============ 速度障碍族 ============
class _VOBase(_PedBase):
    """速度障碍基类： Crossing flows，避碰优先于前进。"""

    def __init__(self, **kw):
        kw.setdefault("n", 20)
        super().__init__(**kw)

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        # 两股对穿人流：左→右 与 下→上
        half = self.n // 2
        xmin, ymin, xmax, ymax = self.bounds
        self.pos[:half] = np.stack([rng.uniform(xmin + 1, xmin + 3, half),
                                    rng.uniform(ymin + 1, ymax - 1, half)], axis=1)
        self.pos[half:] = np.stack([rng.uniform(xmin + 1, xmax - 1, self.n - half),
                                    rng.uniform(ymin + 1, ymin + 3, self.n - half)], axis=1)
        self.vel = np.zeros((self.n, 2))
        self.exited_at = np.full(self.n, -1)
        self.target = np.zeros((self.n, 2))
        self.target[:half] = np.stack([np.full(half, xmax - 0.5),
                                       self.pos[:half, 1]], axis=1)
        self.target[half:] = np.stack([self.pos[half:, 0],
                                       np.full(self.n - half, ymax - 0.5)], axis=1)

    def _directions(self):
        d = self.target - self.pos
        dist = np.linalg.norm(d, axis=1, keepdims=True)
        return d / np.maximum(dist, 0.05), dist[:, 0]

    def _vo_avoid(self, v_pref):
        """VO/RVO/ORCA 子类实现：返回修正速度。"""
        raise NotImplementedError

    def step(self, t, dt):
        alive = self.exited_at < 0
        if not alive.any():
            return
        e_hat, dist = self._directions()
        v_pref = self.v_des * e_hat
        v_new = v_pref.copy()
        v_new[alive] = self._vo_avoid(v_pref)[alive]
        self.vel = v_new
        self.pos = self.pos + self.vel * dt
        arrived = alive & (np.linalg.norm(self.target - self.pos, axis=1) < 0.4)
        self.exited_at[arrived] = int(t / dt)
        self.evacuated = int((self.exited_at >= 0).sum())

    def observe(self):
        alive = self.exited_at < 0
        pos_a = self.pos[alive]
        col = 0
        if alive.sum() > 1:
            d = np.linalg.norm(pos_a[:, None, :] - pos_a[None, :, :], axis=-1)
            np.fill_diagonal(d, np.inf)
            col = int((d < 2 * R_PED * 0.8).sum() // 2) if d.size else 0
        return {"arrived": self.evacuated, "alive": int(alive.sum()),
                "collisions": col}


class VOModel(_VOBase):
    """NET116 速度障碍 VO：他车成为障碍时绕行（一阶避碰）。"""

    model_id = "NET116"

    def _vo_avoid(self, v_pref):
        v = v_pref.copy()
        for i in range(self.n):
            if self.exited_at[i] >= 0:
                continue
            for j in range(self.n):
                if j == i or self.exited_at[j] >= 0:
                    continue
                rel = self.pos[j] - self.pos[i]
                dist = np.linalg.norm(rel)
                if dist > 2.5:
                    continue
                # VO 锥内 → 垂直偏转
                along = np.dot(v[i], rel / max(dist, 0.05))
                if along > 0:
                    perp = np.array([-rel[1], rel[0]]) / max(dist, 0.05)
                    v[i] = v[i] + 0.8 * perp * self.v_des
        return v


class RVOModel(_VOBase):
    """NET117 互惠速度障碍 RVO：双方各承担一半避让（更平滑）。"""

    model_id = "NET117"

    def _vo_avoid(self, v_pref):
        v = v_pref.copy()
        for i in range(self.n):
            if self.exited_at[i] >= 0:
                continue
            for j in range(self.n):
                if j == i or self.exited_at[j] >= 0:
                    continue
                rel = self.pos[j] - self.pos[i]
                dist = np.linalg.norm(rel)
                if dist > 2.5:
                    continue
                mid = 0.5 * (v[i] + v[j])
                along = np.dot(v[i] - mid, rel / max(dist, 0.05))
                if along > 0:
                    perp = np.array([-rel[1], rel[0]]) / max(dist, 0.05)
                    v[i] = v[i] + 0.5 * perp * self.v_des
        return v


class ORCAModel(_VOBase):
    """NET118 最优互惠碰撞避免 ORCA：线性约束半平面投影（n 步时距）。
    基准：穿越人流零碰撞。"""

    model_id = "NET118"
    tau = 2.0  # 避碰时距

    def _vo_avoid(self, v_pref):
        v = v_pref.copy()
        for i in range(self.n):
            if self.exited_at[i] >= 0:
                continue
            u_total = np.zeros(2)
            cnt = 0
            for j in range(self.n):
                if j == i or self.exited_at[j] >= 0:
                    continue
                rel = self.pos[j] - self.pos[i]
                dist = np.linalg.norm(rel)
                rsum = 2 * R_PED
                if dist > rsum + 0.4 or dist < 1e-6:
                    continue
                w = rel / dist
                # 半平面：外侧偏移（互惠一半）
                u = (0.5 * rsum / self.tau) * w
                # 简化线性化：沿 w 方向推出 + 切向滑
                u_total += u
                cnt += 1
            if cnt:
                v[i] = v_pref[i] - u_total + 0.3 * u_total
        return v


class FloorFieldModel(DayanModel):
    """NET119 静态—动态地板场行人 CA：S 静态距离场 + D 动态轨迹场。
    基准：行人沿 S 场梯度到达出口，步数 ≈ 最短路径长度。"""

    model_id = "NET119"
    clock_type = "fixed_step"

    def __init__(self, size=24):
        self.size = size
        self.S = None
        self.D = np.zeros((size, size))
        self.agents = []  # (i,j)
        self.steps_taken = 0

    def _bfs_distance(self, exits):
        """出口 BFS 距离场（4 邻域，曼哈顿近似）。"""
        n = self.size
        S = np.full((n, n), -1.0)
        frontier = list(exits)
        for i, j in exits:
            S[i, j] = 0.0
        cur = 0
        while frontier:
            nxt = []
            for i, j in frontier:
                for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    ni, nj = i + di, j + dj
                    if 0 <= ni < n and 0 <= nj < n and S[ni, nj] < 0:
                        S[ni, nj] = cur + 1
                        nxt.append((ni, nj))
            frontier = nxt
            cur += 1
        return S

    def initialize(self, context, parameters, population, topology, rng):
        n = self.size = parameters.get("size", self.size)
        self.D = np.zeros((n, n))
        exits = parameters.get("exits", [(n - 1, n // 2)])
        self.S = self._bfs_distance(exits)
        n_agents = parameters.get("n_agents", 8)
        self.agents = []
        cells = [(i, j) for i in range(n) for j in range(n)
                 if self.S[i, j] > 0]
        pick = rng.permutation(len(cells))[:n_agents]
        self.agents = [tuple(cells[k]) for k in pick]
        self.steps_taken = 0

    def step(self, t, dt):
        rng = np.random.default_rng(int(t) + 11)
        moves = {}
        for idx, (i, j) in enumerate(self.agents):
            if self.S[i, j] == 0:
                continue
            best, bi, bj = None, i, j
            for di in (-1, 0, 1):
                for dj in (-1, 0, 1):
                    ni, nj = i + di, j + dj
                    if not (0 <= ni < self.size and 0 <= nj < self.size):
                        continue
                    score = self.S[ni, nj] - 0.3 * self.D[ni, nj]
                    if best is None or score < best:
                        best, bi, bj = score, ni, nj
            moves[idx] = (bi, bj)
        # 冲突：同格唯一
        claimed = {}
        for idx, cell in moves.items():
            claimed.setdefault(cell, []).append(idx)
        for idx, (i, j) in enumerate(self.agents):
            if self.S[i, j] == 0:
                continue
            cell = moves[idx]
            if len(claimed[cell]) == 1:
                self.D[i, j] += 1
                self.agents[idx] = cell
                self.steps_taken += 1

    def observe(self):
        at_exit = sum(1 for (i, j) in self.agents if self.S[i, j] == 0)
        dists = [self.S[i, j] for (i, j) in self.agents]
        return {"at_exit": at_exit, "total": len(self.agents),
                "max_remaining": int(max(dists)) if dists else 0,
                "steps": self.steps_taken}

    def validate_state(self):
        return [] if len(self.agents) == len(set(self.agents)) else ["格位冲突"]


class OptimalStepsModel(DayanModel):
    """NET120 最优步长行人模型 OSM：逐 tick 选使
    (前进收益 − 近邻排斥 − 加速度代价) 最大的一步。基准：到达目标。"""

    model_id = "NET120"
    clock_type = "fixed_step"

    def __init__(self, n=10, bounds=(0, 0, 10, 10), v_max=1.5, dt=0.4):
        self.n, self.bounds, self.v_max, self.dt0 = n, bounds, v_max, dt
        self.pos = np.zeros((n, 2))
        self.vel = np.zeros((n, 2))
        self.arrived = 0

    def initialize(self, context, parameters, population, topology, rng):
        self.n = parameters.get("n", self.n)
        xmin, ymin, xmax, ymax = self.bounds
        self.pos = np.stack([rng.uniform(xmin + 0.5, xmax - 3, self.n),
                             rng.uniform(ymin + 0.5, ymax - 0.5, self.n)], axis=1)
        self.vel = np.zeros((self.n, 2))
        self.arrived = 0
        self.arrived_mask = np.zeros(self.n, bool)

    def _score_move(self, i, move):
        """OSM 效用：前进 − 排斥 − 动作代价。"""
        new = self.pos[i] + move
        xmin, ymin, xmax, ymax = self.bounds
        if not (xmin < new[0] < xmax and ymin < new[1] < ymax):
            return -1e9
        target = np.array([xmax - 0.3, ymax - 0.3])
        gain = -np.linalg.norm(target - new)
        cost_acc = 0.1 * np.linalg.norm(move - self.vel[i])
        repel = 0.0
        for j in range(self.n):
            if j == i or self.arrived_mask[j]:
                continue  # 已到达者被出口吸收，不再施力
            d = np.linalg.norm(new - self.pos[j])
            if d < 0.7:
                repel += 1.5 / max(d - 2 * R_PED, 0.08)
        return gain - cost_acc - repel

    def step(self, t, dt):
        target = np.array([self.bounds[2] - 0.3, self.bounds[3] - 0.3])
        for i in range(self.n):
            if self.arrived_mask[i]:
                continue
            if np.linalg.norm(target - self.pos[i]) < 0.35:
                self.arrived_mask[i] = True
                continue
            dirs = np.linspace(0, 2 * np.pi, 9, endpoint=False)
            best, bm = None, np.zeros(2)
            for a in dirs:
                for sp in (self.v_max * dt, self.v_max * dt * 0.5):
                    m = sp * np.array([np.cos(a), np.sin(a)])
                    s = self._score_move(i, m)
                    if best is None or s > best:
                        best, bm = s, m
            self.vel[i] = bm
            self.pos[i] = self.pos[i] + bm
        self.arrived = int(self.arrived_mask.sum())

    def observe(self):
        return {"arrived": self.arrived, "total": self.n}

    def validate_state(self):
        return []
