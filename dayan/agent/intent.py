"""Requirement-preserving routing, with an optional bounded LLM planner."""
from __future__ import annotations

from ..research.requirements import extract_request, coverage_issues

_LLM_PLANNER = None


def set_llm_planner(fn):
    global _LLM_PLANNER
    _LLM_PLANNER = fn


def plan_rule_based(text, last_run=None):
    r = extract_request(text, last_run)
    ids, kind = r["model_ids"], r["kind"]
    if r.get("unresolved_constraints") and kind not in ("explain","build_model"):
        return {"planner":"rule","intent":kind,"plan":[],"requirements":r,"errors":r["unresolved_constraints"]}
    if r["missing_context"] and kind!="explain":
        return {"planner":"rule","intent":kind,"plan":[],"requirements":r,
                "errors":["缺少上一次实际运行上下文，不能猜测要保留的模型和场景"]}
    concrete_scene=r["scene_requirements"]["spatial"]
    if r["scene_requirements"]["unsupported"] and kind not in ("explain","get_capabilities","search_models"):
        return {"planner":"rule","intent":kind,"plan":[],"requirements":r,
                "errors":["当前受限二维场景尚未实现："+"、".join(r["scene_requirements"]["unsupported"])]}
    if not ids and concrete_scene and kind=="run":
        kind="build_model"
    if not ids and r.get("requires_llm_agents") and kind != "build_model":
        ids = [next((mid for name, mid in (("ReAct", "BEH130"), ("Reflexion", "BEH131"), ("Voyager", "BEH132"), ("Concordia", "BEH133")) if name.lower() in text.lower()), "BEH129")]
    if any(word in text for word in ("能力卡", "参数清单", "说明书")) and ids:
        kind = "get_capabilities"
    compiled=None
    if not ids and kind=='run' and r['mechanisms']:
        from ..research.compiler import compile_research
        compiled=compile_research(text,last_run=last_run,seeds=[r['options'].get('seed',0)])
        if compiled.experiment_spec:
            spec=compiled.experiment_spec;ids=[spec.model_id]
            r['parameters']=spec.baseline_params;r['options'].update(ticks=spec.ticks,dt=spec.dt)
    # Natural-language requests without an explicit model must be planned from the full request.
    # Keyword tables may supply search candidates, never permission to execute their first entry.
    errors = coverage_issues(r, ids[0] if ids and kind not in ("search_models", "get_capabilities") else None)
    if compiled and not compiled.experiment_spec:errors.extend(compiled.warnings)
    args = {"parameters": r["parameters"], **{k: v for k, v in r["options"].items() if k in ("ticks", "dt", "seed")}}
    actions = []
    if kind == "build_model":
        actions = [{"tool": kind, "args": {"request": text, "last_run":last_run if r["reuse"] else None}}]
        errors = []
    elif kind == "explain":
        actions = [{"tool":kind,"args":{"request":text,"last_run":last_run}}]
        errors = []
    elif kind=="resume":
        if not last_run or not last_run.get("run_id"):errors.append("继续模拟需要真实run_id与完整检查点，不能从头重跑替代")
        elif r["explicit_parameters"] or r["interventions"] or ("seed" in r["options"] and r["options"]["seed"]!=last_run.get("seed")):
            errors.append("当前续算入口支持追加步数/步长；不支持同时变更参数或随机流，不会忽略这些修改")
        else:actions=[{"tool":"resume","args":{"run_id":last_run["run_id"],"ticks":r["options"].get("ticks",100),"dt":r["options"].get("dt")}}]
    elif kind == "collect_data":
        actions = [{"tool": kind, "args": {"url": r["url"], "format": "csv" if ".csv" in r["url"].lower() else "json"}}]
        errors = []
    elif kind == "analyze_data":
        actions = [{"tool": kind, "args": {"dataset_id": r["dataset_id"], "path": r["explicit_parameters"].get("path", "")}}]
        errors = []
    elif kind == "search_sources":
        import re
        themes = ((r"失业|就业|劳动", "就业"), (r"人口|生育|老龄", "人口"),
                  (r"教育|学校", "教育"), (r"卫生|健康|医疗", "卫生"),
                  (r"经济|GDP|收入", "经济"), (r"文献|论文", "文献"),
                  (r"新闻|媒体", "新闻"), (r"历史|文化", "历史"))
        theme = next((label for pattern, label in themes if re.search(pattern, text, re.I)), "")
        actions = [{"tool": "search_sources", "args": {"theme": theme}}]
        errors = []
    elif kind == "list_presets":
        actions = [{"tool": "list_presets", "args": {}}]
        errors = []
    elif kind == "run_preset":
        from ..research.request_contract import collection_action
        actions, errors, contract = collection_action(text)
        r["data_contract"] = contract
    elif kind == "calibrate_model":
        study_id = (last_run or {}).get("study_id")
        if study_id:
            actions = [{"tool": "research_calibrate", "args": {"study_id": study_id}}]
            errors = []
        else:
            actions = []
            errors = ["校准需要实际study_id及已绑定的真实数据、模型和训练/留出划分；请先建立研究，不能套用固定人口样本"]
    elif kind == "search_models":
        actions = [{"tool": kind, "args": {"query": text}}]
        errors = []
    elif kind == "get_capabilities":
        actions = [{"tool": kind, "args": {"model_id": ids[0]}}]
    elif kind == "experiment":
        actions = [{"tool": kind, "args": {"query": text, "last_run": last_run}}]
    elif ids and kind in ("run", "sweep", "ensemble"):
        args["model_id"] = ids[0]
        if kind == "sweep":
            if not r["sweep_param"] or len(r["values"]) < 2:
                errors.append("参数扫描需要明确参数名和至少两个扫描值")
            args.update(param=r["sweep_param"], values=r["values"], field=r["metric"])
        elif kind == "ensemble":
            args.pop("seed", None)
            args["seeds"] = r["options"].get("seeds", [r["options"]["seed"]] if "seed" in r["options"] else [0, 1, 2, 3])
        actions = [{"tool": kind, "args": args}]
    elif kind == "compare" and len(ids) == 2:
        args.pop("parameters", None)
        args.update(mid_a=ids[0], mid_b=ids[1], field=r["metric"],parameters_a=r["parameters"],parameters_b=r["parameters"])
        actions = [{"tool": kind, "args": args}]
    elif kind == "compose":
        errors.append("组合需要明确模块输入输出映射；不能根据同名字段猜测机制耦合")
    else:
        errors.append("未找到覆盖需求的模型；需要建模或明确研究对象")
    return {"planner": "rule", "intent": kind, "plan": [] if errors else actions,
            "requirements": r, "errors": errors}


def _constrain(planned, request, last_run):
    """Raw user constraints take precedence over generated tool arguments."""
    changes = []
    for action in planned.get("plan", []):
        args = action.get("args")
        if not isinstance(args, dict):
            continue
        tool = action.get("tool")
        if tool in ("research_create", "collect_source", "run_preset"):
            from ..research.native_contract import protect
            args = protect(tool, args, request["original_text"])
            action["args"] = args
        if tool == "build_model":
            args.pop("definition", None)
            args["request"] = request["original_text"]
            args["last_run"]=last_run if request["reuse"] else None
        if tool == "explain":
            args.update(request=request["original_text"],last_run=last_run)
        if tool=="resume":
            args["run_id"]=(last_run or {}).get("run_id")
            for key in ("ticks","dt"):
                if key in request["options"]:args[key]=request["options"][key]
        if tool == "experiment":
            args.update(query=request["original_text"], last_run=last_run)
        if tool == "compare":
            if len(request["model_ids"])==2:args.update(mid_a=request["model_ids"][0],mid_b=request["model_ids"][1])
            for key in ("parameters_a","parameters_b"):args[key]={**(args.get(key) or {}),**request["parameters"]}
            for key in ("ticks","dt","seed"):
                if key in request["options"]:args[key]=request["options"][key]
        if tool in ("run", "sweep", "ensemble", "experiment"):
            if len(request["model_ids"]) == 1:
                args["model_id"] = request["model_ids"][0]
            supplied = args.get("parameters") or {}
            canonical = {**supplied, **request["parameters"]}
            if canonical != supplied:
                changes.append("采用原始请求中的参数与上次实际配置")
            args["parameters"] = canonical
            for key in ("ticks", "dt", "seed", "seeds"):
                if key in request["options"] and not (tool == "ensemble" and key == "seed"):
                    args[key] = request["options"][key]
            if request["interventions"]:
                args["interventions"] = request["interventions"]
    planned["constraint_corrections"] = changes
    planned["requirements"] = request
    return planned


def plan(text, history=None, last_run=None, feedback=None):
    rule = plan_rule_based(text, last_run)
    for action in rule.get("plan",[]):
        if action.get("tool")=="explain":action["args"]["history"]=history or []
    if rule.get("intent") in ("resume", "run_preset", "calibrate_model"):return rule
    if (rule.get("requirements") or {}).get("scene_requirements",{}).get("unsupported") or ((rule.get("requirements") or {}).get("missing_context") and rule.get("intent")!="explain"):
        return rule
    if (rule.get("requirements") or {}).get("unresolved_constraints") and rule.get("intent") not in ("explain","build_model"):return rule
    if rule["plan"] or _LLM_PLANNER is None:
        return rule
    from .tools import tool_manifest
    try:
        result = _LLM_PLANNER(text, tool_manifest(), history=history,
                              last_run=last_run, feedback=feedback)
        if isinstance(result, dict) and result.get("plan"):
            try:
                result = _constrain(result, rule["requirements"], last_run)
            except ValueError as exc:
                return {**result, "plan": [], "requirements": rule["requirements"],
                        "errors": ["原始需求校验失败：" + str(exc)]}
            for action in result.get("plan",[]):
                if action.get("tool")=="explain":action["args"]["history"]=history or []
            issues = []
            for action in result["plan"]:
                if action.get("tool")=="resume" and rule["requirements"]["kind"]!="resume":
                    issues.append("不能将用户要求的新运行擅自改成从旧检查点继续")
                if action.get("tool") in ("run", "experiment", "sweep", "ensemble"):
                    args = action.get("args") or {}
                    mid = args.get("model_id")
                    effective_request = {**rule["requirements"], "parameters": {
                        **(args.get("parameters") or {}), **rule["requirements"]["parameters"]}}
                    issues.extend(coverage_issues(effective_request, mid))
            if issues:
                return {**result, "plan": [], "errors": list(dict.fromkeys(issues))}
            return result
        rule["planner_error"] = result.get("error", "LLM未提供有效计划") if isinstance(result, dict) else "LLM返回格式错误"
    except Exception as exc:
        rule["planner_error"] = f"{type(exc).__name__}: {exc}"
    return rule
