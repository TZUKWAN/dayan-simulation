"""WP8 统一实验测试：程序分析正确性、配对随机流、时点干预、严格参数。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.research.specs import ExperimentSpec  # noqa: E402
from dayan.research.experiment import (run_experiment,  # noqa: E402
                                       analyze_observations)


def _mk_obs(metric_vals, metric="I", t0=0.0, dt=0.1):
    return [{"sim_t": round(t0 + i * dt, 9), metric: v}
            for i, v in enumerate(metric_vals)]


def run_tests():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name} {detail}")

    # ---- 1. 程序分析：已知序列 ----
    vals = [0, 1, 2, 3, 4, 5]
    st = analyze_observations(_mk_obs(vals), "I")
    check("分析：线性斜率=10/单位时间",
          abs(st["trend_slope_per_t"] - 10.0) < 1e-6,
          f"slope={st['trend_slope_per_t']}")
    check("分析：峰值与峰时", st["peak"] == 5.0 and abs(st["peak_t"] - 0.5) < 1e-9)
    check("分析：均值/首末", st["mean"] == 2.5 and st["first"] == 0 and st["last"] == 5)

    st2 = analyze_observations(_mk_obs(vals), "I", warmup=2)
    check("分析：预热期不计入", abs(st2["mean"] - 3.5) < 1e-12 and
          st2["first"] == 0, f"mean={st2['mean']}")

    st3 = analyze_observations(_mk_obs(vals), "I", window=[0.2, 0.4])
    check("分析：窗口裁剪", st3["n"] == 3 and st3["mean"] == 3.0,
          f"st3={st3}")

    st4 = analyze_observations([{"sim_t": 0.0, "x": 1}], "不存在指标")
    check("分析：缺指标如实报错", "error" in st4)

    # ---- 2. 配对实验 + 时点干预（SIS ODE，确定性） ----
    spec = ExperimentSpec(
        model_id="NET052",
        title="SIS 传播率干预",
        baseline_params={},
        arms=[{"label": "降beta30%",
               "interventions": [{"at_t": 1.0, "label": "干预",
                                  "params": {"beta": "*0.5"}}],
               "params": {}}],
        seeds=[0, 1],
        ticks=40, dt=0.1,
        primary_metric="I",
        purpose="policy",
    )
    spec.finalize()
    res = run_experiment(spec)
    check("实验：runs 数 = (1臂基线+1干预)×2种子 = 4", len(res.runs) == 4,
          f"n={len(res.runs)}")
    base_obs = res.observations["基线"]
    arm_obs = res.observations["降beta30%"]
    # 配对：干预前轨迹逐点一致（同 seed 同流）
    pre_t = 1.0
    pre_base = [o for o in base_obs[0] if o.get("sim_t", 9e9) <= pre_t]
    pre_arm = [o for o in arm_obs[0] if o.get("sim_t", 9e9) <= pre_t]
    check("配对随机流：干预前基线与臂轨迹一致",
          [o["I"] for o in pre_base] == [o["I"] for o in pre_arm])
    # 干预后分化且方向正确（降传播率 → I 更低）
    post_b = [o["I"] for o in base_obs[0] if o.get("sim_t", -1) >= 2.0]
    post_a = [o["I"] for o in arm_obs[0] if o.get("sim_t", -1) >= 2.0]
    check("干预后按机制分化（arm I < baseline I）",
          all(a < b for a, b in zip(post_a, post_b)) and post_a,
          f"post_b_tail={post_b[-1]:.4f} post_a_tail={post_a[-1]:.4f}")
    a = res.analysis
    check("分析：配对差为负", a["arms"]["降beta30%"]["paired_diff"]["mean"] < 0)
    check("分析：因果边界声明在场",
          "不构成现实因果识别" in a["causality_note"])
    check("分析：显著性边界声明在场",
          "不是现实被试样本" in a["significance_note"])
    iv = [r for r in res.runs if r["arm"] == "降beta30%"][0]["manifest"]["interventions"]
    check("干预记录：requested=actual=1.0",
          iv and iv[0]["applied"] and iv[0]["requested_t"] == 1.0
          and iv[0]["actual_t"] == 1.0, f"iv={iv}")

    # ---- 3. 严格模式拒绝未知参数 ----
    spec2 = ExperimentSpec(model_id="NET052", primary_metric="I",
                           baseline_params={"bogus": 1}, seeds=[0], ticks=10)
    spec2.finalize()
    try:
        run_experiment(spec2, strict=True)
        check("严格实验拒绝未知参数", False, "未抛出")
    except ValueError:
        check("严格实验拒绝未知参数", True)

    # ---- 4. 规约校验 ----
    bad = ExperimentSpec(model_id="", primary_metric="", seeds=[])
    check("ExperimentSpec 校验拦缺字段", len(bad.validate()) >= 3)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
