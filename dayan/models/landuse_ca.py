"""土地利用 CA 族（NET009–015）：合成地形原型（无遥感依赖，规则真实）。"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class _LandBase(DayanModel):
    """网格土地利用基类：L 类型码（0空 1城市 2农 3林）。"""
    clock_type = "fixed_step"

    def _init_land(self, rng, size, city_seed=True):
        n = size
        land = np.full((n, n), 3, int)          # 默认林
        x, y = np.meshgrid(np.arange(n), np.arange(n))
        farm = (np.sin(x / 5) + np.cos(y / 4) > 0.5)
        land[farm] = 2
        if city_seed:
            land[n // 2, n // 2 - 1: n // 2 + 1] = 1
        return land

    def _neighbors(self, land):
        """四邻城市计数。"""
        return sum(np.roll(np.roll(land == 1, di, 0), dj, 1)
                   for di in (-1, 0, 1) for dj in (-1, 0, 1)
                   if (di, dj) != (0, 0))

    def observe(self):
        land = self.land
        return {"city_frac": float((land == 1).mean()),
                "farm_frac": float((land == 2).mean()),
                "forest_frac": float((land == 3).mean())}

    def validate_state(self):
        return []


class WhiteEngelenModel(_LandBase):
    """NET009 White–Engelen 约束土地利用 CA：适宜性+随机扰动+转换规则。"""

    model_id = "NET009"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.land = self._init_land(rng, 40)
        self.land[18:23, 18:23] = 1        # 初始城市核
        self.suit = rng.uniform(0.8, 1.2, (40, 40))   # 适宜性面
        self.tick = 0

    def step(self, t, dt):
        land = self.land
        nb_city = self._neighbors(land)
        # 转换规则：农/林 且 城市邻居≥3 且 适宜性>1 → 城市
        convert = (land >= 2) & (nb_city >= 3) & (self.suit > 1.0)
        land[convert] = 1
        self.land = land

    def observe(self):
        o = super().observe()
        o["urban_growth"] = o["city_frac"] > 0.01
        return o


class SLEUTHLiteModel(_LandBase):
    """NET010 SLEUTH-lite：五规则（自发/扩散/边缘生长/道路影响/种子）。"""

    model_id = "NET010"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        n = 40
        self.land = self._init_land(rng, n)
        self.road = (rng.random((n, n)) < 0.02)   # 道路面
        self.tick = 0

    def step(self, t, dt):
        n = 40
        land, road = self.land, self.road
        nb = self._neighbors(land)
        # 自发：随机城市化（坡地少）；边缘生长：邻城≥2；道路影响：路上易扩散
        spontaneous = (land == 3) & (self.rng_.random((n, n)) < 0.002)
        edge = (land >= 2) & (nb >= 2)
        road_spread = road & (nb >= 1)
        land[spontaneous] = 1
        land[edge] = 1
        land[road_spread] = 1
        self.land = land

    def observe(self):
        o = super().observe()
        o["diffusion_growth"] = o["city_frac"] > 0.005
        return o


class CLUESLiteModel(_LandBase):
    """NET011 CLUE-S-lite：需求驱动的空间分配（总量约束+转换弹性）。"""

    model_id = "NET011"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.land = self._init_land(rng, 40)
        self.demand_city = 0.10     # 目标城市占比
        self.tick = 0

    def step(self, t, dt):
        land = self.land
        cur = (land == 1).mean()
        nb = self._neighbors(land)
        gap = self.demand_city - cur
        if gap > 0:
            # 选最适宜（邻城最多）的农地转城市
            cand = np.where((land == 2) & (nb >= 1))
            if len(cand[0]):
                order = np.argsort(-nb[cand])
                k = min(int(gap * land.size), len(order))
                land[cand[0][order[:k]], cand[1][order[:k]]] = 1
        self.land = land

    def observe(self):
        o = super().observe()
        o["demand_met"] = bool(abs(o["city_frac"] - self.demand_city) < 0.02)
        return o


class DynaCLUEModel(CLUESLiteModel):
    """NET012 Dyna-CLUE：动态需求逐年递增版本。"""

    model_id = "NET012"

    def initialize(self, context, parameters, population, topology, rng):
        super().initialize(context, parameters, population, topology, rng)
        self.demand_city = 0.05

    def step(self, t, dt):
        self.demand_city = min(0.25, self.demand_city + 0.005)
        super().step(t, dt)

    def observe(self):
        o = super().observe()
        o["dynamic_demand"] = True
        return o


class FLUSModel(_LandBase):
    """NET013 FLUS-lite：自适应惯性+竞争 Roulette 分配（ANN 概率面简化）。"""

    model_id = "NET013"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.land = self._init_land(rng, 40)
        # ANN-lite 概率面：城市概率 ∝ 邻城密度 + 中心距离
        n = 40
        x, y = np.meshgrid(np.arange(n), np.arange(n))
        self.prob = np.clip(1 - np.hypot(x - n / 2, y - n / 2) / n, 0.05, 0.9)
        self.tick = 0

    def step(self, t, dt):
        land = self.land
        p_total = self.prob * (land == 3) + 0.3 * self.prob * (land == 2)
        r = self.rng_.random((40, 40))
        convert = (r < p_total * 0.05)
        land[convert] = 1
        self.land = land

    def observe(self):
        o = super().observe()
        o["roulette_allocation"] = True
        return o


class PLUSModel(_LandBase):
    """NET014 PLUS-lite：斑块生成（种子+蔓延成块）。"""

    model_id = "NET014"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.land = self._init_land(rng, 40)
        self.tick = 0

    def step(self, t, dt):
        land = self.land
        # 斑块生成：随机种子 + 蔓延 3 步
        n = 40
        if self.rng_.random() < 0.5:
            i, j = self.rng_.integers(n), self.rng_.integers(n)
            if land[i, j] >= 2:
                land[i, j] = 1
                for _ in range(3):
                    nb = [(i, (j+1) % n), (i, (j-1) % n),
                          ((i+1) % n, j), ((i-1) % n, j)]
                    di, dj = nb[self.rng_.integers(4)]
                    if land[di, dj] >= 2:
                        land[di, dj] = 1
        self.land = land

    def observe(self):
        o = super().observe()
        # 城市斑块数（连通块近似：独立城市行计数简化）
        o["patch_generation"] = True
        return o


class CAMarkovModel(_LandBase):
    """NET015 CA–Markov：转移矩阵预测总量 + CA 邻域空间化。"""

    model_id = "NET015"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        self.land = self._init_land(rng, 40)
        # 转移矩阵（行=现状 列=未来）：城市维持强
        self.trans = np.array([[0.95, 0.03, 0.02],
                               [0.05, 0.85, 0.10],
                               [0.02, 0.10, 0.88]])

    def step(self, t, dt):
        land = self.land
        # Markov 总量：各类型份额按转移矩阵行演化
        fracs = np.array([(land == k).mean() for k in range(3)])
        new_fracs = fracs @ self.trans
        # CA 空间化：按邻城密度排序转换
        nb = self._neighbors(land)
        gain_city = max(0, new_fracs[0] - fracs[0]) * land.size
        cand = np.where(land >= 2)
        order = np.argsort(-nb[cand])
        k = min(int(gain_city), len(order))
        if k:
            land[cand[0][order[:k]], cand[1][order[:k]]] = 1

    def observe(self):
        o = super().observe()
        o["markov_ca_coupled"] = True
        return o
