"""DAYAN 旗舰耦合器（设计 v3 R7-e）：范式间 CoupledSimulation。

三模式：
- one-way : SD 核（Goodwin 工资份额-就业周期）单向驱动微观 ABM（初始工资）
- cyclic  : ABM 就业率反馈 SD 需求项（双向闭环）
- reference : 共享种子/时钟的对照组（验证耦合本身不破坏各自动态）

核心思想（三主权）：引擎管状态（SD 求解与 ABM 状态各自守恒），
耦合只经"语义接口"传标量（工资水平、就业率），LLM/理论不进内核。
"""
from __future__ import annotations

import numpy as np


class GoodwinSDCore:
    """Goodwin 增长周期（Goodwin 1967 线性形式，RK4）：
    ẇ/ω = −a + b·λ（就业→工资增长的线性菲利普斯关系）
    λ̇ = λ((1−ω)/ν − δ)（利润份额→就业，资本系数 ν、折旧 δ）。
    Lotka–Volterra 型闭轨道：ω 与 λ 反相摆动；
    ω 上界=利润挤压（工资份额→1），λ 下界=投资崩溃——经典有界机制。"""

    def __init__(self, nu=2.5, delta=0.03, a=0.045, b=0.06,
                 x0=(0.68, 0.9)):
        self.nu, self.delta, self.a, self.b = nu, delta, a, b
        self.x = np.array(x0, float)

    def derivatives(self, x):
        w, lmb = np.maximum(x, 1e-9)
        profit_share = 1 - w
        dw = w * (-self.a + self.b * lmb)
        dl = lmb * ((profit_share / self.nu) - self.delta)
        return np.array([dw, dl])

    def step(self, dt):
        x = self.x
        k1 = self.derivatives(x)
        k2 = self.derivatives(x + dt / 2 * k1)
        k3 = self.derivatives(x + dt / 2 * k2)
        k4 = self.derivatives(x + dt * k3)
        self.x = x + dt / 6 * (k1 + 2 * k2 + 2 * k3 + k4)
        self.x = np.clip(self.x, 0.02, 0.999)


class MicroABMSector:
    """微观就业 ABM：N 个异质个体，工资吸引力 → 采纳就业的概率；
    state: 就业人数、平均保留工资。耦合接口：set_wage_level(w)、
    get_employment_rate()。"""

    def __init__(self, n=200, seed=0):
        self.rng = np.random.default_rng(seed)
        self.n = n
        self.employed = np.zeros(n, bool)
        self.reservation = self.rng.uniform(0.4, 0.95, n)
        self.wage = 0.7

    def set_wage_level(self, w):
        self.wage = float(np.clip(w, 0.1, 1.5))

    def step(self):
        p_join = np.clip((self.wage - self.reservation) / 0.3, 0, 0.6)
        p_leave = np.clip((self.reservation - self.wage) / 0.5, 0, 0.3)
        for i in range(self.n):
            if not self.employed[i] and self.rng.random() < p_join[i]:
                self.employed[i] = True
            elif self.employed[i] and self.rng.random() < p_leave[i]:
                self.employed[i] = False

    def get_employment_rate(self):
        return float(self.employed.mean())

    def money(self):
        """总量守恒检验口径：就业者获得工资计数（虚拟账户）。"""
        return float(self.employed.sum() * self.wage)


class CoupledSimulation:
    """范式耦合器：Goodwin SD 核 × 微观 ABM，三模式。"""

    def __init__(self, mode="one-way", n_micro=200, seed=0, T=200.0, dt=0.1):
        assert mode in ("one-way", "cyclic", "reference")
        self.mode = mode
        self.sd = GoodwinSDCore()
        self.abm = MicroABMSector(n=n_micro, seed=seed)
        self.T, self.dt = T, dt
        self.history = []
        self.rng = np.random.default_rng(seed)

    def run(self):
        n_steps = int(self.T / self.dt)
        for k in range(n_steps):
            w_sd = float(self.sd.x[0])
            lmb_sd = float(self.sd.x[1])
            # 映射修正（审计 2026-11-14）：工资份额 ω∈[0,1] ≠ 工资水平。
            # 就业率 λ 才是劳动力市场紧张的度量——高λ→企业加薪竞争→ABM工资感知高。
            # wage_level = baseline * λ（基准=0.7，λ归一到[0,1]→level≈[0,0.7]范围）
            # 旧实现直接传 ω=0.9→ABM 认为工资很高→200人全就业，异质性失效。
            wage_level = 0.7 * lmb_sd    # λ∈[0.6,0.95] → level∈[0.42,0.67]
            if self.mode == "one-way":
                self.abm.set_wage_level(wage_level)
            elif self.mode == "cyclic":
                self.abm.set_wage_level(wage_level)
                # ABM 就业率反馈 SD（双向）：就业率差→投资扰动
                lmb_abm = self.abm.get_employment_rate()
                self._feedback = float(np.clip(0.05 * (lmb_abm - lmb_sd), -0.01, 0.01))
            else:  # reference：无耦合，各自演化（同种子）
                pass
            self.sd.x[1] = float(np.clip(
                self.sd.x[1] + self.dt * getattr(self, '_feedback', 0.0),
                0.05, 0.95))
            self.sd.step(self.dt)
            self.abm.step()
            if k % max(1, n_steps // 500) == 0 or k == n_steps - 1:
                self.history.append({
                    "t": k * self.dt,
                    "wage_share": w_sd,
                    "employment_sd": lmb_sd,
                    "employment_abm": self.abm.get_employment_rate(),
                })
        return self.summary()

    def summary(self):
        arr = np.array([h["wage_share"] for h in self.history])
        emp_sd = np.array([h["employment_sd"] for h in self.history])
        emp_abm = np.array([h["employment_abm"] for h in self.history])
        # Goodwin 闭轨道检验：工资份额范围应有界振荡（非发散）
        w_range = float(arr.max() - arr.min())
        return {
            "mode": self.mode,
            "wage_share_range": w_range,
            "wage_share_final": float(arr[-1]),
            "emp_sd_final": float(emp_sd[-1]),
            "emp_abm_final": float(emp_abm[-1]),
            "sd_bounded": bool(w_range < 0.6 and 0.02 < arr[-1] < 0.98),
            "abm_active": bool(emp_abm.max() > 0 and emp_abm.min() < 1),
            "corr_sd_abm": float(np.corrcoef(emp_sd[10:], emp_abm[10:])[0, 1])
            if len(emp_sd) > 20 else 0.0,
        }
