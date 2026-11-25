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


def tool_get_capabilities(model_id=None):
    if model_id is None:
        from ..engine_capabilities import method_inventory
        return method_inventory()
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
    return _archive_run(model_id,parameters,ticks,seed,dt,interventions,data_bindings)


def _archive_run(model_id, parameters, ticks, seed, dt, interventions, data_bindings, *, review=None, acceptance=None,
                 full_frames=False, checkpoint=None, llm_calls=None):
    from .verification import RunVerificationError, certify_run
    from .build_checkpoint import accepted_run
    from .design_checkpoint import PendingStage
    model_id = _norm_mid(model_id)
    if resolve(model_id)[0] is None:
        return _err(f"{model_id} 无运行工厂")
    parameters = parameters or {}
    try:
        # WP3/WP4/WP5：统一运行层（参数合同+单次初始化+manifest）
        from ..runtime import run_model_full
        def execute(progress=None):
            return run_model_full(model_id, parameters=parameters,
                                  ticks=_coerce_ticks(ticks), seed=seed, dt=dt,
                                  with_time=True, capture_state=True, strict=True,
                                  interventions=interventions, data_bindings=data_bindings, full_frames=full_frames,
                                  _progress=progress)

        def certify(rr):
            if llm_calls is not None:
                from .build_checkpoint import attach_authoring_audit
                attach_authoring_audit(rr, llm_calls)
            if acceptance:
                certify_run(rr, review, acceptance)
            elif review:
                rr.manifest['scenario_review']=review

        rr = accepted_run(model_id, execute, certify, "agent", checkpoint=checkpoint)
        payload = {"model_id": model_id, "n": len(rr.observations),
                   "observations": _clean_nan(rr.observations),
                   "run_id": rr.manifest.get("run_id"),
                   "state_url": f"/api/runs/{rr.manifest['run_id']}/state",
                   "data_url": f"/api/runs/{rr.manifest['run_id']}/observations.csv",
                   **({"scale": rr.manifest["scale"], "bundle_url": f"/api/runs/{rr.manifest['run_id']}/bundle.zip"}
                      if "scale" in rr.manifest else {}),
                   "manifest": rr.manifest,
                   "warnings": rr.manifest.get("warnings", [])}
        ignored = [i.param for i in rr.issues if i.kind == "unknown"]
        if ignored:
            payload["ignored_params"] = ignored
        return _ok(payload)
    except PendingStage:
        raise
    except RunVerificationError as exc:
        return {**_err(f"运行未通过事前验收：{exc}"), "verification": exc.receipt}
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


def tool_ensemble(model_id, seeds=None, parameters=None, ticks=100, dt=None, data_bindings=None, interventions=None, *,
                  _certify=None, _full_frames=False, _checkpoint=None):
    from .design_checkpoint import PendingStage
    model_id = _norm_mid(model_id)
    try:
        if _checkpoint:
            saved = _checkpoint.recover("ensemble", analysis=True)
            if saved:
                return _ok(saved["analysis"])
        payload = _clean_nan(ensemble(model_id, seeds=_coerce_seeds(seeds),
                                  ticks=_coerce_ticks(ticks), parameters=parameters, dt=dt, persist=True, certify=_certify,
                                  interventions=interventions, data_bindings=data_bindings, full_frames=_full_frames,
                                  checkpoint=_checkpoint))
        from ..run_store import get_store
        if _checkpoint:
            payload["continuation"] = _checkpoint.archive_marker("ensemble")
        get_store().save_analysis("ensemble", payload,
                                 record_id=_checkpoint.reserve("ensemble", analysis=True)["record_id"] if _checkpoint else None)
        if _checkpoint:
            _checkpoint.committed("ensemble")
        return _ok(payload)
    except PendingStage:
        raise
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


def tool_experiment(query=None, ticks=None, seeds=None, purpose=None, dt=None,
                    model_id=None, parameters=None, interventions=None,
                    metric=None, last_run=None, seed=None, data_bindings=None,
                    baseline_run_id=None,arms=None,analysis_window=None):
    """研究实验（WP6/WP8）：需求编译 → 候选披露 → 配对种子对照实验 →
    程序先行分析。无运行候选时如实返回缺口，不硬套模型。"""
    try:
        if baseline_run_id is not None:
            from ..research.reviewed_experiments import run_reviewed_experiment
            return _ok(run_reviewed_experiment(query,baseline_run_id,arms=arms,metric=metric,
                seeds=seeds,seed=seed,ticks=ticks,dt=dt,model_id=model_id,parameters=parameters,
                interventions=interventions,data_bindings=data_bindings,analysis_window=analysis_window,purpose=purpose))
        if arms is not None or analysis_window is not None:
            raise ValueError('自建模型显式对照须提供已审且实际执行的baseline_run_id')
        if not isinstance(query,str) or not query.strip():raise ValueError('experiment须提供实际query或已审基线')
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
from .model_tools import DSL_CONTRACT, build_model, design_model, validate_model
TOOL_IMPL.update(design_model=design_model, build_model=build_model, validate_model=validate_model)
from .scenario_tools import modeling_guide, reviewed_run, report_run
TOOL_IMPL.update(modeling_guide=modeling_guide, reviewed_run=reviewed_run, report_run=report_run)
from ..engine_capabilities import method_inventory
TOOL_IMPL["execution_capabilities"] = method_inventory
from ..research.global_sensitivity import tool_global_sensitivity
TOOL_IMPL['global_sensitivity'] = tool_global_sensitivity
from ..research.capacity_planner import tool_plan_capacity
TOOL_IMPL['plan_capacity'] = tool_plan_capacity
from ..research.model_memory import tool_memory_feedback
TOOL_IMPL['memory_feedback'] = tool_memory_feedback
from .explain import explain
TOOL_IMPL["explain"] = explain
from .data_tools import (search_sources, list_presets, run_preset,
                          collection_status, build_data_requirement,
                          build_collection_plan, execute_plan,
                          check_data_quality, calibrate_model, collect_source, cancel_collection, import_collection,
                          research_create, research_model_prepare, research_model_context, research_model_create, research_calibrate, research_finalize, research_report, research_status, collect_census_scene)
TOOL_IMPL.update(search_sources=search_sources, list_presets=list_presets,
                  run_preset=run_preset, collection_status=collection_status,
                  build_data_requirement=build_data_requirement,
                  build_collection_plan=build_collection_plan,
                  execute_plan=execute_plan,
                  check_data_quality=check_data_quality,
                  calibrate_model=calibrate_model, collect_source=collect_source, cancel_collection=cancel_collection,
                  import_collection=import_collection, research_create=research_create, research_calibrate=research_calibrate,
                  research_model_prepare=research_model_prepare,research_model_context=research_model_context,research_model_create=research_model_create,research_finalize=research_finalize,research_report=research_report, research_status=research_status,
                  collect_census_scene=collect_census_scene)



def _tool_specs():
    import inspect
    strings = {"query", "request", "model_id", "run_id", "experiment_id", "analysis_id", "mid_a", "mid_b", "param", "field", "purpose", "metric", "url", "path", "name", "format", "license", "role", "dataset_id", "theme", "state", "preset_id", "variable_name", "unit", "model_fn_src", "question", "collection_id", "study_id", "model_family", "kind", "connector"}
    strings.add("design_id")
    strings.add("revise_from")
    strings.add('research_intent_id')
    strings.add('baseline_run_id')
    objects = {"parameters", "parameters_a", "parameters_b", "handoff", "definition", "last_run", "values", "requirement", "plan", "param_grid", "params", "parse_options"}
    arrays = {"values", "seeds", "interventions", "steps", "data_bindings", "bbox", "history", "variables", "calibration_records", "holdout_records",'arms','analysis_window'}
    descriptions = {
        "get_capabilities": "不填model_id时返回系统实际计算能力与边界；传真实model_id时仅返回该模型的参数和观测合同。未知型号不替换。新建DSL的字段和表达式规范用schema(build_model)。",
        "execution_capabilities": "查询大衍当前实际模型工厂、计算方法、数据适配与运行预算。需要针对原文选型时用 modeling_guide。",
        "modeling_guide": "根据原文查执行能力、缺口和数据预设。普通新研究先自建，指定型号和专用求解需求可查原生适配。DSH 从当前原生用户消息取原文。",
        "reviewed_run": "按 modeling_guide 的适配候选做方案比较、缺陷审查及真实执行。原文自动取得。模型不覆盖、关键缺陷未解和事前数值条件失败时均不会产生通过回执。真实数据由 data_bindings 实际绑定。仅原文明示接受子范围时才使用 allow_partial。",
        "report_run": "输入实际run_id生成同源Word和事实JSON，包含建模依据、数学表达、图表、结果分析和主要发现。整组对照/多种子报告同时传实际experiment_id或analysis_id（二选一），读取同组全部真实成员；run_id仅选定场景成员。校准研究用research_report。",
        "search_models":"检索真实模型能力。query用简短关键词；has_param只放构造参数名（如beta、gamma），observable放观测字段（如S、I、R），都支持名称列表或逗号字符串。不清楚字段时先只用query；零结果会说明缺失字段并列出未满足筛选的候选，候选不能当作已满足筛选。",
        "resume":"从真实run_id完整检查点追加ticks步，恢复主体、模型时间和随机流；不从头重跑冒充继续。",
        "explain":"只读解释用户问题或当前真实归档结果，last_run传真实run_id；不重新运行模型或改变场景。",
        "design_model": "以真实LLM独立构思、在线文献研究、审查缺陷、修正、编制方案与独立审核。parameters通常省略，只放已确定的运行取值。pending直接按next_action续接同一design_id和设置，不自行等待或另起方案。获批后默认build_model(design_id=同号)让平台按该方案编译，不另行发明第二份模型。历史运行仅作参考。",
        "build_model": "从审查通过的同一方案创建并运行DSL或kind=program受管Python模型。默认传获批design_id、保留运行设置并省略definition，由平台按完整方案生成实现。pending直接沿next_action续接；已归档成员不重算。也可传request自动审查与构建。需要自行实现时先读全同号方案，再以同definition和design_id依次validate_model/build_model；request与definition互斥。失败定向修正实际代码/方案。",
        "validate_model": "预检显式模型的结构、DSL表达式或program函数、实际证据路径、场景、原文约束和运行预算。definition合同见schema(build_model)。预检未注册模型、运行仿真或调用LLM。",
        "collect_data": "真实采集公开HTTPS URL、导入项目内CSV/TSV/JSON/JSONL/GeoJSON或ZIP数据文件path，或bbox=[南,西,北,东]采集OSM道路；三者只选一。parse_options可声明无标题字段、分隔符、编码及archive_member。保存原始文件与解析规则、来源哈希。",
        "analyze_data": "分析真实归档数据集，path指定JSON记录列表的点分路径（世界银行结果用1）。",
        "experiment": "真实配对实验。新建模型完成后，用baseline_run_id=本次已审且实际通过的run_id，arms=[{label,params,interventions}]、metric、seeds开展同一方程/真实输入的对照；省略原运行参数，由基线恢复。效果由实际结果决定，零/负效应照实保留。冻结MI研究仍走原科研流程。无baseline_run_id时保留原query编译通路，不自动插入模板干预。",
        "run": "用统一引擎实际运行；data_bindings用field/parameter映射数值参数，program用port/contract/columns保留完整记录或关系边表。结构输入读取inputs[port].columns，不能用聚合均值代替微观联合列。",
        "compose": "顺序终值传递；不等于同一时钟的反馈耦合。",
        "search_sources": "按主题词检索45源可行性矩阵，返回来源状态/许可/认证/最后检查时间。state参数过滤：live/needs_auth/down/candidate等。",
        "collect_source": "按schema实际connector采集；仅status=done且artifact_role=dataset可import_collection转DS。catalog_only/text_only是当前批次的参考材料，不能当作无关问题的数值输入；若研究论文/引用网络本身，按实际字段和records/edges合同采集建模，不因来源名拒绝。partial沿同ID续采。公开文件URL可直接collect_data(url,format,parse_options)，不猜连接器。",
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
            if key.startswith('_') or parameter.kind in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL): continue
            typ = "string" if key in strings else "object" if key in objects else "array" if key in arrays else "integer" if key in ("ticks", "seed", "page_budget", "min_records", "holdout_years", "budget", "forecast_years") else "number" if key in ("dt", "tolerance") else None
            item = {"type": typ} if typ else {}
            if key=='continuation_token':
                item={'type':['string','null'],'description':'原next_action返回的只读续接凭据，恢复同一原文/会话/数据/运行设置；按回执传回，不重新填写或改变参数。'}
            if key == 'allow_partial':
                item = {'type':'boolean','default':False}
            if key=='revise_proposal':
                item={'type':'boolean','default':False,'description':'与revise_from一起显式调整Agent自己提出的参数/采样设置，产生新方案并重新审查；用户原话固定值和MI科研协议不能改，旧方案保留。'}
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
        schema = {"type": "object", "properties": properties, "required": required,
                  "additionalProperties": False}
        spec = {"name": name, "description": descriptions.get(name, (fn.__doc__ or name).strip()),
                "parameters": schema}
        if name == 'collect_source':
            from ..collection.connectors import CONNECTORS
            properties['connector']['enum'] = sorted(CONNECTORS)
        if name in ('design_model','build_model','validate_model','reviewed_run') and 'parameters' in properties:
            properties['parameters']['description']='实际运行取值，如{"grid_rows":60,"fraud_penalty":3}；不是type/default/unit定义对象。参数类型、默认值、边界与单位放在definition.parameters。'
        if name=='experiment':
            properties['baseline_run_id']['description']='本轮同会话已审且真实数值验收通过的自建模型run_id；恢复同一方程、基线参数、时钟、干预和真实输入，再执行声明的对照。'
            properties['arms']={'type':['array','null'],'items':{'type':'object','required':['label'],
                'properties':{'label':{'type':'string','minLength':1},'params':{'type':'object'},
                              'interventions':{'type':'array','items':{'type':'object'}}},'additionalProperties':False},
                'description':'baseline_run_id模式的实际处理臂；params只写明确改变的模型参数，真实输入绑定参数不能用params伪覆盖。'}
            properties['analysis_window']={'type':['array','null'],'minItems':2,'maxItems':2,'items':{'type':'number'},
                'description':'baseline_run_id模式按实际模型时钟分析[t0,t1]；省略则使用完整运行。'}
        if name=='research_calibrate':
            properties['max_evaluations']={'type':'integer','minimum':1,'default':1,
                'description':'MS自建模型研究本次实际求值数；running须按next_action续接同一study_id，不重选或改协议。ST趋势研究沿用既有整批流程。'}
        if name=='research_model_create':
            from ..research.model_study_entry import tool_schema
            spec['parameters']=tool_schema()
        if name=='global_sensitivity':
            from ..research.global_sensitivity import schema
            spec['parameters']=schema()
            spec['description']='对当前版本已审基线做真实Sobol全局敏感性。独立连续分布、配对种子面板、实际样本运行与bootstrap区间；pending只按同analysis_id续接。报告传其run_id及analysis_id。不改变原模型/输入/科研冻结。'
        if name=='plan_capacity':
            from ..research.capacity_planner import schema
            spec['parameters']=schema()
            spec['description']='实际测量已审模型两档探针的耗时、CPU、内存、传输、归档和LLM token，再实跑目标档核外推误差。pending按capacity_id续接；只给建议，不改固定人数/原模型/数据/配置，不假称全局最大规模。'
        if name=='memory_feedback':
            spec['description']='保存用户对实际模型/方案的纠正，仅作后续建模参考。DSH真实用户原话由宿主绑定，Agent不能伪写偏好。design_id/run_id只选一项，归属仍核对。'
            spec['parameters']={'type':'object','additionalProperties':False,'properties':{
                'design_id':{'type':'string'},'run_id':{'type':'string'},'correction':{'type':'string','description':'原生可省略，后台逐字绑定真实用户原文；工作台API须给真实纠正。'}},
                'oneOf':[{'required':['design_id'],'not':{'required':['run_id']}},{'required':['run_id'],'not':{'required':['design_id']}}]}
        if name=='research_model_prepare':
            from ..research.model_intents import prepare_schema
            spec['parameters']=prepare_schema()
        if name=='research_model_context':
            from ..research.model_intents import context_schema
            spec['parameters']=context_schema()
        if name == 'collect_data':
            from ..dataset_parsing import FILE_FORMATS
            properties['format'].update(enum=list(FILE_FORMATS), default='json',
                description='文件内容或ZIP成员的数据格式。ZIP用csv.zip/tsv.zip/json.zip等并指定parse_options.archive_member；也可用对应基础格式加archive_member。不能只写zip。空格分隔的文本可用csv及delimiter=" "。')
        if name in ('collect_data', 'import_collection'):
            from ..datasets import DATA_ROLES
            properties['role'].update(enum=list(DATA_ROLES), default='input',
                description='数据用途，入模通常用input，或明确initialization/exogenous_input/mechanism_estimation。整份之后按时间划分训练/验证/留出的原始观测也用input，由研究split固定各分区；仅有训练行才标calibration。validation/holdout/test仅对应分区，不可混作运行输入。background/source_snapshot为参考，不能直接当评分目标；roads/population供场景适配器。记录/边表是contract.kind，不自造role。')
        if name == "build_model":
            schema["oneOf"] = [
                {"required": ["definition"], "properties": {"definition": {"type": "object"}, "request": {"type": "null"}}},
                {"required": ["request"], "properties": {"request": {"type": "string", "minLength": 1}, "definition": {"type": "null"}}},
            ]
            properties["definition"]["description"] = "完整模型对象：stocks/agents/hybrid为DSL，program为隔离Python合同，不混用字段。DSH省略scenario.source_request时平台附加真实用户原文。"
            properties["request"]["description"] = "仅由平台规划器建模时使用。DSH以独立绑定的本轮用户原文为准。"
            spec["instructions"] = ("新建默认先自动审查再构建。已有通过审查的design_id时保持原文和运行选项不变。"
                                    "DSH提交显式definition必须提供同一原文和会话的design_id。\n" + DSL_CONTRACT)
        if "design_id" in properties:
            properties["design_id"]["description"] = (
                "本工具实际返回的方案编号；pending时原样续接，绑定原文、会话、执行设置和平台版本。"
                if name in ("design_model", "reviewed_run") else
                "design_model真实返回的已通过方案编号，绑定当次原文及执行设置。")
        if "revise_from" in properties:
            properties["revise_from"]["description"] = "实际编译失败回执给出的原方案ID。复用有效研究阶段，针对已记录缺陷修订并重新审查；返回新design_id，不修改原获批方案。直接沿next_action调用；冗余的同一父design_id可以接受，不同编号不能混用。"
        if 'research_intent_id' in properties:
            properties['research_intent_id']['description']='research_model_prepare返回的实际MI编号；完整原文、数据、划分、参数搜索和检验已冻结。各设计/修订/预检/构建及next_action须保持同号。模型基线完成后会自动创建MS研究，不能当作整题完成。'
        if 'parse_options' in properties:
            properties['parse_options'].update(description='文件解析规则。CSV/TSV默认有标题；无标题须header=false及fieldnames。ZIP必须archive_member精确选择，原压缩包完整保留，不执行或提取文件。',
                properties={'delimiter':{'type':'string','minLength':1,'maxLength':1}, 'header':{'type':'boolean'},
                    'fieldnames':{'type':'array','items':{'type':'string'},'minItems':1,'uniqueItems':True},
                    'encoding':{'type':'string'},'skipinitialspace':{'type':'boolean'},'archive_member':{'type':'string'}},
                additionalProperties=False)
        if 'data_bindings' in properties:
            from ..structured_inputs import binding_schema
            properties['data_bindings'].update(items=binding_schema(),description=(
                '两种明确绑定：field/parameter为标量聚合；port/contract/columns为程序结构输入。'
                'contract与definition.input_ports同名端口一致；records保留联合行，edges须声明directed及source/target引用另一端口单字段主键，geojson保留完整Feature及源CRS/轴/单位；timeseries保留系列身份与原观测时点。'
                'fields声明type/unit/nullable，columns用源field或JSON Pointer映射，保留明确单位换算/缺失。原ID为文本时保持string，不丢前导零。'
                '区间clock给interval时须显式anchor=start/end，或用起止列field/end_field；timeseries声明series_by/interpolation/outside/missing/max_gap，由审查后源码实际取值，不在宿主补值。不自动改日期或猜时区。'
                '同一绑定贯穿design/validate/build/run/ensemble；留出或校准数据不能混入结构运行输入。'))
        specs.append(spec)
    return specs


TOOL_SPECS = _tool_specs()

def call_tool(name, /, **kwargs):
    """Agent 唯一执行入口：名称 + 参数 → 结果（JSON 可序列化）。"""
    if name not in TOOL_IMPL:
        return _err(f"未知工具 {name}（可用: {sorted(TOOL_IMPL)}）")
    return TOOL_IMPL[name](**kwargs)


def tool_manifest():
    """给 LLM 的工具清单（JSON 可序列化）。"""
    return json.dumps(TOOL_SPECS, ensure_ascii=False, indent=1)
