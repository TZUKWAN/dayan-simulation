"""Three-party green subsidy audit game on a periodic CA/ABM lattice."""

from collections import deque

import numpy as np

from ..core import DayanModel
from ..lattice import imitate_best, periodic_neighbors


PAPER_URL = "https://xbbjb.nau.edu.cn/sjyjjyj/article/pdf/20260205006"
LAYER_DEFINITIONS = (
    ("audit", "审计覆盖", ("未审计", "审计")),
    ("regulator", "基层监管", ("松懈", "积极监管")),
    ("farm", "农业主体", ("绿色欺诈", "绿色生产")),
)


def _spec(default, low, high, description, choices=None):
    return {
        "default": default, "type": "integer" if type(default) is int else "number",
        "required": False, "minimum": low, "maximum": high, "description": description,
        **({"enum": list(choices)} if choices else {}),
    }


class GreenSubsidyAuditGame(DayanModel):
    model_id = "NET122"
    fixed_dt = 1.0
    time_unit = "蒙特卡洛步（MCS）"
    parameter_schema = {
        "grid_side": _spec(100, 3, 128, "周期网格边长，每格一户与一名监管员"),
        "neighbors": _spec(4, 4, 8, "4 冯·诺依曼，8 摩尔", choices=(4, 8)),
        "audit_mode": _spec(0, 0, 2, "0 风险导向，1 分散随机，2 中心集中"),
        "initial_audit": _spec(.3, 0, 1, "初始审计目标覆盖率"),
        "initial_strict": _spec(.3, 0, 1, "积极监管初始概率"),
        "initial_green": _spec(.3, 0, 1, "绿色生产初始概率"),
        "audit_min": _spec(0., 0, 1, "审计强度下限"),
        "audit_max": _spec(1., 0, 1, "审计强度上限"),
        "audit_period": _spec(1, 1, 4000, "审计强度调整周期 τ₁，MCS"),
        "regulator_period": _spec(1, 1, 4000, "监管策略更新周期 τ₂，MCS"),
        "farm_period": _spec(1, 1, 4000, "农业策略更新周期 τ₃，MCS"),
        "regulator_lag": _spec(0, 0, 60, "监管邻域信息时滞，MCS"),
        "farm_lag": _spec(0, 0, 60, "农业邻域信息时滞，MCS"),
        "audit_window": _spec(1, 1, 4000, "审计活跃窗口长度，MCS"),
        "audit_gap": _spec(0, 0, 4000, "相邻窗口间暂停长度，MCS"),
        "green_cost": _spec(13., 0, 1e6, "绿色生产成本 C_H，千元/亩"),
        "conventional_cost": _spec(5.4, 0, 1e6, "传统生产成本 C_L，千元/亩"),
        "farm_income": _spec(9., 0, 1e6, "生产基础收益 R_f，千元/亩"),
        "green_premium": _spec(3.5, 0, 1e6, "绿色额外收益 R_e，千元/亩"),
        "subsidy": _spec(.7, 0, 1e6, "绿色补贴 S_f，千元/亩"),
        "fine_multiple": _spec(5., 0, 100, "农户违规罚款倍数 b，P_f = b S_f"),
        "bribe_fraction": _spec(.5, 0, 1, "合谋租金比例，B = bribe_fraction × S_f"),
        "regulator_reward": _spec(.003, 0, 1e6, "监管绩效收益 R_d，千元/亩"),
        "regulator_light_fine": _spec(.0005, 0, 1e6, "监管轻责处罚 P_dl，千元/亩"),
        "regulator_heavy_fine": _spec(.02, 0, 1e6, "监管重责处罚 P_dh，千元/亩"),
        "regulator_cost": _spec(.003, 0, 1e6, "严格监管额外成本 C_d，千元/亩"),
        "audit_cost": _spec(.0007, 0, 1e6, "审计成本 C_a，千元/亩"),
        "audit_value": _spec(.0008, 0, 1e6, "审计隐性收益 R_a，千元/亩"),
        "fine_without_audit": _spec(0, 0, 1, "无审计但严格监管时的欺诈处罚。0 采用论文表2，1 采用式(1)"),
    }
    policy_parameters = {
        "audit_min", "audit_max", "audit_mode", "audit_period", "audit_window", "audit_gap",
        "regulator_period", "farm_period", "green_cost", "conventional_cost", "farm_income",
        "green_premium", "subsidy", "fine_multiple", "bribe_fraction", "regulator_reward",
        "regulator_light_fine", "regulator_heavy_fine", "regulator_cost", "audit_cost",
        "audit_value", "fine_without_audit",
    }

    def __init__(self, **parameters):
        self.parameters = {key: spec["default"] for key, spec in self.parameter_schema.items()}
        self._configure({**self.parameters, **parameters}, starting=True)

    def _configure(self, parameters, *, starting):
        for key, value in parameters.items():
            spec = self.parameter_schema[key]
            if (type(value) not in (float, int) or not spec["minimum"] <= value <= spec["maximum"]
                    or spec["type"] == "integer" and int(value) != value
                    or "enum" in spec and value not in spec["enum"]):
                raise ValueError(f"NET122 参数 {key} 超出合同范围")
        p = {key: int(value) if self.parameter_schema[key]["type"] == "integer" else float(value)
             for key, value in parameters.items()}
        if p["audit_min"] > p["audit_max"]:
            raise ValueError("审计强度下限不能高于上限")
        if starting and not p["audit_min"] <= p["initial_audit"] <= p["audit_max"]:
            raise ValueError("初始审计强度必须位于上下限内")
        self.parameters = p
        for key, value in p.items():
            setattr(self, key, value)
        self._payoff = self.payoff_table()
        self._payoff_span = self._payoff.max(axis=0) - self._payoff.min(axis=0)

    def payoff_table(self):
        p = self.parameters
        sf, rf, re = p["subsidy"], p["farm_income"], p["green_premium"]
        rd, cd = p["regulator_reward"], p["regulator_cost"]
        pf, b = sf * p["fine_multiple"], sf * p["bribe_fraction"]
        audited = p["audit_value"] - p["audit_cost"]
        green = rf + re + sf - p["green_cost"]
        regular = rf - p["conventional_cost"]
        strict = rd - cd
        # Row index 4a + 2d + g; columns audit, regulator, agriculture.
        return np.array((
            (-sf-rd, rd+b, regular+sf-b),
            (-rd, rd, green),
            (0, strict, regular-p["fine_without_audit"]*pf),
            (0, strict, green),
            (audited+pf+b, -p["regulator_heavy_fine"], regular-b-pf),
            (audited, -p["regulator_light_fine"], green),
            (audited, strict, regular-pf),
            (audited, strict, green),
        ), dtype=float)

    def initialize(self, context, parameters, population, topology, rng):
        self._configure({**self.parameters, **parameters}, starting=True)
        p = self.parameters
        side = p["grid_side"]
        self.size = side * side
        self._neighbors = periodic_neighbors(side, side, p["neighbors"])
        yy, xx = np.indices((side, side))
        center = (side - 1) / 2
        self._center_order = np.argsort(((yy-center)**2 + (xx-center)**2).ravel(), kind="stable")
        self._audit_rng, self._regulator_rng, self._farm_rng = (
            np.random.default_rng(int(seed)) for seed in rng.integers(0, 2**63, size=3, dtype="uint64")
        )
        self.strict = (rng.random(self.size) < p["initial_strict"]).astype(np.uint8)
        self.green = (rng.random(self.size) < p["initial_green"]).astype(np.uint8)
        self.audit_target = p["initial_audit"]
        self._epoch = np.zeros(3, dtype=np.int64)  # samples, lax, joint fraud
        self._last_epoch = self._epoch.copy()
        self._epoch_risk = np.zeros(self.size, dtype=bool)
        self._risk = self._epoch_risk.copy()
        self._history = deque(maxlen=max(p["regulator_lag"], p["farm_lag"]) + 1)
        self._stability = deque(maxlen=200)
        self.stable_mcs = -1
        self.audit_feedback = p["audit_value"] - p["audit_cost"]
        self.tick = 0
        self.audit_active = True
        self.audited = self._draw_audit()
        self.lax_detected = self.fraud_detected = self.lax_fraud_detected = 0
        self.regulator_switches = self.farm_switches = 0
        self._remember_stability()

    def _draw_audit(self):
        count = int(np.floor(np.nextafter(self.audit_target * self.size, np.inf)))
        mask = np.zeros(self.size, dtype=bool)
        if not self.audit_active or not count:
            return mask
        if count == self.size:
            mask[:] = True
        elif self.parameters["audit_mode"] == 2:
            mask[self._center_order[:count]] = True
        elif self.parameters["audit_mode"] == 1:
            mask[self._audit_rng.choice(self.size, size=count, replace=False)] = True
        else:
            risk = self._risk | self._risk[self._neighbors].any(axis=1)
            priority = np.flatnonzero(risk)
            if len(priority) > count:
                mask[self._audit_rng.choice(priority, size=count, replace=False)] = True
            else:
                mask[priority] = True
                remaining = np.flatnonzero(~mask)
                mask[self._audit_rng.choice(remaining, size=count-len(priority), replace=False)] = True
        return mask

    def _adjust_audit(self):
        self._last_epoch = self._epoch.copy()
        n, lax, joint = self._last_epoch
        p = self.parameters
        feedback = p["audit_value"] - p["audit_cost"]
        if n:
            feedback += (joint / n) * p["subsidy"] * (1 + p["fine_multiple"] + p["bribe_fraction"])
            feedback += (lax / n) * p["regulator_reward"]
            self._risk = self._epoch_risk.copy()
        self.audit_feedback = float(feedback)
        step = .05 if feedback > 0 else -.01
        self.audit_target = float(np.clip(self.audit_target + step, p["audit_min"], p["audit_max"]))
        self._epoch.fill(0)
        self._epoch_risk.fill(False)

    def _remember_stability(self):
        self._stability.append((self.audit_target, self.strict.mean(), self.green.mean()))
        if self.stable_mcs < 0 and len(self._stability) == self._stability.maxlen:
            if (np.std(self._stability, axis=0) < .0001).all():
                self.stable_mcs = self.tick

    def step(self, t, dt):
        if dt != self.fixed_dt or abs(t - self.tick) > 1e-8:
            raise ValueError("NET122 按完整的蒙特卡洛步推进，干预须位于整数步")
        p = self.parameters
        if self.tick and self.tick % p["audit_period"] == 0:
            self._adjust_audit()
        self.audit_active = self.tick % (p["audit_window"] + p["audit_gap"]) < p["audit_window"]
        self.audited = self._draw_audit()
        lax = self.audited & (self.strict == 0)
        fraud = self.audited & (self.green == 0)
        self.lax_detected = int(lax.sum())
        self.fraud_detected = int(fraud.sum())
        self.lax_fraud_detected = int((lax & fraud).sum())
        self._epoch += (int(self.audited.sum()), self.lax_detected, self.lax_fraud_detected)
        self._epoch_risk |= fraud
        row = 4 * self.audited.astype(np.uint8) + 2 * self.strict + self.green
        rewards = self._payoff[row]
        self._history.append((self.strict, self.green, rewards[:, 1], rewards[:, 2]))

        def revise(role, schedule, lag, rng):
            current = self._history[-1][role]
            if (self.tick + 1) % schedule:
                return current
            past = self._history[max(0, len(self._history)-1-lag)]
            return imitate_best(current, rewards[:, role+1], past[role], past[role+2],
                                self._neighbors, self._payoff_span[role+1], rng)

        strict = revise(0, p["regulator_period"], p["regulator_lag"], self._regulator_rng)
        green = revise(1, p["farm_period"], p["farm_lag"], self._farm_rng)
        self.regulator_switches = int(np.count_nonzero(strict != self.strict))
        self.farm_switches = int(np.count_nonzero(green != self.green))
        self.strict, self.green = strict, green
        self.tick += 1
        self._remember_stability()

    def apply_intervention(self, updates, t):
        if int(t) != t:
            raise ValueError("NET122 的干预时点须为整数蒙特卡洛步")
        forbidden = sorted(set(updates) - self.policy_parameters)
        if forbidden:
            raise ValueError("不能在运行中重置网格、时滞历史或初始状态：" + "、".join(forbidden))
        self._configure({**self.parameters, **updates}, starting=False)
        self.audit_target = float(np.clip(self.audit_target, self.parameters["audit_min"],
                                          self.parameters["audit_max"]))

    def observe(self):
        audited = int(self.audited.sum())
        strict = int(self.strict.sum())
        green = int(self.green.sum())
        return {
            "n_cells": int(self.size), "audit_institutions": 1,
            "audited_cells": audited, "strict_cells": strict, "green_cells": green,
            "audit_target": float(self.audit_target), "audit_coverage": float(audited / self.size),
            "strict_share": float(strict / self.size), "lax_share": float((self.size-strict) / self.size),
            "green_share": float(green / self.size),
            "fraud_share": float((self.size-green) / self.size),
            "lax_detected": int(self.lax_detected), "fraud_detected": int(self.fraud_detected),
            "lax_fraud_detected": int(self.lax_fraud_detected),
            "audit_active": bool(self.audit_active), "audit_feedback": float(self.audit_feedback),
            "feedback_samples": int(self._last_epoch[0]), "feedback_lax": int(self._last_epoch[1]),
            "feedback_lax_fraud": int(self._last_epoch[2]),
            "regulator_switches": int(self.regulator_switches), "farm_switches": int(self.farm_switches),
            "stable_mcs": int(self.stable_mcs),
            "distance_to_ideal": float(np.linalg.norm((1-self.audit_target, 1-strict/self.size,
                                                        1-green/self.size)) / np.sqrt(3)),
        }

    def validate_state(self):
        if not self.parameters["audit_min"] <= self.audit_target <= self.parameters["audit_max"]:
            return ["审计强度越界"]
        if any(values.shape != (self.size,) for values in (self.audited, self.strict, self.green)):
            return ["主体策略与网格不一致"]
        return []

    def state_frame(self):
        side = self.parameters["grid_side"]
        layers = []
        for (key, label, states), values in zip(LAYER_DEFINITIONS, (self.audited, self.strict, self.green)):
            encoded = (values.astype(np.uint8) + ord("0")).tobytes().decode("ascii")
            layers.append({"id": key, "label": label, "states": list(states), "values": encoded})
        return {"entities": [], "facilities": [], "relations": [], "sim_t": self.tick,
                "lattice": {"width": side, "height": side, "layers": layers}}
