"""统一实验执行（WP8）：配对随机数对照、时点干预、程序先行的分析。

设计约束（方案 §7/§10/§20）：
- 基线与各实验臂共用同一 seed（配对随机流）：差异只来自处理；
- 程序先算统计（均值/趋势斜率/峰值/效应量/配对差），LLM 只做解释；
- 显著性表述与效应量分开；多次仿真重复不是现实被试样本；
- 模型内反事实比较 ≠ 现实因果识别（结果对象里如实声明）。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

import numpy as np

from ..runtime import run_model_full
from .specs import ExperimentSpec


@dataclass
class ExperimentResult:
    spec: ExperimentSpec
    runs: list = field(default_factory=list)      # 每 run 一条 {arm, seed, run_id, manifest}
    observations: dict = field(default_factory=dict)  # {arm_label: [obs_series per seed]}
    analysis: dict = field(default_factory=dict)
    warnings: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return bool(self.observations) and bool(self.analysis) and not self.analysis.get("error")


def analyze_observations(obs: list, metric: str, warmup: int = 0,
                         window: list | None = None) -> dict:
    """程序先行统计：窗口均值/趋势斜率/峰值/峰时/首末。不宣称显著性。"""
    series: list[float] = []
    ts: list[float] = []
    for o in obs:
        if not isinstance(o, dict):
            continue
        if metric not in o:
            continue
        v = o[metric]
        if isinstance(v, (int, float)) and np.isfinite(v):
            t = o.get("sim_t", len(ts))
            ts.append(float(t))
            series.append(float(v))
    if not series:
        return {"metric": metric, "error": "指标缺失于观测", "n": 0}
    if window and len(window) == 2:
        t0, t1 = float(window[0]), float(window[1])
        pairs = [(t, v) for t, v in zip(ts, series) if t0 <= t <= t1]
        if not pairs:
            return {"metric": metric, "error": "指定分析窗口内没有观测", "n": 0}
        ts, series = [p[0] for p in pairs], [p[1] for p in pairs]
    arr = np.asarray(series, dtype=float)
    if not isinstance(warmup, int) or warmup < 0 or warmup >= len(arr):
        return {"metric": metric, "error": "预热长度非法或已排除全部观测", "n": 0}
    n_warm = warmup
    eff = arr[n_warm:]
    t_arr = np.asarray(ts, dtype=float)[n_warm:]
    slope = float(np.polyfit(t_arr, eff, 1)[0]) if len(eff) >= 3 else None
    return {
        "metric": metric, "n": len(arr), "window": window or "全程",
        "mean": float(eff.mean()), "std": float(eff.std(ddof=1)) if len(eff) > 1 else 0.0,
        "min": float(eff.min()), "max": float(eff.max()),
        "first": float(arr[0]), "last": float(arr[-1]),
        "trend_slope_per_t": slope,
        "peak": float(eff.max()),
        "peak_t": float(t_arr[int(np.argmax(eff))]),
    }


def _agg(values: list[float]) -> dict:
    a = np.asarray(values, dtype=float)
    return {"per_seed": [float(x) for x in a],
            "mean": float(a.mean()) if len(a) else None,
            "std": float(a.std(ddof=1)) if len(a) > 1 else 0.0}


def run_experiment(spec: ExperimentSpec, strict: bool = True,
                   persist: bool = False) -> ExperimentResult:
    """执行实验：基线 + 各臂 × 各 seed（配对随机流）。"""
    from .specs import ExperimentSpec as _ES  # noqa: F401  (类型引用)
    result = ExperimentResult(spec=spec)
    issues = spec.validate()
    if issues:
        result.warnings.extend(issues)
        return result

    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    metric = spec.primary_metric
    window = spec.analysis_window or None
    arms = [{"label": "基线", "interventions": spec.baseline_interventions,
             "params": dict(spec.baseline_params)}]
    for a in spec.arms:
        arms.append({
            "label": a.get("label", f"臂{len(arms)}"),
            "interventions": list(spec.baseline_interventions) + a.get("interventions", []),
            "params": dict(a.get("params") or {}),
        })

    obs_by_arm: dict[str, list] = {}
    for arm in arms:
        obs_by_arm[arm["label"]] = []
        for seed in spec.seeds:
            rr = run_model_full(
                spec.model_id,
                parameters={**spec.baseline_params, **arm["params"]},
                ticks=spec.ticks, dt=spec.dt, seed=int(seed),
                experiment=spec.rng_domain, strict=strict,
                with_time=True,
                interventions=arm["interventions"], capture_state=persist,
                data_bindings=spec.data_bindings)
            if persist:
                from ..run_store import get_store
                get_store().save_run(rr, "experiment_run", spec.title + " · " + arm["label"])
            result.runs.append({
                "arm": arm["label"], "seed": int(seed),
                "run_id": rr.manifest.get("run_id"),
                "manifest": rr.manifest,
            })
            obs_by_arm[arm["label"]].append(rr.observations)
            if rr.issues:
                result.warnings.extend(
                    f"[{arm['label']} seed={seed}] {i.message}"
                    for i in rr.issues)
            if not rr.observations:
                result.warnings.append(
                    f"[{arm['label']} seed={seed}] 运行无观测")
    result.observations = obs_by_arm

    # ---- 程序先行分析 ----
    baseline_label = "基线"
    analysis: dict = {"metric": metric,
                      "model_id": spec.model_id,
                      "n_seeds": len(spec.seeds),
                      "paired_by_seed": True,
                      "causality_note": "模型内反事实比较，不构成现实因果识别",
                      "significance_note": "多次仿真重复不是现实被试样本；"
                                           "此处报告效应量与配对差，不宣称现实显著性"}
    base_stats = [analyze_observations(o, metric, spec.warmup_ticks, window)
                  for o in obs_by_arm.get(baseline_label, [])]
    good_base = [s for s in base_stats if "error" not in s]
    if not good_base:
        analysis["error"] = f"基线缺少指标 {metric}"
        result.analysis = analysis
        result.warnings.append(analysis["error"])
        return result
    if len(good_base) != len(spec.seeds):
        analysis["error"] = "部分基线种子缺少有效分析，配对实验不完整"
        result.analysis = analysis
        return result
    base_window_mean = _agg([s["mean"] for s in good_base])
    analysis["baseline"] = {
        "window_mean": base_window_mean,
        "trend_slope_per_t": _agg([s["trend_slope_per_t"] for s in good_base
                                   if s["trend_slope_per_t"] is not None]),
        "peak": _agg([s["peak"] for s in good_base]),
        "peak_t": _agg([s["peak_t"] for s in good_base]),
    }
    arms_out: dict = {}
    for arm in arms[1:]:
        stats = [analyze_observations(o, metric, spec.warmup_ticks, window)
                 for o in obs_by_arm.get(arm["label"], [])]
        good = [s for s in stats if "error" not in s]
        if len(good) != len(spec.seeds):
            analysis["error"] = f"臂 {arm['label']} 部分种子缺少指标或分析窗口数据，配对实验不完整"
            result.analysis = analysis
            return result
        arm_mean = _agg([s["mean"] for s in good])
        # 配对差：同 seed 基线 vs 臂
        paired = []
        for s_b, s_a in zip(base_stats, stats):
            if "error" not in s_b:
                paired.append(s_a["mean"] - s_b["mean"])
        pd_mean = float(np.mean(paired)) if paired else None
        pd_std = float(np.std(paired, ddof=1)) if len(paired) > 1 else None
        # Cohen's d（效应量，非显著性声明）
        d = None
        sd_pool = np.sqrt((base_window_mean["std"] ** 2 +
                           arm_mean["std"] ** 2) / 2.0) \
            if (base_window_mean["std"] or arm_mean["std"]) else None
        if sd_pool and sd_pool > 0 and pd_mean is not None:
            d = pd_mean / sd_pool
        arms_out[arm["label"]] = {
            "window_mean": arm_mean,
            "trend_slope_per_t": _agg([s["trend_slope_per_t"] for s in good
                                       if s["trend_slope_per_t"] is not None]),
            "peak": _agg([s["peak"] for s in good]),
            "paired_diff": {"mean": pd_mean, "std": pd_std, "n": len(paired)},
            "effect_rel": (pd_mean / base_window_mean["mean"])
            if base_window_mean["mean"] not in (0, 0.0) and pd_mean is not None
            else None,
            "cohens_d": d,
        }
    analysis["arms"] = arms_out
    analysis["baseline_window_mean"] = base_window_mean["mean"]
    result.analysis = analysis
    result.warnings.append("实验完成（模型内反事实对照；效应量见 analysis）")
    _ = started  # 保留字段位
    return result


def experiment_payload(result: ExperimentResult) -> dict:
    """The HTTP/UI/tool surfaces consume the same actual experiment record."""
    if not result.ok:
        raise ValueError("实验未完成: " + str(result.warnings))
    spec = result.spec
    baseline = result.observations.get("基线") or [[]]
    first = result.runs[0]
    return {"compiled": True, "model_id": spec.model_id,
            "experiment_id": spec.experiment_id, "experiment_spec": spec.to_dict(),
            "analysis": result.analysis, "warnings": result.warnings,
            "runs": result.runs, "n_runs": len(result.runs),
            "observations_by_arm": result.observations,
            "observations": baseline[0], "run_id": first["run_id"], "manifest": first["manifest"],
            "arm_observations": {key: series[0] for key, series in result.observations.items()
                                 if key != "基线" and series},
            "state_url": f"/api/runs/{first['run_id']}/state",
            "data_url": f"/api/runs/{spec.experiment_id}/bundle.zip"}
