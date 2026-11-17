"""组合引擎：Agent 的"手"——四大确定性操作（无 LLM 依赖）。

- sweep(mid, param, values)         参数扫描：同一模型多组参数对照
- ensemble(mid, seeds, n)           多种子集成：均值/方差/收敛性
- compare(mid_a, mid_b, field)      跨模型对照：同口径观测量比较
- compose(steps, handoff)           流水线：前级终值字段 → 后级参数注入
"""
from __future__ import annotations

import numpy as np

from ..runtime import run_model_full, param_contract
from ..limits import validate_compute


def _numeric(observation):
    return {k: float(v) for k, v in observation.items() if k != "sim_t"
            and isinstance(v, (int, float)) and not isinstance(v, bool) and np.isfinite(v)}


def _execute(mid, parameters, ticks, seed, dt, persist, source):
    rr = run_model_full(mid, parameters=parameters, ticks=ticks, seed=seed,
                        dt=dt, strict=True, with_time=True, capture_state=persist)
    if persist:
        from ..run_store import get_store
        get_store().save_run(rr, source)
    return {"model_id": mid, "run_id": rr.manifest["run_id"],
            "params": rr.manifest["requested"]["parameters"], "manifest": rr.manifest,
            "observations": rr.observations, "final": _numeric(rr.observations[-1]),
            "state_url": f"/api/runs/{rr.manifest['run_id']}/state" if persist else None}


def sweep(mid, param, values, ticks=100, seed=None, parameters=None, dt=None,
          field=None, persist=False):
    """参数扫描：返回每组 values 的终值观测量 + 数值字段对照表。"""
    values = list(values)
    if not values:
        raise ValueError("参数扫描至少需要一个值")
    if param not in param_contract(mid)["params"]:
        raise ValueError(f"{mid} 无模型参数 {param}")
    validate_compute(ticks,runs=len(values),arms=len(values)-1,parameters=parameters)
    from ..research.compiler import _pick_metric
    selected=_pick_metric(mid,field)
    runs = []
    for v in values:
        run = _execute(mid, {**(parameters or {}), param: v}, ticks, seed, dt, persist, "sweep")
        runs.append({"value": v, **run})
    # 数值字段对照
    fields = sorted({k for r in runs for k in r["final"]})
    table = [{f: [r["final"].get(f) for r in runs] for f in fields}][0]
    if field and field not in fields:
        raise ValueError(f"请求观测量 {field} 不在模型输出中")
    return {"model_id": mid, "param": param, "values": values,
            "baseline_parameters": dict(parameters or {}), "seed": runs[0]["manifest"]["rng"]["seed"],
            "primary_metric": selected or None,
            "metric_choice_required":not bool(selected),
            "runs": runs, "table": table}


def ensemble(mid, seeds=(0, 1, 2, 3, 4), ticks=100, parameters=None, dt=None, persist=False):
    """多种子集成：每个数值观测量的均值/标准差/变异系数。"""
    parameters = parameters or {}
    seeds = list(seeds)
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("种子列表必须非空且不重复")
    validate_compute(ticks,runs=len(seeds),seeds=len(seeds),parameters=parameters)
    finals, runs = [], []
    for s in seeds:
        run = _execute(mid, parameters, ticks, s, dt, persist, "ensemble")
        runs.append({"seed": s, **run})
        finals.append(run["final"])
    fields = sorted({k for f in finals for k in f})
    stats = {}
    for f in fields:
        vals = np.array([f_.get(f, np.nan) for f_ in finals], float)
        vals = vals[np.isfinite(vals)]
        if len(vals) == 0:
            continue
        mean = float(vals.mean())
        std = float(vals.std(ddof=1)) if len(vals) > 1 else None
        stats[f] = {"mean": mean, "std": std,
                    "cv": float(std / abs(mean)) if std is not None and abs(mean) > 1e-12 else None,
                    "n_valid": int(len(vals))}
    return {"model_id": mid, "n_seeds": len(seeds), "seeds": seeds,
            "parameters": parameters, "stats": stats, "runs": runs}


def compare(mid_a, mid_b, field=None, ticks=100, seed=None, parameters_a=None,
            parameters_b=None, dt=None, persist=False):
    """跨模型对照：共同数值字段的并排终值与方向一致性。"""
    validate_compute(ticks,runs=2,arms=1,parameters=parameters_a)
    validate_compute(ticks,parameters=parameters_b)
    ra = _execute(mid_a, parameters_a, ticks, seed, dt, persist, "compare")
    rb = _execute(mid_b, parameters_b, ticks, seed, dt, persist, "compare")
    fa, fb = ra["final"], rb["final"]
    numeric_a = fa
    shared = sorted(set(numeric_a) & set({k for k, v in fb.items()
                                          if isinstance(v, (int, float))
                                          and not isinstance(v, bool)}))
    if field:
        shared = [f for f in shared if f == field]
    table = {f: {"a": numeric_a.get(f), "b": fb.get(f)} for f in shared}
    result = {"mid_a": mid_a, "mid_b": mid_b, "shared_fields": shared,
              "table": table, "runs": [ra, rb],
              "comparability_note": "共同字段按名称对照；结论仍须核对模型假设、量纲与口径，不代表现实因果比较"}
    if not shared:
        result["note"] = (f"{mid_a} 与 {mid_b} 无共同数值观测量，无法直接对照；"
                          "可改用 compose 流水线或分别 run 后人工解读")
    return result


def _norm_steps(steps):
    """归一化步骤格式：兼容 [{"model_id":..., "params":{...}}]、
    {"MID": {...}} 映射、以及 [(mid, params)] 元组列表。"""
    if isinstance(steps, dict):
        return [(mid, dict(p or {})) for mid, p in steps.items()]
    out = []
    for s in steps or []:
        if isinstance(s, dict):
            mid = s.get("model_id") or s.get("model")
            if not mid:
                raise ValueError(f"步骤缺少 model_id: {s!r}")
            out.append((mid, dict(s.get("params") or {})))
        elif isinstance(s, (list, tuple)) and len(s) == 2:
            out.append((s[0], dict(s[1] or {})))
        else:
            raise ValueError(f"无法解析步骤: {s!r}")
    return out


def compose(steps, handoff=None, ticks=100, seed=None, record_obs=False, dt=None, persist=False):
    """流水线组合：steps 见 _norm_steps（LLM 给 dict 列表也能跑）；
    handoff = {"from_field": "to_param"}：前级终值字段注入后级参数。
    共享种子/时钟；每级输出存档。步骤 params 里的 ticks 会覆盖全局 ticks。
    record_obs=True 时每级附带截断的观测序列（供前端 3D 可视化）。"""
    steps = _norm_steps(steps)
    handoff = handoff or {}
    if not steps:raise ValueError('流水线至少需要一个模型')
    from ..runtime import validate_run_arguments
    from ..research.semantics import port
    total=0
    for mid,params in steps:
        count=params.get('ticks',ticks)
        validate_run_arguments(count,.1 if dt is None else dt,0 if seed is None else seed)
        validate_compute(count,arms=len(steps)-1,parameters=params)
        total+=count
    from ..limits import limits,BudgetExceeded
    if total>limits().total_steps:raise BudgetExceeded('流水线总运行步数超过预算')
    outputs = []
    carry = {}
    for i, step in enumerate(steps):
        mid, params = step
        params = dict(params or {})
        step_ticks = params.pop("ticks", ticks)
        if i > 0 and handoff:
            mapping_trace=[]
            for src, mapping in handoff.items():
                dst=mapping.get('target') if isinstance(mapping,dict) else mapping
                if src in carry and dst:
                    if dst not in param_contract(mid)["params"]:
                        raise ValueError(f"映射目标 {mid}.{dst} 不是模型参数")
                    source_port=port(steps[i-1][0],src,'outputs')
                    target_port=port(mid,dst,'inputs')
                    if isinstance(mapping,dict):
                        declared={key:mapping.get(key) for key in ('unit','scope')}
                        if not all(declared.values()):raise ValueError('显式映射须声明unit与scope，不能从字段名猜测')
                        if any(p and p!=declared for p in (source_port,target_port)):
                            raise ValueError('显式单位/主体范围与模型端口合同不一致')
                        source_port=target_port=declared
                    if not source_port or source_port!=target_port:
                        raise ValueError(f'{src}→{mid}.{dst}缺少兼容单位及主体范围的显式端口合同')
                    params[dst] = carry[src]
                    mapping_trace.append({'source_model':steps[i-1][0],'source_field':src,'target_model':mid,
                        'target_parameter':dst,'value':carry[src],**source_port,
                        'source_t':outputs[-1]['manifest']['actual'].get('final_t'),
                        'target_phase':'initialization (independent stage clock)'})
                else:
                    raise ValueError(f"前级没有映射所需观测量 {src}")
        run = _execute(mid, params, step_ticks, seed, dt, persist, "compose")
        obs, numeric = run["observations"], run["final"]
        entry = {"step": i, "model_id": mid,
                 "params": params, "final": numeric, "run_id": run["run_id"],
                 "manifest": run["manifest"], "state_url": run["state_url"]}
        entry['mapping_trace']=mapping_trace if i>0 and handoff else []
        if record_obs:
            entry["observations"] = obs
        outputs.append(entry)
        carry = numeric
    return {"n_stages": len(steps), "handoff": handoff, "stages": outputs,
            "coupling_kind": "sequential_handoff",
            "coupling_note": "显式单位/主体范围合同下的顺序终值→初值传递；各级时钟独立，不等同于共享时钟反馈耦合"}
