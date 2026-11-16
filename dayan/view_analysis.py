"""Analysis of an explicitly selected view of immutable saved runs.

Client values select a metric/window/frame; all reported results come from archives.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import math
from statistics import mean

NAMES = {"flux": "交通通量", "density": "车辆密度", "n_cars": "车辆数", "speed": "速度",
         "I": "感染量 I", "S": "易感量 S", "gini": "基尼系数", "evacuated": "累计疏散",
         "arrived": "累计到达", "waiting": "等待人数", "k": "人均资本", "wealth": "财富", "income": "收入"}


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def metric_info(model_id, metric):
    name, unit = NAMES.get(metric, metric), "原模型单位"
    if model_id == "NET106":
        unit = {"flux": "模型通量", "speed": "格/步", "n_cars": "辆", "density": "比例"}.get(metric, unit)
    if model_id == "NET052" and metric in ("I", "S"):
        name, unit = ("感染比例" if metric == "I" else "易感比例"), "比例"
    return {"name": name, "unit": unit}


def intervention_time(records):
    baseline = next((r for r in records if r.get("view_group") == "基线"), records[0])
    def signature(iv):
        return (iv.get("requested_t"), repr(sorted(iv.get("params", {}).items())))
    common = {signature(iv) for iv in baseline.get("manifest", {}).get("interventions", []) if iv.get("applied")}
    times = [iv["actual_t"] for r in records for iv in r.get("manifest", {}).get("interventions", [])
             if iv.get("applied") and number(iv.get("actual_t"))
             and (len(records) == 1 or signature(iv) not in common)]
    return min(times) if times else None


def analyze_view(records, selected_id, metric=None, window=None, sim_t=None, entity_id=None, kind="run", entity_metric=None, distribution_field=None):
    selected = next((r for r in records if r["run_id"] == selected_id), None)
    if selected is None:
        raise ValueError("所选运行不属于报告数据")
    rows = selected["observations"]
    available = [key for row in rows for key, value in row.items() if key != "sim_t" and number(value)]
    if not available:
        raise ValueError("归档没有可分析的数值指标")
    metric = metric or next((k for k in ("flux", "I", "I_total", "gini", "evacuated", "k") if k in available), available[0])
    if metric not in available:
        raise ValueError("所选运行没有可分析的该指标")
    start = min(r["observations"][0]["sim_t"] for r in records)
    end = max(r["observations"][-1]["sim_t"] for r in records)
    raw = dict(window or {})
    mode = raw.get("mode", "custom" if raw else "all")
    if mode == "all":
        normalized = {"from": start, "to": end, "exclusive": False, "mode": "all"}
    elif mode == "post":
        t = intervention_time(records)
        if t is None:
            raise ValueError("归档没有可用于干预后比较的干预记录")
        normalized = {"from": t, "to": end, "exclusive": True, "mode": "post"}
    elif mode == "custom":
        a, b = raw.get("from"), raw.get("to")
        if not number(a) or not number(b) or a > b or a < start or b > end:
            raise ValueError("分析窗口须在归档时间范围内，且起点不晚于终点")
        normalized = {"from": a, "to": b, "exclusive": False, "mode": "custom"}
    else:
        raise ValueError("不支持的分析窗口类型")
    def in_window(row):
        t = row["sim_t"]
        return (t > normalized["from"] + 1e-9 if normalized["exclusive"] else t >= normalized["from"] - 1e-9) and t <= normalized["to"] + 1e-9
    per_run = []
    grouped = defaultdict(list)
    for record in records:
        values = [row[metric] for row in record["observations"] if in_window(row) and number(row.get(metric))]
        item = {"run_id": record["run_id"], "label": record.get("view_label", record["model_id"]),
                "group": record.get("view_group", record.get("view_label", record["model_id"])),
                "seed": record.get("view_seed", record.get("manifest", {}).get("rng", {}).get("seed")),
                "n": len(values), "mean": mean(values) if values else None,
                "first": values[0] if values else None, "last": values[-1] if values else None}
        per_run.append(item)
        grouped[item["group"]].append(item)
    selected_summary = next(x for x in per_run if x["run_id"] == selected_id)
    if selected_summary["mean"] is None:
        raise ValueError("所选运行在分析窗口内没有该指标的观测")
    groups = [{"name": name, "n": sum(number(x["mean"]) for x in items),
               "mean": mean([x["mean"] for x in items if number(x["mean"])]) if any(number(x["mean"]) for x in items) else None,
               "observations_per_run": [x["n"] for x in items]} for name, items in grouped.items()]
    baseline = next((g for g in groups if g["name"] == "基线"), groups[0])
    comparisons = []
    for group in groups:
        if group is baseline:
            continue
        pairs = []
        if kind == "experiment":
            for arm in grouped[group["name"]]:
                base = next((x for x in grouped[baseline["name"]] if x["seed"] == arm["seed"]), None)
                if base and number(base["mean"]) and number(arm["mean"]):
                    pairs.append((base["mean"], arm["mean"]))
        if pairs:
            difference, denominator = mean([b-a for a,b in pairs]), mean([a for a,b in pairs])
        elif number(group["mean"]) and number(baseline["mean"]):
            difference, denominator = group["mean"]-baseline["mean"], baseline["mean"]
        else:
            difference, denominator = None, None
        comparisons.append({"group": group["name"], "baseline": baseline["name"], "paired_n": len(pairs),
                            "difference": difference, "relative": difference/denominator if denominator and difference is not None else None})
    if sim_t is not None and (not number(sim_t) or sim_t < rows[0]["sim_t"] or sim_t > rows[-1]["sim_t"]):
        raise ValueError("报告观察时点须在所选运行范围内")
    requested_time = sim_t if sim_t is not None else rows[-1]["sim_t"]
    frames = selected.get("state_frames") or []
    frame = next((f for f in reversed(frames) if f["sim_t"] <= requested_time + 1e-9), None)
    entities = frame.get("entities", []) if frame else []
    if entity_id and not any(str(e.get("id")) == entity_id for f in frames for e in f.get("entities", [])):
        raise ValueError("归档没有所选主体的轨迹")
    if entity_metric and entity_id and not any(number(e.get(entity_metric)) for f in frames for e in f.get("entities", []) if str(e.get("id"))==entity_id):
        raise ValueError("所选主体没有该数值属性")
    distribution = {}
    field = distribution_field or next((k for k in ("speed", "wealth", "income", "state", "group", "type") if entities and any(k in e for e in entities)), None)
    if distribution_field and entities and not any(number(e.get(field)) or isinstance(e.get(field),(str,bool)) for e in entities):
        raise ValueError("当前主体状态中没有所选分布字段")
    if field:
        values = [e[field] for e in entities if field in e and (number(e[field]) or isinstance(e[field], (str, bool)))]
        if values and all(number(x) for x in values):
            distribution = {"field": field, "n": len(values), "missing": len(entities)-len(values),
                            "min": min(values), "max": max(values), "mean": mean(values),
                            "zero_count": sum(x == 0 for x in values)}
        else:
            distribution = {"field": field, "n": len(values), "missing": len(entities)-len(values),
                            "counts": dict(Counter(str(x) for x in values))}
    return {"metric": metric, "metric_info": metric_info(selected["model_id"], metric), "window": normalized,
            "kind": kind, "per_run": per_run, "groups": groups, "comparisons": comparisons,
            "selected_run_id": selected_id, "requested_time": requested_time,
            "frame_time": frame["sim_t"] if frame else None, "entity_id": entity_id, "entity_metric": entity_metric,
            "entity_count": len(entities), "distribution": distribution,
            "run_ids": [r["run_id"] for r in records],
            "limitations": ["模型内数值比较，不自动构成现实因果识别或预测校准。",
                            "单种子不能判断跨种子稳健性；观测时点不是独立重复实验。",
                            "模型时间和量纲按原模型保留，不自动换算现实秒、小时或交通单位。"]}
