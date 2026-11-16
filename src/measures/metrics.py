"""分布与结构测量（纯确定性，无 LLM）。"""
from __future__ import annotations

import numpy as np


def gini(wealth: list[float]) -> float:
    w = np.sort(np.asarray(wealth, dtype=float))
    n = len(w)
    if n == 0 or w.sum() <= 0:
        return 0.0
    cum = np.cumsum(w)
    return float((n + 1 - 2 * np.sum(cum) / cum[-1]) / n)


def top_shares(wealth: list[float]) -> dict:
    w = np.sort(np.asarray(wealth, dtype=float))
    n = len(w)
    tot = w.sum()
    if tot <= 0:
        return {"top10": 0.0, "top1": 0.0, "bottom50": 0.0}
    k10 = max(1, int(round(0.1 * n)))
    k1 = max(1, int(round(0.01 * n)))
    return {
        "top10": float(w[-k10:].sum() / tot),
        "top1": float(w[-k1:].sum() / tot),
        "bottom50": float(w[: n // 2].sum() / tot),
    }


def class_matrix(prev: dict, cur: dict) -> dict:
    """两期位置转移计数。prev/cur: {aid: position}"""
    keys = ["unemployed", "worker", "self", "employer", "member"]
    m = {f"{a}->{b}": 0 for a in keys for b in keys}
    for aid, p0 in prev.items():
        p1 = cur.get(aid)
        if p1 is not None:
            m[f"{p0}->{p1}"] += 1
    return m


def exploitation_stats(world) -> dict:
    """剩余占有结构的微观记账式测量（口径：当期经营结余/工资单）。

    - profit_w: 有雇员企业的当期经济利润之和（收入−工钱−折旧价值），可为负
    - wages: 当期工资单总额
    - exploitation_rate = max(profit_w, 0) / wages  （只计正结余，口径注明）
    - labor_share = wages / (wages + max(profit_w, 0))
    报告时必须注明这是"经营结余/工资单"的代理口径，与马克思 s/(v) 的
    概念差异见实验设计书。
    """
    profit_w = 0.0
    wages = 0.0
    n_firms_with_workers = 0
    for f in world.firms.values():
        if f.workers:
            n_firms_with_workers += 1
            wages += f.wage_bill
            if getattr(f, "is_coop", False):
                continue  # 合作社：成员为剩余索取者，无雇佣剩余（构造性为零）
            dep = world.params.delta * world.params.P_K * f.capital_used
            profit_w += f.revenue - f.wage_bill - dep
    rate = max(profit_w, 0.0) / wages if wages > 0 else float("nan")
    lshare = wages / (wages + max(profit_w, 0.0)) if wages > 0 else float("nan")
    return {"profit_w": profit_w, "wages": wages,
            "exploitation_rate": rate, "labor_share": lshare,
            "n_firms_with_workers": n_firms_with_workers}
