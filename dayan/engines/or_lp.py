"""R7-c OREngine：线性规划/运输问题 + propose–dispose 协议。

规范（三主权第四条延伸）：LLM 提出分配方案（自然语言→结构化），
确定性求解器验证可行性/最优性，LLM 只解释——LLM 永不做数学。
"""
from __future__ import annotations

from typing import Any, Optional

import numpy as np
from scipy.optimize import linprog


def solve_lp(c: np.ndarray, A_ub=None, b_ub=None, A_eq=None, b_eq=None,
             bounds=None) -> dict:
    """线性规划（min c·x s.t. 约束）。返回 {ok, x, cost, status}。"""
    r = linprog(c, A_ub=A_ub, b_ub=b_ub, A_eq=A_eq, b_eq=b_eq,
                bounds=bounds, method="highs")
    ok = r.success
    return {"ok": bool(ok), "x": (r.x.tolist() if ok else None),
            "cost": (float(r.fun) if ok else None), "status": r.message}


def solve_transportation(supplies: list[float], demands: list[float],
                         costs: list[list[float]]) -> dict:
    """运输问题：min Σcost·x s.t. Σ_j x_ij=supply_i, Σ_i x_ij=demand_j, x≥0。"""
    s, d = np.asarray(supplies, float), np.asarray(demands, float)
    c = np.asarray(costs, float)
    assert c.shape == (len(s), len(d)), "成本矩阵形状不符"
    assert abs(s.sum() - d.sum()) < 1e-9, "供需不平衡（模板要求平衡）"
    m, n = c.shape
    c_flat = c.flatten()
    A_eq, b_eq = [], []
    for i in range(m):
        row = np.zeros(m * n)
        row[i * n:(i + 1) * n] = 1.0
        A_eq.append(row)
        b_eq.append(s[i])
    for j in range(n):
        col = np.zeros(m * n)
        col[j::n] = 1.0
        A_eq.append(col)
        b_eq.append(d[j])
    r = linprog(c_flat, A_eq=np.array(A_eq), b_eq=np.array(b_eq),
                method="highs")
    ok = r.success
    return {"ok": bool(ok), "x": (np.array(r.x).reshape(m, n) if ok else None),
            "cost": (float(r.fun) if ok else None), "status": r.message}


def check_feasible(x: np.ndarray, supplies: np.ndarray, demands: np.ndarray,
                   tol: float = 1e-6) -> tuple[bool, str]:
    """提案方案可行性校验（propose–dispose 的 dispose 端）。"""
    x = np.asarray(x, float)
    if x.shape != (len(supplies), len(demands)):
        return False, "形状不符"
    if (x < -1e-9).any():
        return False, "存在负运量"
    if (np.abs(x.sum(axis=1) - supplies) > 1e-6).any():
        return False, "行和≠供给"
    if (np.abs(x.sum(axis=0) - demands) > 1e-6).any():
        return False, "列和≠需求"
    return True, "可行"


def optimality_gap(x_prop: np.ndarray, costs: np.ndarray,
                   optimal_cost: float) -> float:
    """提案成本与最优成本之差（≥0；=0 即最优）。"""
    c = float((np.asarray(x_prop, float) * np.asarray(costs, float)).sum())
    return c - optimal_cost
