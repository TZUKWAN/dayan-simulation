"""财富分布双形态拟合：下层指数 + 上层 Pareto（Yakovenko 校准靶）。"""
from __future__ import annotations

import numpy as np
from scipy import stats


def fit_two_class(wealth: list[float], tail_q: float = 0.90) -> dict:
    """下层（< 分位 q）拟合指数分布，上层（≥ 分位 q）拟合 Pareto。

    返回各分支的 MLE 参数与 KS 统计量（越小越好）。
    这是"两阶级"统计结构的 qualitative 校准靶：
    真实收入数据呈下层指数、上尾幂律的双形态（Yakovenko 2009, RMP 81）。
    """
    w = np.asarray([max(0.0, x) for x in wealth], dtype=float)
    w = w[w > 0]
    if len(w) < 20:
        return {"n": len(w), "ok": False}
    q = np.quantile(w, tail_q)
    low = w[w < q]
    high = w[w >= q]
    out = {"n": int(len(w)), "ok": True, "xmin": float(q)}
    # 下层指数：MLE loc=0, scale=mean
    if len(low) >= 10 and low.mean() > 0:
        scale = float(low.mean())
        ks = stats.kstest(low / scale, "expon")
        out["exp_scale"] = scale
        out["exp_ks"] = float(ks.statistic)
    else:
        out["exp_scale"] = float("nan")
        out["exp_ks"] = float("nan")
    # 上层 Pareto：xmin=q, alpha = n / Σ ln(x/xmin)
    if len(high) >= 5 and q > 0:
        alpha = len(high) / float(np.sum(np.log(high / q)))
        if alpha > 0:
            ks = stats.kstest(high / q, "pareto", args=(alpha,))
            out["pareto_alpha"] = float(alpha)
            out["pareto_ks"] = float(ks.statistic)
        else:
            out["pareto_alpha"] = float("nan")
            out["pareto_ks"] = float("nan")
    else:
        out["pareto_alpha"] = float("nan")
        out["pareto_ks"] = float("nan")
    return out
