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


def analysis_time_series(rows):
    """Collapse identical saved states at the same timestamp without rewriting the archive."""
    clean = []
    for row in rows:
        time = row.get("sim_t")
        if not number(time) or (clean and time < clean[-1]["sim_t"]):
            raise ValueError("报告需要有限且按时间排序的实际观测")
        if clean and time == clean[-1]["sim_t"]:
            if row != clean[-1]:
                raise ValueError(f"同一归档时刻 {time:g} 含不同观测，时间顺序不明，不能给出时序结论")
            continue
        clean.append(row)
    return clean


def present_entities(frame):
    # The pedestrian engine keeps exit records at a sentinel coordinate for history.
    return [entity for entity in (frame or {}).get("entities", [])
            if not (entity.get("type") == "pedestrian" and entity.get("state") == "exited")]


def in_window(time, window):
    lower = time > window["from"] + 1e-9 if window["exclusive"] else time >= window["from"] - 1e-9
    return lower and time <= window["to"] + 1e-9


def metric_info(model_id, metric):
    if str(model_id).startswith("USR"):
        return {"name": metric, "unit": "原模型单位"}
    name, unit = NAMES.get(metric, metric), "原模型单位"
    if model_id == "NET122":
        from .research.semantics import port
        spec = port(model_id, metric, "outputs") or {}
        name = spec.get("label", name)
        unit = {"fraction": "比例", "cell": "格"}.get(spec.get("unit"), unit)
    if model_id == "NET106":
        unit = {"flux": "模型通量", "speed": "格/步", "n_cars": "辆", "density": "比例"}.get(metric, unit)
    if model_id == "NET052" and metric in ("I", "S"):
        name, unit = ("感染比例" if metric == "I" else "易感比例"), "比例"
    if model_id in ("NET114","NET121"):
        name, unit = {"speed": ("模型步速", "m/s"), "alive": ("在场人数", "人"),
                      "evacuated": ("累计疏散", "人"), "min_separation": ("最小行人间距", "m"),
                      "moving": ("移动人数", "人"), "waiting": ("停留人数", "人"),
                      "fallen": ("倒地待助人数", "人"), "assisted": ("处于受助状态人数", "人"),
                      "aid_completed": ("累计恢复人数", "人"), "yielding": ("降速规则作用人数", "人"),
                      "local_conflicts": ("几何相交对数", "对")}.get(metric, (name, unit))
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


def analyze_view(records, selected_id, metric=None, window=None, sim_t=None, entity_id=None, kind="run", entity_metric=None, distribution_field=None, distribution_region=None):
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
    per_run = []
    grouped = defaultdict(list)
    for record in records:
        values = [row[metric] for row in record["observations"] if in_window(row["sim_t"], normalized) and number(row.get(metric))]
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
    requested_time = sim_t if sim_t is not None else min(rows[-1]["sim_t"], normalized["to"])
    frames = selected.get("state_frames") or []
    frame = next((f for f in reversed(frames) if f["sim_t"] <= requested_time + 1e-9
                  and (sim_t is not None or in_window(f["sim_t"], normalized))), None)
    entities = present_entities(frame)
    departed = len(frame.get("entities", [])) - len(entities) if frame else 0
    distribution_entities = entities
    if distribution_region is not None:
        if (len(distribution_region) != 4 or not all(number(v) for v in distribution_region) or
                distribution_region[0] >= distribution_region[2] or distribution_region[1] >= distribution_region[3]):
            raise ValueError('选区需要四个从小到大的有限边界数值')
        x0,y0,x1,y1 = distribution_region
        bounds = (frame or {}).get('space', {}).get('bounds', [])
        distribution_entities = [e for e in entities if number(e.get('x')) and number(e.get('y')) and
            x0 <= e['x'] and (e['x'] <= x1 if len(bounds)==4 and x1==bounds[2] else e['x'] < x1) and
            y0 <= e['y'] and (e['y'] <= y1 if len(bounds)==4 and y1==bounds[3] else e['y'] < y1)]
    lattice = frame.get("lattice") if frame else None
    lattice_summary = None
    population = frame.get("population") if frame else None
    from .population_groups import is_grouped
    grouped_population = is_grouped(population)
    if lattice and population and not grouped_population:
        from .population import decode_column
        import numpy as np

        column = population["columns"][population["color_by"]]
        values = decode_column(column, population["count"])
        low, high = float(values.min()), float(values.max())
        binary = low in (0, 1) and high in (0, 1) and np.all((values == 0) | (values == 1))
        lattice_summary = {"width": population["grid"]["columns"], "height": population["grid"]["rows"],
                           "layers": [{"label": lattice["layers"][0]["label"],
                                       **({"state": "值为 1", "count": int(values.sum())} if binary else
                                          {"min": low, "max": high, "mean": float(values.mean())})}]}
    elif lattice and lattice.get('encoding') == 'u8-preview':
        lattice_summary = {key:lattice[key] for key in ('width','height','source_width','source_height')}
        lattice_summary.update(preview_only=True, layers=[{'label':layer['label']} for layer in lattice['layers']])
    elif lattice:
        lattice_summary = {"width": lattice["width"], "height": lattice["height"],
                           "layers": [{"label": layer["label"], "state": layer["states"][1],
                                       "count": layer["values"].count("1")} for layer in lattice["layers"]]}
    from .population import entity_trace
    trace = entity_trace(frames, entity_id, [entity_metric] if entity_metric else None) if entity_id else []
    if entity_id and not any('id' in item for item in trace):
        raise ValueError("归档没有所选主体的轨迹")
    if entity_metric and entity_id and not any(number(item.get(entity_metric)) for item in trace):
        raise ValueError("所选主体没有该数值属性")
    distribution = {}
    field = distribution_field or next((k for k in ("speed", "wealth", "income", "state", "group", "type") if entities and any(k in e for e in entities)), None)
    if population:
        from .population_analysis import distribution as population_distribution
        if grouped_population:
            field = distribution_field or next((group['id']+'.'+group['color_by']
                                                for group in population['groups'] if group.get('color_by')), 'group')
        else:
            field = field or population["color_by"]
        distribution = population_distribution(frame, field, distribution_region)
    elif distribution_field and entities and not any(number(e.get(field)) or isinstance(e.get(field),(str,bool)) for e in entities):
        raise ValueError("当前主体状态中没有所选分布字段")
    elif field and entities:
        values = [e[field] for e in distribution_entities if field in e and (number(e[field]) or isinstance(e[field], (str, bool)))]
        if values and all(number(x) for x in values):
            distribution = {"field": field, "n": len(values), "missing": len(distribution_entities)-len(values),
                            "min": min(values), "max": max(values), "mean": mean(values),
                            "zero_count": sum(x == 0 for x in values)}
        else:
            distribution = {"field": field, "n": len(values), "missing": len(distribution_entities)-len(values),
                            "counts": dict(Counter(str(x) for x in values))}
    return {"metric": metric, "metric_info": metric_info(selected["model_id"], metric), "window": normalized,
            "kind": kind, "per_run": per_run, "groups": groups, "comparisons": comparisons,
            "selected_run_id": selected_id, "requested_time": requested_time, "frame_explicit": sim_t is not None,
            "frame_time": frame["sim_t"] if frame else None, "entity_id": entity_id, "entity_metric": entity_metric,
            **({"entity_trace": trace} if entity_id else {}),
            "entity_count": population["count"] if population else len(entities),
            "departed_entities": departed, "distribution": distribution,
            **({"lattice": lattice_summary} if lattice_summary else {}),
            "distribution_field": distribution_field,
            "distribution_region": distribution_region,
            "run_ids": [r["run_id"] for r in records],
            "limitations": ["模型内数值比较，不自动构成现实因果识别或预测校准。",
                            "单种子不能判断跨种子稳健性；观测时点不是独立重复实验。",
                            "模型时间和量纲按原模型保留，不自动换算现实秒、小时或交通单位。"]}
