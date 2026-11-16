"""Agent 工具合同（LLM 即插即用层）。

未来 LLM Agent 的 function-calling 工具集即本文件暴露的 tool_specs：
每个工具 = 名称 + 中文描述 + JSON 参数 schema + 纯函数实现（确定性）。
LLM 在环时只负责"选择工具+填参数"；执行永远走本文件（三主权：引擎管执行）。
"""
from __future__ import annotations

import json

from .composer import compare, compose, ensemble, sweep
from .metadata import load_capabilities, search_capabilities, filter_names
from ..model_index import ALL_INDEX, resolve, run_model


def _ok(payload):
    return {"ok": True, "payload": payload}


def _err(msg):
    return {"ok": False, "error": msg}


def tool_search_models(query="", has_param=None, observable=None):
    try:
        params,observables=filter_names(has_param),filter_names(observable)
        matches=search_capabilities(query=query,has_param=params,observable=observables)
        candidates=search_capabilities(query=query)[:5] if not matches and (params or observables) else []
        diagnostics=[{'model_id':c['model_id'],'missing_parameters':sorted(set(params)-{p['name'] for p in c['parameters']}),
                      'missing_observables':sorted(set(observables)-set(c['observables']))} for c in candidates]
        return _ok({'count':len(matches),'matches':matches,'query':query,'required_parameters':params,
                    'required_observables':observables,'filter_diagnostics':diagnostics,'candidates':candidates})
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_get_capabilities(model_id):
    model_id = _norm_mid(model_id)
    caps = load_capabilities()
    for c in caps:
        if c["model_id"] == model_id:
            return _ok(c)
    return _err(f"{model_id} 无能力卡")


def _clean_nan(obj):
    """递归清理 NaN/Inf/NumPy 标量 → JSON 兼容（np.float32 不清理会 500）。"""
    import math
    try:
        import numpy as np
        if isinstance(obj, np.floating):
            f = float(obj)
            return f if math.isfinite(f) else None
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
    except ImportError:
        pass
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {k: _clean_nan(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_clean_nan(v) for v in obj]
    return obj


def _coerce_ticks(ticks):
    """接受精确整数表示；越界、负数或小数明确拒绝，不自动裁剪。"""
    import math
    if isinstance(ticks, bool):
        raise ValueError("ticks 必须为整数")
    value = float(ticks)
    if not math.isfinite(value) or not value.is_integer() or not 0 <= value <= 10000:
        raise ValueError("ticks 必须为0–10000范围内整数，不会自动裁剪或替换")
    return int(value)


def _norm_mid(model_id):
    """模型 ID 归一：LLM/用户可能给小写或带空格（eco019 → ECO019）。"""
    return str(model_id).strip().upper() if model_id is not None else ""


def _coerce_values(values):
    """sweep 的 values 归一：容忍 "0.1,0.3" / "0.1 0.3" / 单数字字符串。"""
    if values is None:
        raise ValueError("values 不能为空")
    if isinstance(values, str):
        parts = [p for p in values.replace(",", " ").split() if p]
        vals = [float(p) for p in parts]
    elif isinstance(values, (list, tuple)):
        vals = []
        for v in values:
            if isinstance(v, (int, float)):
                vals.append(float(v))
            else:
                vals.append(float(str(v)))
    elif isinstance(values, (int, float)):
        vals = [float(values)]
    else:
        raise ValueError(f"values 类型不支持: {type(values).__name__}")
    if not vals:
        raise ValueError("values 为空")
    return vals


def _coerce_seeds(seeds):
    """ensemble 的 seeds 归一：容忍 "1,2,3" / 单个 int / 浮点整数值列表。"""
    if seeds is None:
        return (0, 1, 2, 3, 4)
    if isinstance(seeds, (int, float)):
        seeds = [seeds]
    if isinstance(seeds, str):
        parts = [p for p in seeds.replace(",", " ").split() if p]
        seeds = parts
    if isinstance(seeds, (list, tuple)):
        from decimal import Decimal, InvalidOperation
        try:
            values = [Decimal(str(s)) for s in seeds]
        except InvalidOperation as exc:
            raise ValueError("seed 不是有效整数") from exc
        if not values or len(values) > 50 or any(
                not s.is_finite() or s != s.to_integral_value() or not 0 <= s < 2 ** 64 for s in values):
            raise ValueError("seeds 必须为1–50个不重复的非负整数")
        result = tuple(int(s) for s in values)
        if len(set(result)) != len(result):
            raise ValueError("seeds 不能重复")
        return result
    raise ValueError(f"seeds 类型不支持: {type(seeds).__name__}")


def _check_params(model_id, parameters):
    """对照能力卡返回未知参数名列表（静默注入的披露）。"""
    if not parameters:
        return []
    caps = load_capabilities()
    known = set()
    for c in caps:
        if c["model_id"] == model_id:
            known = {p["name"] for p in c.get("parameters", [])
                     if isinstance(p, dict)}
            break
    if not known:
        return []
    return sorted(k for k in parameters if k not in known)


def tool_run(model_id, parameters=None, ticks=100, seed=None, dt=None, interventions=None, data_bindings=None):
    model_id = _norm_mid(model_id)
    if resolve(model_id)[0] is None:
        return _err(f"{model_id} 无运行工厂")
    parameters = parameters or {}
    try:
        # WP3/WP4/WP5：统一运行层（参数合同+单次初始化+manifest）
        from ..runtime import run_model_full
        rr = run_model_full(model_id, parameters=parameters,
                            ticks=_coerce_ticks(ticks), seed=seed, dt=dt,
                            with_time=True, capture_state=True, strict=True,
                            interventions=interventions, data_bindings=data_bindings)
        if not rr.observations:
            return _err(f"{model_id} 运行无观测："
                        + "; ".join(i.message for i in rr.issues)[:200])
        from ..run_store import get_store
        get_store().save_run(rr, "agent")
        payload = {"model_id": model_id, "n": len(rr.observations),
                   "observations": _clean_nan(rr.observations),
                   "run_id": rr.manifest.get("run_id"),
                   "state_url": f"/api/runs/{rr.manifest['run_id']}/state",
                   "data_url": f"/api/runs/{rr.manifest['run_id']}/observations.csv",
                   "manifest": rr.manifest,
                   "warnings": rr.manifest.get("warnings", [])}
        ignored = [i.param for i in rr.issues if i.kind == "unknown"]
        if ignored:
            payload["ignored_params"] = ignored
        return _ok(payload)
    except ValueError as e:
        # 严格校验失败或参数类型不可救——如实报错而非静默降级
        return _err(f"ValueError: {e}")
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_sweep(model_id, param, values, ticks=100, parameters=None, seed=None, dt=None, field=None):
    model_id = _norm_mid(model_id)
    try:
        payload = _clean_nan(sweep(model_id, param, _coerce_values(values),
                                   ticks=_coerce_ticks(ticks), parameters=parameters,
                                   seed=seed, dt=dt, field=field, persist=True))
        from ..run_store import get_store
        get_store().save_analysis("sweep", payload)
        return _ok(payload)
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_ensemble(model_id, seeds=None, parameters=None, ticks=100, dt=None):
    model_id = _norm_mid(model_id)
    try:
        payload = _clean_nan(ensemble(model_id, seeds=_coerce_seeds(seeds),
                            ticks=_coerce_ticks(ticks), parameters=parameters, dt=dt, persist=True))
        from ..run_store import get_store
        get_store().save_analysis("ensemble", payload)
        return _ok(payload)
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_compare(mid_a, mid_b, field=None, ticks=100, parameters_a=None, parameters_b=None,
                 seed=None, dt=None):
    try:
        payload = _clean_nan(compare(_norm_mid(mid_a), _norm_mid(mid_b),
                                      field=field, ticks=_coerce_ticks(ticks), seed=seed, dt=dt,
                                      parameters_a=parameters_a, parameters_b=parameters_b, persist=True))
        from ..run_store import get_store
        get_store().save_analysis("compare", payload)
        return _ok(payload)
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_compose(steps, handoff=None, ticks=100, seed=None, dt=None):
    try:
        payload = _clean_nan(compose(steps, handoff=handoff, ticks=_coerce_ticks(ticks),
                                      record_obs=True, seed=seed, dt=dt, persist=True))
        from ..run_store import get_store
        get_store().save_analysis("compose", payload)
        return _ok(payload)
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_experiment(query, ticks=None, seeds=None, purpose=None, dt=None,
                    model_id=None, parameters=None, interventions=None,
                    metric=None, last_run=None, seed=None, data_bindings=None):
    """研究实验（WP6/WP8）：需求编译 → 候选披露 → 配对种子对照实验 →
    程序先行分析。无运行候选时如实返回缺口，不硬套模型。"""
    try:
        from ..research import compile_research, run_experiment
        seed_list = list(_coerce_seeds(seeds if seeds is not None else seed))
        cr = compile_research(query, purpose=purpose, ticks=ticks,
                              seeds=seed_list, dt=dt, model_id=model_id,
                              parameters=parameters, interventions=interventions,
                              metric=metric, last_run=last_run)
        es = cr.experiment_spec
        if es is None:
            return {"ok": False, "error": "需求尚未形成可执行实验: " + "; ".join(cr.warnings), "payload": {
                "compiled": False,
                "research_spec": cr.research_spec.to_dict(),
                "candidates": cr.candidates,
                "warnings": cr.warnings, "notes": cr.notes,
                "message": "无可运行候选——已产出研究规约与候选披露，"
                           "未虚构实验（见 warnings/unsupported）",
            }}
        if data_bindings is not None:
            es.data_bindings = list(data_bindings)
        res = run_experiment(es, strict=True, persist=True)
        if not res.ok or res.analysis.get("error"):
            return _err("实验未完成: " + str(res.analysis.get("error") or res.warnings))
        from ..run_store import get_store
        get_store().save_experiment(res, query, cr.research_spec.to_dict())
        # 面向 LLM/前端的紧凑载荷：分析 + 基线与各臂首种子观测序列
        payload = {
            "compiled": True,
            "model_id": es.model_id,
            "experiment_id": es.experiment_id,
            "research_id": cr.research_spec.research_id,
            "research_spec": cr.research_spec.to_dict(),
            "candidates": cr.candidates,
            "experiment_spec": es.to_dict(),
            "analysis": res.analysis,
            "warnings": cr.warnings + res.warnings,
            "notes": cr.notes,
            "n_runs": len(res.runs),
            "runs": res.runs,
            "observations_by_arm": _clean_nan(res.observations),
            "data_url": f"/api/runs/{es.experiment_id}/bundle.zip",
        }
        base = res.observations.get("基线") or []
        if base:
            payload["observations"] = _clean_nan(base[0])
            first = res.runs[0]
            payload["run_id"] = first["run_id"]
            payload["manifest"] = first["manifest"]
        arms_obs = {lbl: _clean_nan((sers[0] if sers else []))
                    for lbl, sers in res.observations.items()
                    if lbl != "基线"}
        if arms_obs:
            payload["arm_observations"] = arms_obs
        return _ok(payload)
    except Exception as e:                                 # noqa: BLE001
        return _err(f"{type(e).__name__}: {e}")


def tool_resume(run_id,ticks=100,dt=None):
    try:
        from ..run_store import resume_saved_run
        return _ok(resume_saved_run(run_id,_coerce_ticks(ticks),dt))
    except (ValueError,KeyError,FileNotFoundError) as exc:return _err(str(exc))


TOOL_IMPL = {
    "search_models": tool_search_models,
    "get_capabilities": tool_get_capabilities,
    "run": tool_run,
    "resume":tool_resume,
    "sweep": tool_sweep,
    "ensemble": tool_ensemble,
    "compare": tool_compare,
    "compose": tool_compose,
    "experiment": tool_experiment,
}
from .data_tools import collect_data, analyze_data
TOOL_IMPL.update(collect_data=collect_data, analyze_data=analyze_data)
from .model_tools import build_model
TOOL_IMPL["build_model"] = build_model
from .explain import explain
TOOL_IMPL["explain"] = explain
from .data_tools import (search_sources, list_presets, run_preset,
                          collection_status, build_data_requirement,
                          build_collection_plan, execute_plan,
                          check_data_quality, calibrate_model, collect_source, cancel_collection, import_collection,
                          research_create, research_calibrate, research_report, research_status)
TOOL_IMPL.update(search_sources=search_sources, list_presets=list_presets,
                  run_preset=run_preset, collection_status=collection_status,
                  build_data_requirement=build_data_requirement,
                  build_collection_plan=build_collection_plan,
                  execute_plan=execute_plan,
                  check_data_quality=check_data_quality,
                  calibrate_model=calibrate_model, collect_source=collect_source, cancel_collection=cancel_collection,
                  import_collection=import_collection, research_create=research_create, research_calibrate=research_calibrate,
                  research_report=research_report, research_status=research_status)



def _tool_specs():
    import inspect
    strings = {"query", "request", "model_id", "run_id", "mid_a", "mid_b", "param", "field", "purpose", "metric", "url", "path", "name", "format", "license", "role", "dataset_id", "theme", "state", "preset_id", "variable_name", "unit", "model_fn_src", "question", "collection_id", "study_id", "model_family", "kind", "connector"}
    objects = {"parameters", "parameters_a", "parameters_b", "handoff", "definition", "last_run", "values", "requirement", "plan", "param_grid", "params"}
    arrays = {"values", "seeds", "interventions", "steps", "data_bindings", "bbox", "history", "variables", "calibration_records", "holdout_records"}
    descriptions = {
        "search_models":"检索真实模型能力。query用简短关键词；has_param只放构造参数名（如beta、gamma），observable放观测字段（如S、I、R），都支持名称列表或逗号字符串。不清楚字段时先只用query；零结果会说明缺失字段并列出未满足筛选的候选，候选不能当作已满足筛选。",
        "resume":"从真实run_id完整检查点追加ticks步，恢复主体、模型时间和随机流；不从头重跑冒充继续。",
        "explain":"只读解释用户问题或当前真实归档结果，last_run传真实run_id；不重新运行模型或改变场景。",
        "build_model": "根据原始request调用真实LLM生成安全可执行DSL新模型，或提供definition；注册后真实运行，返回定义、run_id和同源状态。不是只选目录模型。",
        "collect_data": "真实采集公开HTTPS URL、导入项目内CSV/JSON文件path，或bbox=[南,西,北,东]采集OSM道路；三者只选一。保存原始文件与来源哈希。",
        "analyze_data": "分析真实归档数据集，path指定JSON记录列表的点分路径（世界银行结果用1）。",
        "experiment": "按原始query的确切参数、种子、干预时间/幅度编译并真实执行配对实验；不自动插入模板干预。",
        "run": "用统一引擎实际运行；data_bindings=[{dataset_id,path,field,aggregate,parameter,scale}]把真实数据显式映射到参数。",
        "compose": "顺序终值传递；不等于同一时钟的反馈耦合。",
        "search_sources": "按主题词检索45源可行性矩阵，返回来源状态/许可/认证/最后检查时间。state参数过滤：live/needs_auth/down/candidate等。",
        "list_presets": "列出12个主题采集预设（人口就业/SDG/欧洲/劳动/卫生/教育/文献/门户/新闻/历史等），每个含占位符说明。",
        "run_preset": "按预设ID执行真实采集。values传占位符值（indicator/country/year_from等），地区别名自动映射（中国→CHN）。",
        "collection_status": "查询采集任务状态：pages哈希、n_records、partial标记、记录预览。",
        "build_data_requirement": "构建数据需求规约：variables=[{name,concept,unit,purpose,geo_level,time_range,min_records}]。purpose必须是calibration/holdout_validation/exogenous_input等。",
        "build_collection_plan": "从DataRequirement自动生成采集计划（按概念词路由到连接器）。返回steps数组可直接传execute_plan。",
        "execute_plan": "逐步执行采集计划：真实网络请求+原始快照+partial标记。返回每步的collection_id。",
        "check_data_quality": "对采集记录做质量检查：覆盖率/缺失率/时间范围/地域分布/单位。返回issues列表。",
        "calibrate_model": "网格搜索校准：model_fn_src是lambda表达式（受限求值），param_grid是{参数名:[候选值]}，observations=[{date,value}]。可选holdout_records做留出验证。",
    }
    specs = []
    for name, fn in TOOL_IMPL.items():
        properties, required = {}, []
        for key, parameter in inspect.signature(fn).parameters.items():
            if parameter.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL): continue
            typ = "string" if key in strings else "object" if key in objects else "array" if key in arrays else "integer" if key in ("ticks", "seed", "page_budget", "min_records", "holdout_years", "budget", "forecast_years") else "number" if key in ("dt", "tolerance") else None
            item = {"type": typ} if typ else {}
            if key in ('has_param','observable'):
                item={'anyOf':[{'type':'array','items':{'type':'string'},'maxItems':32},{'type':'string'},{'type':'null'}],
                      'description':'必须同时具备的精确'+('构造参数名；S/I/R这类仓室观测请用observable' if key=='has_param' else '观测字段名；R与R0是不同字段')}
            if parameter.default is None and typ:
                item["type"] = [typ, "null"]
            if key in ("ticks", "seed"):
                item["minimum"] = 0
                item["maximum"] = 10000 if key == "ticks" else 2**64-1
            if key == "dt":
                item["exclusiveMinimum"] = 0
            if key == "purpose" and name == "experiment":
                item["enum"] = ["teaching", "mechanism", "explanatory", "policy", "prediction", None]
            if key in ("values", "seeds", "bbox") and typ == "array":
                item["items"] = {"type": "integer" if key == "seeds" else "number"}
            if parameter.default is inspect.Parameter.empty:
                required.append(key)
            properties[key] = item
        specs.append({"name": name, "description": descriptions.get(name, (fn.__doc__ or name).strip()),
                      "parameters": {"type": "object", "properties": properties,
                                     "required": required, "additionalProperties": False}})
    return specs


TOOL_SPECS = _tool_specs()

def call_tool(name, **kwargs):
    """Agent 唯一执行入口：名称 + 参数 → 结果（JSON 可序列化）。"""
    if name not in TOOL_IMPL:
        return _err(f"未知工具 {name}（可用: {sorted(TOOL_IMPL)}）")
    return TOOL_IMPL[name](**kwargs)


def tool_manifest():
    """给 LLM 的工具清单（JSON 可序列化）。"""
    return json.dumps(TOOL_SPECS, ensure_ascii=False, indent=1)
