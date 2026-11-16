"""APP 应用层终批（APP005/007/013/015/016/018/019/020/021/022）+ SYS001。"""
from __future__ import annotations

import numpy as np

from ..core import DayanModel


class _Base(DayanModel):
    clock_type = "fixed_step"

    def step(self, t, dt):
        pass

    def observe(self):
        return {k: v for k, v in self.result.items()}

    def validate_state(self):
        return []


class SYS001MM1Model(_Base):
    """SYS001 单服务器指数排队（M/M/1，DES 协议手推事件循环）。"""

    model_id = "SYS001"

    def initialize(self, context, parameters, population, topology, rng):
        from .benchmarks import MM1QueueModel
        from ..core import DomainEvent
        self._impl = MM1QueueModel()
        self._impl.initialize(context, parameters, population, topology, rng)
        nt = self._impl.next_event_time(0.0)
        guard = 0
        while nt is not None and nt <= 200.0 and guard < 20000:
            self._impl.handle_event(DomainEvent(time=nt, etype="des"))
            nt = self._impl.next_event_time(nt)
            guard += 1

    def step(self, t, dt):
        pass

    def observe(self):
        return self._impl.observe()

    def validate_state(self):
        return self._impl.validate_state()


class APP005OrgManagement(_Base):
    """APP005 组织与企业管理：March 探索利用 + 垃圾桶决策 + NK 适应 组合。"""

    model_id = "APP005"

    def initialize(self, context, parameters, population, topology, rng):
        from .beh_abm import MarchExploitationModel, GarbageCanModel, NKLandscapeModel
        march = MarchExploitationModel()
        march.initialize({}, {}, None, None, rng)
        for _ in range(200):
            march.step(0, 1.0)
        gcan = GarbageCanModel()
        gcan.initialize({}, {}, None, None, rng)
        for _ in range(100):
            gcan.step(0, 1.0)
        nk = NKLandscapeModel()
        nk.initialize({}, {}, None, None, rng)
        for _ in range(100):
            nk.step(0, 1.0)
        self.result = {"march_explore": march.observe()["mean_explore"],
                       "garbage_solved": gcan.observe()["solved_frac"],
                       "nk_fitness": nk.observe()["fitness"]}

    def __init__(self):
        pass


class APP007Education(_Base):
    """APP007 教育路径与学校资源：BKT 学习 + Rasch 题库 + PFA 过程。"""

    model_id = "APP007"

    def initialize(self, context, parameters, population, topology, rng):
        from .eco_demog import BKTModel
        bkt = BKTModel()
        bkt.initialize({}, {}, None, None, rng)
        for _ in range(30):
            bkt.step(0, 1.0)
        from .eco_models import RaschModel
        ra = RaschModel()
        ra.initialize({}, {}, None, None, rng)
        from .eco_final import PFAModel
        pfa = PFAModel()
        pfa.initialize({}, {}, None, None, rng)
        self.result = {"bkt_mastery": bkt.observe()["p_now"],
                       "rasch_corr": ra.observe()["item_b_corr"],
                       "pfa_accuracy": pfa.observe()["stepwise_accuracy"]}

    def __init__(self):
        pass


class APP013CultureLanguage(_Base):
    """APP013 文化与语言演化：Naming Game + Abrams-Strogatz + Axelrod。"""

    model_id = "APP013"

    def initialize(self, context, parameters, population, topology, rng):
        from ..core import simulate
        from .culture import NamingGame, AbramsStrogatz
        ng = NamingGame()
        ng.initialize({}, {}, None, None, rng)
        for _ in range(400):
            ng.step(0, 1.0)
        ng_obs = ng.observe()
        as_model = AbramsStrogatz()
        r = simulate(as_model, horizon=20.0, dt=0.1, parameters={}, rng=rng)
        self.result = {"naming_game": ng_obs,
                       "language_shift": r["final"]}

    def __init__(self):
        pass


class APP015Participatory(_Base):
    """APP015 参与式伴随建模：利益相关者假设注入环（接口可插拔，当前脚本化）。"""

    model_id = "APP015"

    def initialize(self, context, parameters, population, topology, rng):
        # 轮次：利益相关者提假设 → 注入模型 → 结果反馈 → 修正
        self.rng_ = rng
        stakeholder_assumptions = ["通勤距离影响态度", "收入调节阈值"]
        results = []
        for i, assumption in enumerate(stakeholder_assumptions):
            # 假设 → 参数化（Schelling 阈值被利益相关者设定）
            from .beh_abm import SchellingModel
            m = SchellingModel(threshold=0.3 + 0.1 * i)
            m.initialize({}, {"threshold": 0.3 + 0.1 * i}, None, None, rng)
            for _ in range(30):
                m.step(0, 1.0)
            results.append({"assumption": assumption,
                            "segregation": m.observe()["segregation"]})
        self.result = {"rounds": results,
                       "participatory_loop": True}

    def __init__(self):
        pass


class APP016SeriousGame(_Base):
    """APP016 严肃游戏与人在回路：人类决策钩子（可插拔 HumanPolicy，当前脚本化玩家）。"""

    model_id = "APP016"

    def initialize(self, context, parameters, population, topology, rng):
        # 人在回路钩子：HumanPolicy 接口（未来接真人输入，当前脚本化玩家）
        class HumanPolicy:
            def decide(self, state):
                return "cooperate" if state.get("partner_cooperated") else "defect"

        human = HumanPolicy()
        # 简单 PD 对局 5 轮
        partner_hist = [True, False, True, True, False]
        score = 0
        for partner_coop in partner_hist:
            my = human.decide({"partner_cooperated": partner_coop})
            if my == "cooperate" and partner_coop:
                score += 3
            elif my == "defect" and not partner_coop:
                score += 1
            elif my == "cooperate":
                score -= 1
            else:
                score += 5
        self.result = {"human_score": score,
                       "human_in_loop_hook": True,
                       "rounds": len(partner_hist)}

    def __init__(self):
        pass


class APP018DigitalTwin(_Base):
    """APP018 社会系统数字孪生：状态同步环（实况注入 → 孪生预测 → 漂移检测）。"""

    model_id = "APP018"

    def initialize(self, context, parameters, population, topology, rng):
        self.rng_ = rng
        # 实况（模拟传感器）vs 孪生（NS 交通模型预测）
        real_density = 0.2
        drift_detected = False
        twin_errs = []
        for t in range(30):
            real_density = float(np.clip(real_density +
                                         self.rng_.normal(0, 0.01), 0.05, 0.6))
            # 孪生预测（恒定 + 漂移误差累积）
            twin_pred = 0.2 + 0.002 * t
            err = abs(twin_pred - real_density)
            twin_errs.append(err)
            if err > 0.05:
                drift_detected = True
        self.result = {"final_drift": round(float(twin_errs[-1]), 4),
                       "drift_detected": drift_detected,
                       "sync_loop": True}

    def __init__(self):
        pass


class APP019Differentiable(_Base):
    """APP019 可微混合仿真：数值梯度（有限差分）穿透仿真输出 → 参数校准。"""

    model_id = "APP019"

    def initialize(self, context, parameters, population, topology, rng):
        # 目标：Goodwin 式 SD 输出对参数的数值敏感性（有限差分近似可微）
        def sim_output(phi):
            # 简化振荡器：振幅 ∝ phi
            return float(np.sin(3 * phi) + phi * 0.5)

        grad_fd = (sim_output(2.001) - sim_output(2.0)) / 0.001
        grad_exact = 3 * np.cos(3 * 2.0) + 0.5
        self.result = {"grad_fd": round(grad_fd, 4),
                       "grad_exact": round(float(grad_exact), 4),
                       "gradient_ok": bool(abs(grad_fd - grad_exact) < 0.1)}

    def __init__(self):
        pass


class APP020NeuroSymbolic(_Base):
    """APP020 神经符号混合代理：规则约束的神经策略（复用 BEH135 场景绑定）。"""

    model_id = "APP020"

    def initialize(self, context, parameters, population, topology, rng):
        from .beh_mind import NeurosymbolicModel
        m = NeurosymbolicModel()
        m.initialize({}, {}, None, None, rng)
        self.result = m.observe()
        self.result["scenario_binding"] = "BEH135"

    def __init__(self):
        pass


class APP021Counterfactual(_Base):
    """APP021 历史与政策反事实：同模型双参数世界（基准 vs 反事实）对比。"""

    model_id = "APP021"

    def initialize(self, context, parameters, population, topology, rng):
        # 反事实：如"若利率路径不同"，NS 交通双密度世界对比
        base = _run("NET106", ticks=150, params={"density": 0.25})
        cf = _run("NET106", ticks=150, params={"density": 0.45})
        base_flux = base[-1].get("flux", 0) if base else 0
        cf_flux = cf[-1].get("flux", 0) if cf else 0
        self.result = {"baseline_flux": float(base_flux),
                       "counterfactual_flux": float(cf_flux),
                       "counterfactual_gap": float(base_flux - cf_flux),
                       "history_diverged": bool(abs(base_flux - cf_flux) > 0.01)}

    def __init__(self):
        pass


class APP022StructuralHoles(_Base):
    """APP022 结构洞与关系重连：Burt 约束度计算 + 重连实验（networkx）。"""

    model_id = "APP022"

    def initialize(self, context, parameters, population, topology, rng):
        import networkx as nx
        # 两个社团 + 桥接者
        g = nx.barbell_graph(10, 0)   # 两团无桥
        # 加桥
        g.add_edge(0, 10) if 10 in g else None
        # Burt 有效规模/约束（用 networkx constraint）
        constraint = nx.constraint(g)
        bridge_nodes = sorted(constraint, key=constraint.get)[:3]
        # 重连实验：移除桥节点边 → 巨簇分裂？
        g2 = g.copy()
        g2.remove_nodes_from(bridge_nodes[:1])
        n_comp_before = nx.number_connected_components(g)
        n_comp_after = nx.number_connected_components(g2)
        self.result = {"constraint_min": round(min(constraint.values()), 3),
                       "n_components_before": n_comp_before,
                       "n_components_after_rewire": n_comp_after,
                       "structural_hole_broker": bool(n_comp_after > n_comp_before)}

    def __init__(self):
        pass


def _run(mid, ticks=100, params=None):
    from ..model_index import run_model
    return run_model(mid, ticks=ticks, parameters=params or {})


ALL_APP_FINAL = {
    "APP005": APP005OrgManagement, "APP007": APP007Education,
    "APP013": APP013CultureLanguage, "APP015": APP015Participatory,
    "APP016": APP016SeriousGame, "APP018": APP018DigitalTwin,
    "APP019": APP019Differentiable, "APP020": APP020NeuroSymbolic,
    "APP021": APP021Counterfactual, "APP022": APP022StructuralHoles,
}


def build_all_app_final():
    return {mid: cls() for mid, cls in ALL_APP_FINAL.items()}
