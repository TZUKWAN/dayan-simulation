"""传染病仓室家族引擎（NET051-073）：声明式仓室图 → ODE/随机。

一个通用 CompartmentEngine 覆盖 SI/SIS/SIR/SIRS/SEIR/SEIRS/SEIRD/SEIAR/
含出生死亡/疫苗等仓室模型族（NET051-062）。网络传播与随机过程单独类。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class CompartmentModel(DayanModel):
    """声明式仓室 ODE 引擎。

    spec 示例（SIR）：
      compartments: [S, I, R]
      init: {S: 995, I: 5, R: 0}
      params: {beta: 0.4, gamma: 0.1}
      transitions:                      # 速率表达式基于 compartments+params
        - {from: S, to: I, rate: "beta * S * I / N"}
        - {from: I, to: R, rate: "gamma * I"}
      conservation: ["S+I+R == N"]
    """

    model_id = "NET.compartment"
    clock_type = "ode"

    def __init__(self, spec: dict):
        self.spec = spec
        self.compartments = list(spec["compartments"])
        self.N_total = float(sum(float(v) for v in spec["init"].values()))
        self.params = dict(spec.get("params", {}))
        self.transitions = list(spec.get("transitions", []))
        self.x = np.array([float(spec["init"][c]) for c in self.compartments])

    def initialize(self, context, parameters, population, topology, rng):
        if parameters:
            self.params.update(parameters)
        init = self.spec["init"]
        self.x = np.array([float(init[c]) for c in self.compartments])
        if parameters.get("I0") is not None and "I" in self.compartments:
            idx = self.compartments.index("I")
            self.x[idx] = float(parameters["I0"])

    def _namespace(self, x) -> dict:
        ns = dict(self.params)
        ns["N"] = self.N_total
        ns.update(dict(zip(self.compartments, x)))
        return ns

    def derivatives(self, t, x) -> np.ndarray:
        with np.errstate(all="ignore"):
            ns = self._namespace(x)
            dx = np.zeros(len(self.compartments))
            for tr in self.transitions:
                rate = float(eval(tr["rate"], {"__builtins__": {}}, dict(ns)))
                f, to = tr.get("from"), tr.get("to")
                # from/to 为 null 表示外部出生源/死亡汇（vital dynamics）
                fi = self.compartments.index(f) if f in self.compartments else None
                ti = self.compartments.index(to) if to in self.compartments else None
                if fi is not None:
                    dx[fi] -= rate
                if ti is not None:
                    dx[ti] += rate
        return dx

    def observe(self) -> dict:
        return {c: round(float(self.x[i]), 4)
                for i, c in enumerate(self.compartments)}

    def validate_state(self) -> list[str]:
        errs = []
        for cons in self.spec.get("conservation", []):
            total = sum(self.x[self.compartments.index(c)]
                        for c in cons.split("+"))
            if abs(total - self.N_total) > 1e-6 * self.N_total:
                errs.append(f"守恒 {cons} 破坏")
        return errs


# ============ NET051-060 声明式规格工厂 ============
def spec_SI(N=1000, beta=0.4, I0=5):
    return {"compartments": ["S", "I"], "init": {"S": N - I0, "I": I0},
            "params": {"beta": beta, "N": N},
            "transitions": [{"from": "S", "to": "I",
                             "rate": "beta * S * I / N"}],
            "conservation": ["S+I"]}


def spec_SIS(N=1000, beta=0.4, gamma=0.2, I0=5):
    return {"compartments": ["S", "I"], "init": {"S": N - I0, "I": I0},
            "params": {"beta": beta, "gamma": gamma, "N": N},
            "transitions": [
                {"from": "S", "to": "I", "rate": "beta * S * I / N"},
                {"from": "I", "to": "S", "rate": "gamma * I"}],
            "conservation": ["S+I"]}


def spec_SIR(N=1000, beta=0.4, gamma=0.1, I0=5):
    return {"compartments": ["S", "I", "R"], "init": {"S": N - I0, "I": I0, "R": 0},
            "params": {"beta": beta, "gamma": gamma, "N": N},
            "transitions": [
                {"from": "S", "to": "I", "rate": "beta * S * I / N"},
                {"from": "I", "to": "R", "rate": "gamma * I"}],
            "conservation": ["S+I+R"]}


def spec_SIRS(N=1000, beta=0.4, gamma=0.1, xi=0.02, I0=5):
    return {"compartments": ["S", "I", "R"], "init": {"S": N - I0, "I": I0, "R": 0},
            "params": {"beta": beta, "gamma": gamma, "xi": xi, "N": N},
            "transitions": [
                {"from": "S", "to": "I", "rate": "beta * S * I / N"},
                {"from": "I", "to": "R", "rate": "gamma * I"},
                {"from": "R", "to": "S", "rate": "xi * R"}],
            "conservation": ["S+I+R"]}


def spec_SEIR(N=1000, beta=0.5, sigma=0.2, gamma=0.1, I0=5, E0=5):
    return {"compartments": ["S", "E", "I", "R"],
            "init": {"S": N - I0 - E0, "E": E0, "I": I0, "R": 0},
            "params": {"beta": beta, "sigma": sigma, "gamma": gamma, "N": N},
            "transitions": [
                {"from": "S", "to": "E", "rate": "beta * S * I / N"},
                {"from": "E", "to": "I", "rate": "sigma * E"},
                {"from": "I", "to": "R", "rate": "gamma * I"}],
            "conservation": ["S+E+I+R"]}


def spec_SEIRS(N=1000, beta=0.5, sigma=0.2, gamma=0.1, xi=0.01, I0=5, E0=5):
    sp = spec_SEIR(N, beta, sigma, gamma, I0, E0)
    sp["params"]["xi"] = xi
    sp["transitions"].append({"from": "R", "to": "S", "rate": "xi * R"})
    return sp


def spec_SEIRD(N=1000, beta=0.5, sigma=0.2, gamma=0.1, mu=0.01, I0=5, E0=5):
    sp = spec_SEIR(N, beta, sigma, gamma, I0, E0)
    sp["params"]["mu"] = mu
    sp["compartments"].append("D")
    sp["init"]["D"] = 0
    sp["conservation"] = ["S+E+I+R+D"]
    sp["transitions"].append({"from": "I", "to": "D", "rate": "mu * I"})
    return sp


def spec_SEIAR(N=1000, beta=0.5, sigma=0.2, gamma=0.1, rho_asym=0.4,
               I0=5, A0=5, E0=5):
    sp = {"compartments": ["S", "E", "I", "A", "R"],
          "init": {"S": N - I0 - A0 - E0, "E": E0, "I": I0, "A": A0, "R": 0},
          "params": {"beta": beta, "sigma": sigma, "gamma": gamma,
                      "rho": rho_asym, "N": N},
          "transitions": [
              # 无症状者同样排毒：感染力含 I+A（传播力 = I + A）
              {"from": "S", "to": "E", "rate": "beta * S * (I + A) / N"},
              # E 出流按 rho 分流：E→I 占 (1-rho)，E→A 占 rho（总出流恰为 sigma·E）
              {"from": "E", "to": "I", "rate": "(1 - rho) * sigma * E"},
              {"from": "E", "to": "A", "rate": "rho * sigma * E"},
              {"from": "I", "to": "R", "rate": "gamma * I"},
              {"from": "A", "to": "R", "rate": "gamma * A"}],
          "conservation": ["S+E+I+A+R"]}
    return sp


def spec_SIRV_vaccine(N=1000, beta=0.4, gamma=0.1, nu=0.01, ve=0.9,
                      vaccine_decay=0.005, I0=5, V0=100):
    """NET060 SEIRV：疫苗完全保护+衰减基线。"""
    V_protected = V0 * ve
    return {"compartments": ["S", "V", "I", "R"],
            "init": {"S": N - I0 - V_protected, "V": V_protected,
                     "I": I0, "R": 0},
            "params": {"beta": beta, "gamma": gamma, "nu": nu,
                        "vd": vaccine_decay, "N": N},
            "transitions": [
                {"from": "S", "to": "V", "rate": "nu * S"},
                {"from": "V", "to": "S", "rate": "vd * V"},
                {"from": "S", "to": "I", "rate": "beta * S * I / N"},
                {"from": "I", "to": "R", "rate": "gamma * I"}],
            "conservation": ["S+V+I+R"]}


def spec_SIR_vital(N=1000, beta=0.4, gamma=0.1, mu_birth=0.01, I0=5):
    """NET059 含出生死亡的 SIR：出生 μN 入 S，各仓室死亡率 μ（净零，总量守恒）。"""
    return {"compartments": ["S", "I", "R"], "init": {"S": N - I0, "I": I0, "R": 0},
            "params": {"beta": beta, "gamma": gamma, "mu": mu_birth, "N": N},
            "transitions": [
                {"from": None, "to": "S", "rate": "mu * N"},      # 出生入 S
                {"from": "S", "to": None, "rate": "mu * S"},      # 自然死亡
                {"from": "I", "to": None, "rate": "mu * I"},
                {"from": "R", "to": None, "rate": "mu * R"},
                {"from": "S", "to": "I", "rate": "beta * S * I / N"},
                {"from": "I", "to": "R", "rate": "gamma * I"}],
            "conservation": ["S+I+R"]}


class MetapopulationSIR(DayanModel):
    """NET062 元群体 SIR：多个城市，移 动传播（重力耦合）。"""

    model_id = "NET062"
    clock_type = "ode"

    def __init__(self, cities=4, N_per=500.0, beta=0.4, gamma=0.1,
                 mobility=0.001, I0=5):
        self.cities, self.N_per = cities, N_per
        self.beta, self.gamma, self.mobility = beta, gamma, mobility
        self.I0 = I0
        self.x = np.array([N_per - I0, I0, 0.0] * cities)  # [S,I,R]×C 交错
        self.N = N_per

    def initialize(self, context, parameters, population, topology, rng):
        # 此前仅有 __init__ 布局、无 initialize → 经统一入口必抛
        # NotImplementedError；补合同方法（参数生效 + 初态重建）
        self.cities = int(parameters.get("cities", self.cities))
        self.N = parameters.get("N_per", self.N_per)
        self.beta = parameters.get("beta", self.beta)
        self.gamma = parameters.get("gamma", self.gamma)
        self.mobility = parameters.get("mobility", self.mobility)
        self.I0 = parameters.get("I0", self.I0)
        self.x = np.array([self.N - self.I0, self.I0, 0.0] * self.cities)

    def derivatives(self, t, x):
        c = self.cities
        dx = np.zeros_like(x)
        for ci in range(c):
            S, I, R = x[3 * ci:3 * ci + 3]
            inf = self.beta * S * I / self.N
            dx[3 * ci] = -inf + self.mobility * sum(
                x[3 * cj] - S for cj in range(c) if cj != ci) / max(1, c - 1)
            dx[3 * ci + 1] = inf - self.gamma * I + self.mobility * sum(
                x[3 * cj + 1] - I for cj in range(c) if cj != ci) / max(1, c - 1)
            dx[3 * ci + 2] = self.gamma * I
        return dx

    def observe(self):
        c = self.cities
        return {f"city{i}_I": round(float(self.x[3 * i + 1]), 2)
                for i in range(c)}


# ============ 随机过程变体 ============
class GillespieSIR(DayanModel):
    """NET064 有限人口 Markov 随机 SIR（Gillespie 跳跃过程）。"""

    model_id = "NET064_jump"
    clock_type = "jump"

    def __init__(self, N=1000, beta=0.3, gamma=0.1, I0=5, seed=0):
        self.N, self.beta, self.gamma, self.I0 = N, beta, gamma, I0
        self.rng = np.random.default_rng(seed)
        self.S, self.I, self.R = N - I0, I0, 0

    def initialize(self, context, parameters, population, topology, rng):
        self.beta = parameters.get("beta", self.beta)
        self.gamma = parameters.get("gamma", self.gamma)

    def event_intensities(self, t) -> np.ndarray:
        inf = self.beta * self.S * self.I / self.N
        rec = self.gamma * self.I
        return np.array([inf, rec])

    def apply_jump(self, t, which):
        if which == 0:
            self.S -= 1
            self.I += 1
        else:
            self.I -= 1
            self.R += 1

    def observe(self):
        return {"S": self.S, "I": self.I, "R": self.R}

    def validate_state(self):
        errs = []
        if self.S + self.I + self.R != self.N:
            errs.append("人口守恒破坏")
        return errs


class ReedFrostChain:
    """NET065 Reed–Frost 链二项传播（离散世代）。"""

    model_id = "NET065"

    def __init__(self, n=500, p=0.02, seed=0, n_seed=3):
        self.n, self.p, self.seed = n, p, seed
        self.rng = np.random.default_rng(seed)
        self.susceptible = n - n_seed
        self.infected = n_seed
        self.generation_curve = [n_seed]

    def initialize(self, context, parameters, population, topology, rng):
        self.susceptible = self.n - 3
        self.infected = 3
        self.generation_curve = [3]

    def step(self, t, dt):
        """一代：每个感染者以 p 感染每个易感者。"""
        if self.infected <= 0 or self.susceptible <= 0:
            return
        new_inf = 0
        for _ in range(self.infected):
            contacts = int(self.rng.integers(0, self.susceptible + 1))
            new_inf += int(self.rng.binomial(contacts, self.p))
        self.susceptible -= new_inf
        self.infected = new_inf
        self.generation_curve.append(new_inf)

    def observe(self):
        return {"infected_gen": self.infected,
                "susceptible": self.susceptible,
                "gen_curve": self.generation_curve[-5:]}

    def validate_state(self):
        return []


class BranchingProcess:
    """NET073 负二项后代疫情分支模型：灭绝/爆发分支判定。"""

    model_id = "NET073"

    def __init__(self, R0=1.5, dispersion=0.5, n0=3, seed=0):
        self.R0, self.k, self.n0, self.seed = R0, dispersion, n0, seed
        self.rng = np.random.default_rng(seed)
        self.alive = n0
        self.extinct = False

    def initialize(self, context, parameters, population, topology, rng):
        self.R0 = parameters.get("R0", self.R0)
        self.alive = parameters.get("n0", 3)
        self.extinct = self.alive == 0

    def step(self, t, dt):
        if self.extinct or self.alive <= 0:
            return
        # 负二项后代分布（方差超泊松）
        mean = self.R0
        p = self.k / (self.k + mean)
        offspring = int(self.rng.negative_binomial(self.k, p))
        self.alive = offspring
        if self.alive == 0:
            self.extinct = True

    def observe(self):
        return {"alive": self.alive, "extinct": self.extinct}

    def validate_state(self):
        return []
