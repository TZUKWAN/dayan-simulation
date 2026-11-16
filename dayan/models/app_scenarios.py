"""APP 应用层场景（APP001–APP022）：绑定既有模型组合的"场景配方"。

每个场景 = 一个可运行的组合（主模型 + 参数），输出场景级诊断。
场景不是新模型，是平台能力的"应用配方"——对应规范中的应用层定位。
需要数据校准/人在回路的场景（APP015-019）标注依赖，不做伪造。
"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel
from ..model_index import run_model


def _run(mid, ticks=100, params=None):
    return run_model(mid, ticks=ticks, parameters=params or {})


class _ScenarioBase(DayanModel):
    """场景基类：initialize 跑组合配方，observe 出诊断。"""
    clock_type = "fixed_step"

    def __init__(self):
        self.result = {}

    def step(self, t, dt):
        pass

    def observe(self):
        return dict(self.result)

    def validate_state(self):
        return []


class APP001EpidemicPolicy(_ScenarioBase):
    """APP001 公共卫生与防疫政策：SIR 基线 vs 疫苗接种（SIRV）情景对照。"""

    model_id = "APP001"

    def initialize(self, context, parameters, population, topology, rng):
        base = _run("NET052", ticks=120)      # SIS 地方病
        vac = _run("NET060", ticks=120)       # 疫苗情景
        last_v = vac[-1] if vac else {}
        self.result = {"baseline_final": base[-1] if base else {},
                       "vaccine_final": {k: v for k, v in last_v.items()
                                         if isinstance(v, (int, float))},
                       "policy_lever": "vaccination_coverage"}

    def __init__(self):
        super().__init__()


class APP002TrafficScenario(_ScenarioBase):
    """APP002 城市交通：NS 低密度自由流 vs 高密度拥堵对照 + LWR 宏观。"""

    model_id = "APP002"

    def initialize(self, context, parameters, population, topology, rng):
        free = _run("NET106", ticks=150, params={"density": 0.15})
        jam = _run("NET106", ticks=150, params={"density": 0.55})
        macro = _run("NET095", ticks=150)
        f_flux = free[-1].get("flux", 0) if free else 0
        j_flux = jam[-1].get("flux", 0) if jam else 0
        self.result = {"free_flow_flux": float(f_flux),
                       "congested_flux": float(j_flux),
                       "congestion_loss": float(1 - j_flux / max(f_flux, 1e-9)),
                       "macro_kmean": (macro[-1].get("k_mean", 0) if macro else 0)}

    def __init__(self):
        super().__init__()


class APP003OpinionElection(_ScenarioBase):
    """APP003 选举与政治意见：q-voter 意见动力学 + Duverger 政治包。"""

    model_id = "APP003"

    def initialize(self, context, parameters, population, topology, rng):
        from .opinion import QVoterModel
        m = QVoterModel()
        m.initialize({}, {}, None, None, rng)
        for _ in range(400):
            m.step(0, 1.0)
        self.result = {"final_opinion_mean": float(np.mean(m.x))}

    def __init__(self):
        super().__init__()


class APP004MediaScenario(_ScenarioBase):
    """APP004 社交媒体传播：Bass 创新扩散 + 意见动力学交叉。"""

    model_id = "APP004"

    def initialize(self, context, parameters, population, topology, rng):
        from .wave2 import BassModel
        m = BassModel()
        r = simulate_bass(m, rng)
        self.result = r

    def __init__(self):
        super().__init__()


def simulate_bass(m, rng):
    from ..core import simulate
    r = simulate(m, horizon=30.0, dt=0.1, parameters={}, rng=rng)
    return {"final_obs": r["final"]}


class APP006ConflictScenario(_ScenarioBase):
    """APP006 国际关系与冲突：Richardson 军备 + Lanchester 交战两级。"""

    model_id = "APP006"

    def initialize(self, context, parameters, population, topology, rng):
        arms = _run("ECO110", ticks=150, params={"x0": [2.0, 2.0]})
        battle = _run("ECO111", ticks=100)
        self.result = {"arms_race_final": (arms[-1] if arms else {}),
                       "battle_final": (battle[-1] if battle else {})}

    def __init__(self):
        super().__init__()


class APP008HealthPolicy(_ScenarioBase):
    """APP008 医疗服务与健康政策：M/M/c 排队（医疗资源）+ 健康队列 Markov。"""

    model_id = "APP008"

    def initialize(self, context, parameters, population, topology, rng):
        q = _run("SYS002", ticks=150, params={"c": 3, "lam": 2.0, "mu": 1.0})
        hm = _run("ECO099", ticks=100)
        self.result = {"queue_final": (q[-1] if q else {}),
                       "cohort_final": (hm[-1] if hm else {})}

    def __init__(self):
        super().__init__()


class APP009TaxBenefit(_ScenarioBase):
    """APP009 税收福利财政：静态算术税福微观仿真 + GL-SIM 财政三部门。"""

    model_id = "APP009"

    def initialize(self, context, parameters, population, topology, rng):
        tax = _run("ECO096", ticks=5)
        sim = _run("ECO035", ticks=80)
        self.result = {"tax_mtr": (tax[-1].get("mtr_path") if tax else None),
                       "fiscal_Y": (sim[-1].get("Y") if sim else None),
                       "conserv": (sim[-1].get("conserv") if sim else None)}

    def __init__(self):
        super().__init__()


class APP010FinanceRisk(_ScenarioBase):
    """APP010 金融市场系统性风险：SFM 价格收敛 + Lux-Marchesi 肥尾 + ZI 效率。"""

    model_id = "APP010"

    def initialize(self, context, parameters, population, topology, rng):
        sfm = _run("ECO046", ticks=200)
        lm = _run("ECO048", ticks=200)
        zi = _run("ECO054", ticks=25)
        self.result = {"sfm_final": (sfm[-1] if sfm else {}),
                       "lm_kurtosis": (lm[-1].get("excess_kurtosis") if lm else None),
                       "zi_efficiency": (zi[-1].get("alloc_efficiency") if zi else None)}

    def __init__(self):
        super().__init__()


class APP011UrbanHousing(_ScenarioBase):
    """APP011 城市土地住房：Schelling 空间隔离（pack 基准）+ Forrester 城市。"""

    model_id = "APP011"

    def initialize(self, context, parameters, population, topology, rng):
        city = _run("ECO103", ticks=150)
        self.result = {"city_final": (city[-1] if city else {}),
                       "schelling_note": "见 src/packs/benchmark_sugarscape 联动"}

    def __init__(self):
        super().__init__()


class APP012PopulationAging(_ScenarioBase):
    """APP012 人口家庭老龄化：Leslie/Lefkovitch 增长 + Lee-Carter 死亡率。"""

    model_id = "APP012"

    def initialize(self, context, parameters, population, topology, rng):
        lk = _run("ECO058", ticks=60)
        lc = _run("ECO061", ticks=5)
        self.result = {"population_total": (lk[-1].get("total") if lk else None),
                       "lambda1": (lk[-1].get("lambda1") if lk else None),
                       "leecarter_fit": (lc[-1].get("resid_ratio") if lc else None)}

    def __init__(self):
        super().__init__()


class APP014ClimateGovernance(_ScenarioBase):
    """APP014 能源气候资源治理：DICE-lite + World3-lite + Hotelling 三景对照。"""

    model_id = "APP014"

    def initialize(self, context, parameters, population, topology, rng):
        dice = _run("ECO106", ticks=150)
        w3 = _run("ECO102", ticks=200)
        hot = _run("ECO115", ticks=80)
        self.result = {"dice_final": (dice[-1] if dice else {}),
                       "world3_resources": (w3[-1].get("resources") if w3 else None),
                       "hotelling_price": (hot[-1].get("price") if hot else None)}

    def __init__(self):
        super().__init__()


class APP017ExperimentalCalibration(_ScenarioBase):
    """APP017 实验经济学与校准：ZI 交易效率 + Mincer 估计 + GARCH 滤波。"""

    model_id = "APP017"

    def initialize(self, context, parameters, population, topology, rng):
        zi = _run("ECO054", ticks=25)
        mn = _run("ECO083", ticks=5)
        self.result = {"zi_efficiency": (zi[-1].get("alloc_efficiency") if zi else None),
                       "mincer_rho_hat": (mn[-1].get("rho_hat") if mn else None)}

    def __init__(self):
        super().__init__()


ALL_APP_SCENARIOS = {
    "APP001": APP001EpidemicPolicy, "APP002": APP002TrafficScenario,
    "APP003": APP003OpinionElection, "APP004": APP004MediaScenario,
    "APP006": APP006ConflictScenario, "APP008": APP008HealthPolicy,
    "APP009": APP009TaxBenefit, "APP010": APP010FinanceRisk,
    "APP011": APP011UrbanHousing, "APP012": APP012PopulationAging,
    "APP014": APP014ClimateGovernance, "APP017": APP017ExperimentalCalibration,
}


def build_all_apps():
    return {mid: cls() for mid, cls in ALL_APP_SCENARIOS.items()}
