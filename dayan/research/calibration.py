"""真实数据校准与独立留出验证（任务书 §四.4）。

设计约束：
- 只支持一个与所选案例适配的校准器（当前：网格搜索 + 均方误差），不泛化声明
- 必须接收：真实观测、待估参数及范围、损失函数、预算、数据角色
- 优化过程确实调用模型（不是纸面拟合）
- 记录评估点数、失败、目标值、所选参数、不可识别诊断
- 留出集独立于拟合数据（时间切分优先），分割不泄漏由调用方传入不同的 collection_id 并被 role_leakage 拦截
- 阈值在看结果前声明（调用方传入 tolerance），超阈如实失败
"""
from __future__ import annotations

import itertools
import math
from datetime import datetime, timezone

import numpy as np


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _series(rows, label):
    if not rows:
        raise ValueError(f"{label}为空")
    if len(rows) > 10000:
        raise ValueError("每个角色最多1万观测点")
    years, values = [], []
    for row in rows:
        year, value = float(row["date"]), float(row["value"])
        if not math.isfinite(year) or not math.isfinite(value):
            raise ValueError(f"{label}包含非有限日期或观测值")
        years.append(year); values.append(value)
    if len(set(years)) != len(years):
        raise ValueError(f"{label}日期重复；请先明确地区/群体维度再建立单变量时间序列")
    if years != sorted(years):
        raise ValueError(f"{label}必须按时间升序排列")
    return years, values


def _predict(fn, params, years):
    result = list(fn(dict(params), list(years)))
    if len(result) != len(years):
        raise ValueError(f"预测长度{len(result)}与观测长度{len(years)}不一致，不能zip截断")
    values = [float(v) for v in result]
    if not all(math.isfinite(v) for v in values):
        raise ValueError("预测包含缺失或非有限值，不能丢掉失败预测点")
    return values


def _rmse(actual, predicted):
    return math.sqrt(sum((a-p)**2 for a, p in zip(actual, predicted)) / len(actual))


def grid_search_calibrate(*, model_fn, param_grid, observations, loss_fn=None,
                          tolerance=None, budget=500, holdout_observations=None,
                          name="", holdout_tolerance=None):
    """Bounded exact-length evaluations, independent forward holdout, complete audit trail.

    A finite grid cannot establish structural identifiability or policy causality.
    """
    years, actual = _series(observations, "训练集")
    hold_years, hold_actual = _series(holdout_observations, "留出集") if holdout_observations else ([], [])
    if hold_years and (set(years) & set(hold_years) or min(hold_years) <= max(years)):
        raise ValueError("留出日期必须独立并晚于全部训练日期，不能重叠/回流")
    budget = int(budget)
    if not 1 <= budget <= 10000 or not param_grid or len(param_grid) > 8:
        raise ValueError("需1..8个参数，评估预算须为1..10000")
    names, grids = list(param_grid), []
    for key in names:
        grid = list(param_grid[key])
        if not grid or len(grid) > 10000:
            raise ValueError("参数网格为空或过大")
        grid = [float(v) for v in grid]
        if not all(math.isfinite(v) for v in grid):
            raise ValueError("参数网格包含非有限值")
        grids.append(list(dict.fromkeys(grid)))
    for value in (tolerance, holdout_tolerance):
        if value is not None and (not math.isfinite(float(value)) or float(value) < 0):
            raise ValueError("误差阈值须为非负有限数字")
    total = math.prod(len(g) for g in grids)
    evaluations, best, best_pred, best_loss = [], None, None, math.inf
    for i, combo in enumerate(itertools.islice(itertools.product(*grids), budget)):
        params = dict(zip(names, combo))
        entry = {"combo_id": i, "params": params, "loss": None}
        try:
            predicted = _predict(model_fn, params, years)
            loss = float((loss_fn or _rmse)(actual, predicted))
            if not math.isfinite(loss) or loss < 0:
                raise ValueError("损失函数返回非法值")
            entry["loss"] = loss
            if loss < best_loss:
                best, best_pred, best_loss = params, predicted, loss
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        evaluations.append(entry)
    base = {"name": name, "calibrator": "grid_search_rmse" if loss_fn is None else "grid_search_custom",
            "loss_metric": "rmse" if loss_fn is None else "custom", "at": _now(),
            "n_observations": len(actual), "n_evaluated": len(evaluations), "grid_size": total,
            "budget": budget, "budget_exhausted": len(evaluations) < total,
            "n_failed": sum(e["loss"] is None for e in evaluations), "evaluations": evaluations,
            "validation_scope": "给定模型/变量/划分上的误差检验；不证明政策因果、外推有效性或参数结构可识别"}
    if best is None:
        return {**base, "status": "failed", "error": "所有参数组合均失败，详见evaluations"}
    mean = sum(actual) / len(actual)
    baseline = _rmse(actual, [mean]*len(actual))
    near = [e for e in evaluations if e["loss"] is not None and math.isclose(e["loss"], best_loss, rel_tol=.05, abs_tol=1e-10)]
    train_ok = None if tolerance is None else best_loss <= float(tolerance)
    hold_limit = holdout_tolerance if holdout_tolerance is not None else tolerance
    hold, hold_ok = None, None
    if hold_years:
        try:
            pred = _predict(model_fn, best, hold_years)
            rmse = _rmse(hold_actual, pred)
            hold_ok = None if hold_limit is None else rmse <= float(hold_limit)
            hold = {"n": len(hold_actual), "dates": hold_years, "actual": hold_actual,
                    "predicted": pred, "residuals": [a-p for a,p in zip(hold_actual,pred)],
                    "rmse": rmse, "tolerance": hold_limit, "tolerance_met": hold_ok,
                    "baseline_train_mean_rmse": _rmse(hold_actual, [mean]*len(hold_actual))}
        except Exception as exc:
            hold_ok = False
            hold = {"n": len(hold_actual), "error": str(exc), "tolerance_met": False}
    status = ("failed_tolerance" if train_ok is False else "failed_holdout" if hold_ok is False else
              "fitted_no_holdout" if not hold_years else "fitted_unvalidated" if train_ok is None or hold_ok is None else "pass")
    return {**base, "status": status, "best_params": best, "best_loss": best_loss,
            "training": {"dates": years, "actual": actual, "predicted": best_pred,
                         "residuals": [a-p for a,p in zip(actual,best_pred)]},
            "tolerance": tolerance, "tolerance_met": train_ok is True and hold_ok is True,
            "training_tolerance_met": train_ok, "failure_note": "" if status == "pass" else status,
            "baseline_mean_rmse": baseline, "improvement_vs_baseline": baseline-best_loss,
            "holdout": hold, "non_identifiable": len(near) > 1, "near_min_count": len(near),
            "identifiability_status": "not_established_by_grid_search",
            "non_identifiable_note": f"网格内{len(near)}组损失接近；结构可识别性未证实，不能据唯一网格最优宣称可识别"}


def time_split(records, *, holdout_years=1, time_field="date"):
    if not isinstance(holdout_years, int) or holdout_years < 1:
        raise ValueError("留出年份数须为正整数")
    years = sorted({float(r[time_field]) for r in records})
    if len(years) <= holdout_years:
        raise ValueError("时间点不足，无法形成独立训练/留出集")
    cut = years[-holdout_years]
    calibration = sorted([r for r in records if float(r[time_field]) < cut], key=lambda r: float(r[time_field]))
    holdout = sorted([r for r in records if float(r[time_field]) >= cut], key=lambda r: float(r[time_field]))
    return calibration, holdout
