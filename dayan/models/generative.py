"""Real LLM cognitive loops in an explicitly abstract community environment.

Inspired by Park et al. 2304.03442, ReAct 2210.03629, Reflexion 2303.11366,
and Voyager 2305.16291. This is a small executable adaptation, not a full
reproduction of those environments, evaluations, or empirical human behavior.
"""
from __future__ import annotations

import copy
import json
import math
import numpy as np

from ..llm_client import complete, configured, json_object


class CognitiveSimulation:
    clock_type = "fixed_step"
    time_unit = "abstract model time"
    requires_external = True
    declared_observables = ["n_agents", "n_memories", "n_reflections", "llm_calls", "actions_executed", "mean_energy", "resources", "hazard", "objective"]
    cognitive_mode = "memory-reflection-plan"
    implementation_note = "真实LLM调用与模拟环境行动闭环；简化架构适配，非原论文全量复现；非真实居民数据"

    def __init__(self, n=2, scenario="抽象社区居民通过工作和互助降低风险，维持能量与公共资源。",
                 decision_interval=10.0, max_llm_calls=8, initial_energy=.7):
        if isinstance(n, bool) or int(n) != n or not 1 <= n <= 8:
            raise ValueError("真实LLM主体数量须为1–8整数")
        if isinstance(max_llm_calls, bool) or int(max_llm_calls) != max_llm_calls or not 1 <= max_llm_calls <= 12:
            raise ValueError("每次仿真LLM调用预算须为1–12整数")
        if not math.isfinite(decision_interval) or decision_interval <= 0 or not 0 <= initial_energy <= 1:
            raise ValueError("决策间隔须为正，初始能量须在0–1内")
        self.n, self.scenario = int(n), str(scenario)
        self.decision_interval, self.max_llm_calls = decision_interval, int(max_llm_calls)
        self.initial_energy = float(initial_energy)

    def initialize(self, context=None, parameters=None, population=None, topology=None, rng=None):
        if not configured():
            raise RuntimeError("此模型需要真实LLM服务；未配置时不能用固定脚本运行")
        self.rng = rng if rng is not None else np.random.default_rng(0)
        self.agents = [{"id": i, "x": float(self.rng.uniform(0, 10)), "y": float(self.rng.uniform(0, 10)),
                        "energy": self.initial_energy, "memory": [], "reflections": [], "plan": [],
                        "next_decision": 0., "decision": None, "skills": []} for i in range(self.n)]
        self.t, self.resources, self.hazard = 0., 10., 1.
        self.llm_audit, self.events = [], []
        self.actions_executed = 0
        self.budget_reported = False

    def _objective(self):
        return float(self.resources - 10*self.hazard + sum(a["energy"] for a in self.agents))

    def _decide(self, agent):
        recent = sorted(agent["memory"], key=lambda m: m["importance"] + .01*m["sim_t"], reverse=True)[:8]
        context = {"scenario": self.scenario, "mode": self.cognitive_mode,
                   "sim_t": self.t, "resources": self.resources, "hazard": self.hazard,
                   "agent": {k: agent[k] for k in ("id", "x", "y", "energy")},
                   "retrieved_memory": recent, "reflections": agent["reflections"][-3:],
                   "skills": agent["skills"][-5:], "objective": self._objective()}
        prompt = ("你是抽象社会仿真中的主体；根据实际观测、记忆与上次行动反馈做下一次决策。"
                  "只输出JSON：{action:rest|work|help|share|move,reason:简短可展示理由,reflection:从反馈得出的反思,plan:[后续行动描述],target:[x,y],skill:[动作名序列]}。"
                  "不能自称已执行行动或编造环境结果。工作消耗能量并增加公共资源，互助消耗能量/资源并降低风险，休息恢复能量；"
                  "move向0–10坐标移动；share记录对其他主体的实际消息。按给定mode使用记忆反思规划/反馈修正/技能复用。"
                  "Concordia裁决模式另返回allowed布尔值，程序只执行通过裁决且满足资源约束的动作。")
        raw = complete([{"role": "system", "content": prompt},
                        {"role": "user", "content": json.dumps(context, ensure_ascii=False)}],
                       max_tokens=4096, timeout=60, purpose=self.model_id + ":" + self.cognitive_mode,
                       audit=self.llm_audit)
        decision = json_object(raw)
        if decision.get("action") not in ("rest", "work", "help", "share", "move"):
            raise ValueError("LLM行动不在模拟环境工具合同中，未执行")
        if not isinstance(decision.get("reason"), str) or not decision["reason"].strip():
            raise ValueError("LLM决策缺少可审计理由")
        if decision["action"] == "move":
            target = decision.get("target")
            if not isinstance(target, list) or len(target) != 2 or any(not isinstance(x, (int, float)) or not math.isfinite(x) or not 0 <= x <= 10 for x in target):
                raise ValueError("LLM移动目标非法，未执行")
        if self.cognitive_mode == "game-master" and not isinstance(decision.get("allowed"), bool):
            raise ValueError("GM缺少明确裁决")
        agent["decision"] = decision
        agent["plan"] = decision.get("plan", [])
        if decision.get("reflection"):
            agent["reflections"].append(str(decision["reflection"])[:1000])
        agent["next_decision"] = self.t + self.decision_interval
        self.events.append({"sim_t": self.t, "etype": "llm_decision", "agent_id": agent["id"],
                            "call_id": self.llm_audit[-1]["call_id"], "decision": decision})

    def _act(self, agent, dt):
        d = agent["decision"]
        if d is None:
            return {"action": None, "applied": False, "reason": "调用预算不足，主体尚无有效计划"}
        action = d["action"]
        applied, reason = True, ""
        if self.cognitive_mode == "game-master" and not d["allowed"]:
            applied, reason = False, "GM否决"
        elif action == "rest":
            agent["energy"] = min(1., agent["energy"]+.15*dt)
        elif action in ("work", "help"):
            cost = (.1 if action == "work" else .12)*dt
            if agent["energy"] < cost or action == "help" and self.resources < dt:
                applied, reason = False, "实际能量或公共资源不足"
            else:
                agent["energy"] -= cost
                self.resources += dt if action == "work" else -dt
                self.hazard = max(0., self.hazard - (.02 if action == "work" else .1)*dt)
        elif action == "move":
            dx, dy = d["target"][0]-agent["x"], d["target"][1]-agent["y"]
            distance = math.hypot(dx, dy)
            step = min(distance, dt)
            if distance:
                agent["x"] += dx/distance*step
                agent["y"] += dy/distance*step
        elif action == "share":
            for other in self.agents:
                if other["id"] != agent["id"]:
                    other["memory"].append({"sim_t": self.t, "importance": 2.,
                                             "message_from": agent["id"], "message": d["reason"]})
        if applied:
            self.actions_executed += 1
        return {"action": action, "applied": applied, "reason": reason}

    def step(self, t, dt):
        self.t = float(t)
        for agent in self.agents:
            before = self._objective()
            agent["memory"].append({"sim_t": self.t, "importance": 1+abs(self.hazard),
                                     "energy": agent["energy"], "resources": self.resources, "hazard": self.hazard})
            if self.t+1e-9 >= agent["next_decision"]:
                if len(self.llm_audit) < self.max_llm_calls:
                    self._decide(agent)
                elif not self.budget_reported:
                    self.events.append({"sim_t": self.t, "etype": "llm_budget", "message": "预算已用尽；此后仅执行最后真实生成的计划，不再产生新LLM调用"})
                    self.budget_reported = True
            outcome = self._act(agent, dt)
            gain = self._objective()-before
            agent["memory"].append({"sim_t": self.t+dt, "importance": 3+abs(gain), "outcome": outcome, "objective_delta": gain})
            if self.cognitive_mode == "skill-library" and outcome["applied"] and gain > 0:
                skill = (agent["decision"] or {}).get("skill", [])
                if isinstance(skill, list) and skill and all(s in ("rest", "work", "help", "share", "move") for s in skill) and skill not in agent["skills"]:
                    agent["skills"].append(skill)
            self.events.append({"sim_t": self.t+dt, "etype": "action_outcome", "agent_id": agent["id"], **outcome, "objective_delta": gain})
        self.t = float(t+dt)

    def observe(self):
        return {"n_agents": len(self.agents), "n_memories": sum(len(a["memory"]) for a in self.agents),
                "n_reflections": sum(len(a["reflections"]) for a in self.agents),
                "llm_calls": len(self.llm_audit), "actions_executed": self.actions_executed,
                "mean_energy": float(np.mean([a["energy"] for a in self.agents])),
                "resources": self.resources, "hazard": self.hazard, "objective": self._objective()}

    def state_frame(self):
        return {"entities": [{"id": a["id"], "type": "agent", "x": a["x"], "y": a["y"],
                               "state": (a["decision"] or {}).get("action", "awaiting_decision"),
                               "energy": a["energy"]} for a in self.agents],
                "relations": [], "facilities": [], "aggregates": self.observe(),
                "space": {"bounds": [0, 0, 10, 10], "unit": "abstract distance"}}

    def snapshot(self):
        return {"parameters": {key: getattr(self, key) for key in ("n", "scenario", "decision_interval", "max_llm_calls", "initial_energy")},
                "agents": self.agents, "t": self.t, "resources": self.resources, "hazard": self.hazard,
                "llm_audit": self.llm_audit, "events": self.events, "actions_executed": self.actions_executed,
                "budget_reported": self.budget_reported, "rng_state": self.rng.bit_generator.state}

    def restore(self, snapshot):
        self.__init__(**snapshot["parameters"])
        self.initialize()
        for key in ("agents", "t", "resources", "hazard", "llm_audit", "events", "actions_executed", "budget_reported"):
            setattr(self, key, copy.deepcopy(snapshot[key]))
        self.rng.bit_generator.state = snapshot["rng_state"]

    def validate_state(self):
        return [] if self.resources >= 0 and all(0 <= a["energy"] <= 1 for a in self.agents) else ["资源或能量越界"]


class GenerativeAgentModel(CognitiveSimulation):
    model_id = "BEH129"


class ReActModel(CognitiveSimulation):
    model_id = "BEH130"
    cognitive_mode = "observe-decide-tool-feedback"


class ReflexionModel(CognitiveSimulation):
    model_id = "BEH131"
    cognitive_mode = "outcome-feedback-reflection"


class VoyagerSkillLibraryModel(CognitiveSimulation):
    model_id = "BEH132"
    cognitive_mode = "skill-library"


class ConcordiaModel(CognitiveSimulation):
    model_id = "BEH133"
    cognitive_mode = "game-master"
