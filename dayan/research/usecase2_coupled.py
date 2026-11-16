"""Goodwin宏微观耦合机制比较；真实数据可初始化，行为/政策参数仍须声明假设。

政策臂通过改变 Goodwin 参数实际改变机制：
- 基线：默认参数（nu=2.5, delta=0.03, a=0.045, b=0.06）
- 臂1 就业补贴：提高 b（菲利普斯敏感度→就业对工资增长响应更强）
- 臂2 培训投资：降低 a（降低工资增长压力）+ 降低 nu（资本效率提升）
每种3种子，记录 wage_share/employment_sd/employment_abm 三通道轨迹。
成本按年度财政投入估算，标注为参数化假设。
"""
from __future__ import annotations

import json
import math
from datetime import datetime

import numpy as np

from ..coupled import CoupledSimulation


def run_coupled_scenario(name: str, *, nu: float = 2.5, delta: float = 0.03,
                         a: float = 0.045, b: float = 0.06,
                         n_micro: int = 200, seeds: list | None = None,
                         T: float = 100.0, dt: float = 0.1,
                         policy_cost_per_capita: float | None = None,
                         reservation_shift: float = 0.0,
                         initialization: dict | None = None) -> dict:
    """运行一个耦合情景（多种子），返回异质群体+宏观数据。

    政策传导路径（审计修正后）：
    - reservation_shift < 0：降低保留工资（就业补贴/培训让工人更愿意接受工作）
      → 直接改变 ABM 异质群体的行为参数，而非间接改 SD 宏观系数
    - nu 变化：资本效率→投资→就业需求（Goodwin 供给侧传导）
    """
    seeds = [0, 1, 2] if seeds is None else seeds
    if not seeds or len(set(seeds)) != len(seeds) or len(seeds) > 30:
        raise ValueError("需要1..30个不重复种子")
    if not (0 < dt <= T <= 1000) or T/dt > 10000 or not 10 <= n_micro <= 2000:
        raise ValueError("耦合运行超出有界时长/主体预算")
    binding = None
    if initialization:
        from .studies import verified_records, digest
        task, records = verified_records(initialization["collection_id"])
        if task["connector"] != "worldbank" or task["params"].get("indicator") != "SL.UEM.TOTL.ZS":
            raise ValueError("就业初始化须为已核验的失业率百分比，不能用人口或目录替代")
        selected = [r for r in records if str(r.get("date")) == str(initialization["year"])
                    and r.get("country_id") == initialization["country_id"]]
        if len(selected) != 1 or selected[0].get("value") is None or not 0 <= float(selected[0]["value"]) <= 100:
            raise ValueError("指定地区年份没有唯一有效失业率观测")
        value = float(selected[0]["value"])
        binding = {**initialization, "indicator": "SL.UEM.TOTL.ZS", "observed_unemployment_percent": value,
                   "transform": "employment_share = 1 - unemployment_percent / 100",
                   "resolved_employment_share": 1-value/100, "record_sha256": digest(selected[0]),
                   "source_page_sha256": selected[0]["_sha256"], "role": "initialization"}
    runs = []
    for seed in seeds:
        sim = CoupledSimulation(mode="cyclic", n_micro=n_micro, seed=seed,
                                T=T, dt=dt)
        sim.sd.nu = nu
        sim.sd.delta = delta
        sim.sd.a = a
        sim.sd.b = b
        if binding:
            share = binding["resolved_employment_share"]
            sim.sd.x[1] = share
            # Model agents are a hypothetical finite sample, not real individual census records.
            sim.abm.employed[:] = False
            initial_count = round(share*n_micro)
            sim.abm.employed[sim.abm.rng.permutation(n_micro)[:initial_count]] = True
        initial = {"employment_sd": float(sim.sd.x[1]), "employment_abm": sim.abm.get_employment_rate()}
        # 异质群体政策传导：直接改保留工资分布（有理论依据——培训/补贴降低保留门槛）
        if reservation_shift != 0:
            sim.abm.reservation = np.clip(
                sim.abm.reservation + reservation_shift, 0.05, 0.99)
        summary = sim.run()
        runs.append({
            "seed": seed,
            "final_wage_share": sim.history[-1]["wage_share"],
            "final_employment_abm": sim.history[-1]["employment_abm"],
            "mean_employment_abm": round(np.mean([h["employment_abm"]
                                                  for h in sim.history]), 4),
            "employment_std_abm": round(np.std([h["employment_abm"]
                                                for h in sim.history]), 4),
            "trajectory_length": len(sim.history),
            "trajectory_sample": sim.history[::max(1, len(sim.history)//10)][:11],
            "trajectory": sim.history,
            "initial": initial,
        })

    emp_means = [r["mean_employment_abm"] for r in runs]
    return {
        "scenario": name, "params": {"nu": nu, "delta": delta, "a": a, "b": b, "reservation_shift": reservation_shift},
        "seeds": seeds, "n_micro": n_micro,
        "mean_employment": round(float(np.mean(emp_means)), 4),
        "std_employment": round(float(np.std(emp_means, ddof=1)), 4)
        if len(emp_means) > 1 else 0.0,
        "runs": runs,
        "policy_cost_per_capita": policy_cost_per_capita,
        "cost_evidence": "user_assumption_not_empirically_estimated" if policy_cost_per_capita is not None else "not_provided",
        "empirical_binding": binding,
        "calibration_status": "not_calibrated",
        "evidence_scope": "仅初始化使用真实宏观观测；行为、政策幅度、工资份额和成本仍是假设，不能据此宣称现实政策效果" if binding else "纯机制假设情景，无真实数据绑定或校准",
        "note": "异质个体保留工资服从 U(0.4,0.95)；就业概率取决于个体保留工资与SD工资份额",
    }


def compare_scenarios(baseline: dict, policy1: dict, policy2: dict) -> dict:
    """三方案对比（就业率差异+成本）。"""
    b_emp = baseline["mean_employment"]
    p1_emp = policy1["mean_employment"]
    p2_emp = policy2["mean_employment"]
    def ordering(values):
        return tuple(sorted(range(len(values)), key=lambda i: (values[i], i)))
    cohorts = [{r["seed"]: r["mean_employment_abm"] for r in s["runs"]} for s in (baseline, policy1, policy2)]
    common = sorted(set.intersection(*(set(c) for c in cohorts)))
    if any(set(c) != set(common) for c in cohorts):
        raise ValueError("政策比较需要相同配对种子，不能比较不同随机样本冒称政策效应")
    rankings = [ordering([c[seed] for c in cohorts]) for seed in common]
    stable = len(common) >= 3 and len(set(rankings)) == 1
    return {
        "baseline_employment": b_emp,
        "policy1_employment": p1_emp,
        "policy2_employment": p2_emp,
        "policy1_delta": round(p1_emp - b_emp, 4),
        "policy2_delta": round(p2_emp - b_emp, 4),
        "policy1_cost": policy1.get("policy_cost_per_capita", 0),
        "policy2_cost": policy2.get("policy_cost_per_capita", 0),
        "ranking_stable": stable,
        "ranking_check": {"scope": "仅跨配对种子的排序一致性，非参数/结构稳健性", "n_paired_seeds": len(common),
                          "ordering_by_seed": {str(seed):list(rank) for seed,rank in zip(common,rankings)}},
        "paired_deltas": {"policy1": [cohorts[1][seed]-cohorts[0][seed] for seed in common],
                          "policy2": [cohorts[2][seed]-cohorts[0][seed] for seed in common]},
        "note": "模型内反事实比较，不构成现实因果识别",
    }


def run_usecase2_coupled() -> dict:
    """完整用例2：耦合模型政策比较。"""
    baseline = run_coupled_scenario(
        "基线(现状延续)", nu=2.5, delta=0.03, a=0.045, b=0.06,
        reservation_shift=0.0, policy_cost_per_capita=0)
    policy1 = run_coupled_scenario(
        "就业补贴(降低保留工资0.1)", nu=2.5, delta=0.03, a=0.045, b=0.06,
        reservation_shift=-0.1, policy_cost_per_capita=500)
    policy2 = run_coupled_scenario(
        "培训+资本效率(降保留工资0.15+降nu)", nu=1.8, delta=0.03,
        a=0.045, b=0.06, reservation_shift=-0.15, policy_cost_per_capita=1500)

    comparison = compare_scenarios(baseline, policy1, policy2)
    return {
        "use_case": "mechanism_policy_assumptions",
        "empirical_scope": "未绑定地区观测、未校准的假设示例；不代表中国或其他地区的真实政策效果",
        "model": "GoodwinSD + MicroABM(cyclic, heterogeneous workers)",
        "n_micro": 200, "T": 100.0, "dt": 0.1,
        "baseline": baseline, "policy1": policy1, "policy2": policy2,
        "comparison": comparison,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }


if __name__ == "__main__":
    result = run_usecase2_coupled()
    print(json.dumps(result["comparison"], ensure_ascii=False, indent=2))
    json.dump(result, open("data/collection/usecase2_coupled.json", "w",
                           encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n归档: data/collection/usecase2_coupled.json")
