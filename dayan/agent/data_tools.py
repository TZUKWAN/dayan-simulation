"""Agent tools backed by actual dataset operations."""
from .. import datasets


def collect_data(url=None, path=None, name="输入数据", format="json", license="unknown", role="input", bbox=None, parse_options=None):
    try:
        if sum(item is not None for item in (url, path, bbox)) != 1:
            raise ValueError("只指定url、项目内path或OSM道路bbox之一")
        _check_dataset_role(role)
        if bbox is not None:
            if parse_options is not None:
                raise ValueError('OSM bbox使用固定公开接口，解析选项仅用于文件')
            result = datasets.osm_roads(bbox)
        elif url is not None:
            result = datasets.fetch(url, name=name, format=format, license=license, role=role, parse_options=parse_options)
        else:
            result = datasets.import_file(path, name=name, format=format, license=license, role=role, parse_options=parse_options)
        return {"ok": True, "payload": result}
    except Exception as exc:
        from ..dataset_parsing import FILE_FORMATS
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}",
                "available_formats": list(FILE_FORMATS), "available_roles": list(datasets.DATA_ROLES),
                "guidance": 'format是成员数据格式，例如csv.zip；archive_member精确指定ZIP成员。role是数据用途，入模通常input；records/edges/geojson写在后续绑定的contract.kind，不是role。'}


def _check_dataset_role(role):
    if role not in datasets.DATA_ROLES:
        raise ValueError('未知数据用途role：' + str(role) + '；可选：' + ', '.join(datasets.DATA_ROLES)
                         + '。入模默认input，记录/边表写在绑定contract.kind中，不另造role')


def analyze_data(dataset_id, path=""):
    try:
        return {"ok": True, "payload": datasets.analyze(dataset_id, path)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def collect_census_scene(bbox, road_classes=None):
    """Collect same-vintage TIGERweb roads and POP100 blocks for CPL001 (WGS84 west/south/east/north)."""
    try:
        from ..collection.spatial import collect_census_scene as collect
        return {"ok": True, "payload": collect(bbox, road_classes)}
    except (OSError, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


# ============ 自动多源采集（学术/政策升级，2026-11-13） ============

def search_sources(theme: str = "", state: str = ""):
    """按主题词/状态检索来源矩阵（真实探测证据随附）。"""
    try:
        from ..collection import registry
        rows = registry.matrix()
        out = []
        for m in rows:
            if state and m["state"] != state:
                continue
            hay = " ".join([m["source_id"], m["name"], m.get("org", ""),
                            " ".join(m.get("topics", [])),
                            registry.CATS.get(m["cat"], "")])
            if theme and theme.lower() not in hay.lower():
                continue
            out.append({"source_id": m["source_id"], "name": m["name"],
                        "state": m["state"], "state_zh": m["state_zh"],
                        "topics": m.get("topics", []),
                        "auth": m.get("auth"), "license": m.get("license"),
                        "last_checked": m.get("last_checked")})
        return {"ok": True, "payload": {"n_sources": len(out), "sources": out[:30]}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def list_presets():
    """主题采集预设清单（自然语言可直接驱动）。"""
    try:
        from ..collection import presets
        return {"ok": True, "payload": {"presets": [
            {"preset_id": p["preset_id"], "theme": p["theme"],
             "title": p["title"], "connector": p["connector"],
             "placeholders": p["placeholders"],
             **({"evidence":p["evidence"]} if p.get("evidence") else {}),
             "options": list(p.get("indicator_options", {}).keys())}
            for p in presets.list_presets()]}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def run_preset(preset_id, values=None, page_budget=1):
    """按预设执行真实采集（占位符自动解析+地区别名映射）。"""
    try:
        from ..collection import presets, engine
        preset = presets.get_preset(str(preset_id))
        if preset is None:
            raise ValueError(f"未知预设 {preset_id}")
        params = presets.resolve_params(preset, values or {})
        task = engine.run_collection(preset["connector"], params,
                                     name=preset["title"], theme=preset["theme"],
                                     page_budget=int(page_budget))
        return {"ok": task["status"] == "done" and task.get("n_records", 0) > 0, "payload": task,
                "error": task.get("error") or task.get("incomplete_reason") if task["status"] != "done" else None}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def collection_status(collection_id):
    """采集任务状态+记录预览。"""
    try:
        from ..collection import engine
        task = engine.get_task(collection_id)
        if task is None:
            raise ValueError(f"任务不存在 {collection_id}")
        return {"ok": True, "payload": {
            "task": {k: v for k, v in task.items() if k != "pages"},
            "pages": [{"idx": p["idx"], "url": p["url"], "sha256": p["sha256"],
                       "n_records": p["n_records"]} for p in task.get("pages", [])],
            "preview": engine.records_preview(collection_id, 5)}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build_data_requirement(question, variables, geo_scope="", time_scope=""):
    """从结构化变量列表构建 DataRequirement（版本化+校验）。"""
    try:
        from ..research.data_requirements import DataRequirement, DataVariable
        vars_ = [DataVariable(**v) for v in variables]
        req = DataRequirement(question=question, variables=vars_,
                              geo_scope=geo_scope, time_scope=time_scope)
        req.finalize()
        issues = req.validate()
        return {"ok": not issues, "payload": {"requirement": req.to_dict(),
                                          "issues": issues}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def build_collection_plan(requirement: dict):
    """从 DataRequirement 自动生成采集计划。"""
    try:
        from ..research.data_requirements import DataRequirement, build_plan
        req = DataRequirement.from_dict(requirement)
        plan = build_plan(req)
        return {"ok": bool(plan.steps) and all(s.status != "skipped" for s in plan.steps), "payload": {"plan": plan.to_dict(),
                                         "summary": plan.summary()}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def execute_plan(plan: dict, page_budget=1):
    """逐步执行采集计划（真实采集，留证据）。"""
    try:
        from ..collection import engine
        from ..research.data_requirements import CollectionPlan
        results = []
        for step in plan.get("steps", []):
            if step.get("status") == "skipped" or                     step.get("connector") in ("(无匹配路由)", ""):
                results.append({"step_id": step["step_id"], "status": "skipped",
                                "variable": step["variable_name"], "error": step.get("error", "无匹配路由")})
                continue
            try:
                task = engine.run_collection(
                    step["connector"], step["params"],
                    name=step["variable_name"], purpose=step.get("purpose", "research"),
                    page_budget=int(page_budget),
                    collection_id=step.get("collection_id") or None)
                step["status"] = task["status"]
                step["collection_id"] = task["collection_id"]
                step["n_records"] = task["n_records"]
                results.append({"step_id": step["step_id"],
                                "status": task["status"],
                                "variable": step["variable_name"],
                                "n_records": task["n_records"],
                                "collection_id": task["collection_id"]})
            except Exception as e:
                step["status"] = "failed"
                step["error"] = str(e)[:200]
                results.append({"step_id": step["step_id"], "status": "failed",
                                "variable": step["variable_name"],
                                "error": str(e)[:120]})
        return {"ok": bool(results) and all(r["status"] == "done" and r.get("n_records", 0) > 0 for r in results), "payload": {"results": results,
                                         "summary": {
                                             "total_steps": len(results),
                                             "done": sum(1 for r in results if r["status"] == "done"),
                                             "failed": sum(1 for r in results if r["status"] == "failed"),
                                             "partial": sum(1 for r in results if r["status"] == "partial"),
                                             "skipped": sum(1 for r in results if r["status"] == "skipped"),
                                             "total_records": sum(r.get("n_records", 0) for r in results)}}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def check_data_quality(records, variable_name, unit="", **kwargs):
    """数据质量检查（覆盖/缺失/单位/地域/时间跨度）。"""
    try:
        from ..research.quality import check_quality, save_quality_report
        report = check_quality(records, variable_name=variable_name,
                               unit=unit, **kwargs)
        path = save_quality_report(report)
        return {"ok": report["status"] == "pass", "quality_pass": report["status"] == "pass",
                "payload": {**report, "report_path": str(path)}}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def calibrate_model(model_fn_src, param_grid, calibration_records,
                    holdout_records=None, tolerance=None, calibration_name=""):
    """真实校准：网格搜索调用模型函数（model_fn_src 为可执行表达式）。

    model_fn_src 形如 "lambda params, years: [params['k0'] * (1 + params['r']) ** y for y in years]"
    只允许表达式（不执行任意语句），参数名来自 param_grid keys。
    """
    try:
        from ..research.safe_expression import compile_model_expression
        fn = compile_model_expression(model_fn_src)
        from ..research.calibration import grid_search_calibrate
        result = grid_search_calibrate(
            model_fn=fn, param_grid=param_grid,
            observations=calibration_records,
            holdout_observations=holdout_records,
            tolerance=tolerance, name=calibration_name)
        result["input_evidence"] = "caller_supplied_not_source_verified"
        result["provenance_note"] = "此入口只验证传入函数/观测的拟合误差；真实来源绑定、模型归档和报告请使用research_create/research_calibrate"
        return {"ok": result["status"] == "pass", "payload": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def collect_source(connector, params, page_budget=2, collection_id=None):
    """真实协议采集/资源下载/续采。目录证据不能当数值数据；partial需以原ID续采。"""
    try:
        from ..collection import engine, connectors
        if connector not in connectors.CONNECTORS:
            return {'ok':False,'error':'未知连接器 '+str(connector),'error_code':'unknown_connector',
                    'available_connectors':sorted(connectors.CONNECTORS),
                    'next_action':{'action':'schema','tool':'collect_data' if isinstance(params,dict) and params.get('url') else 'collect_source'},
                    'guidance':'公开文件URL直接用collect_data，声明format/parse_options；连接器枚举见collect_source的schema。不要猜连接器名。'}
        task = engine.run_collection(connector, params, page_budget=page_budget, collection_id=collection_id)
        return {"ok": task["status"] == "done" and task.get("n_records", 0) > 0, "payload": task,
                "error": task.get("error") or task.get("incomplete_reason")}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def cancel_collection(collection_id):
    """请求取消采集，在当前有界HTTP请求结束后停止，不把请求取消冒称已终止。"""
    from ..collection import engine
    return {"ok": True, "payload": engine.cancel(collection_id)}


def import_collection(collection_id, role="input"):
    """为模型参数导入真实数据时使用 role="input"（默认）；holdout 仅用于独立验证。返回 dataset_id。"""
    try:
        _check_dataset_role(role)
        import json
        from ..research.studies import verified_records
        from ..collection.evidence import artifact_role
        task, rows = verified_records(collection_id)
        if artifact_role(task["connector"], rows, {"artifact_role": task.get("artifact_role")} if task.get("artifact_role") else {}) != "dataset":
            raise ValueError("仅实际dataset可导入模型；此批次是目录/文本/文献元数据")
        provenance = (task["pages"][0].get("meta") or {}).get("provenance") or {}
        result = datasets.ingest(json.dumps(rows, ensure_ascii=False, allow_nan=False).encode(),
            name=task["name"], format="json", source=f"collection:{collection_id}", license=provenance.get("license", "unknown"), role=role,
            metadata={"collection_id":collection_id,"pages":task["pages"],
                      **{key:provenance[key] for key in ("reference","units","scope","method") if key in provenance}})
        return {"ok": True, "payload": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_create(question, collection_id, model_family, param_grid, tolerance,
                    holdout_years=1, budget=500, forecast_years=0, validation_years=0, selection_top=3):
    """按原始问题建立不可变研究合同。显式模型族/网格/阈值，校验实测国家指标年份；返回study_id。"""
    try:
        from ..research.studies import create_study, summary
        return {"ok": True, "payload": summary(create_study(question, collection_id, model_family,
            param_grid, tolerance, holdout_years, budget, forecast_years, validation_years, selection_top))}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_model_prepare(question,observables,time_unit,target_bindings,time_origin,split,execution,objectives,
                           param_grid,seeds,selection_top,max_loss,diagnostics,availability,information_mode,
                           parent_study_id=None):
    """先固定完整原文、真实目标/输入与研究检验，再按next_action自主设计/构建。MI仅是研究意图，不是已运行或已校准结果。"""
    try:
        from ..research.model_intents import prepare_intent
        return {'ok':True,'validation_pass':False,'payload':prepare_intent(question,observables=observables,
            time_unit=time_unit,target_bindings=target_bindings,time_origin=time_origin,split=split,execution=execution,
            objectives=objectives,param_grid=param_grid,seeds=seeds,selection_top=selection_top,max_loss=max_loss,
            diagnostics=diagnostics,availability=availability,information_mode=information_mode,parent_study_id=parent_study_id)}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def research_model_context(research_intent_id,evidence):
    """将已采集来源定义/单位/方法等文字引用附加到同MI，保留数值输入和科学协议。来源不等于完成建模或研究。"""
    try:
        from ..research.model_intents import attach_source_evidence,load_intent
        question=load_intent(research_intent_id)['protocol']['question']
        return {'ok':True,'validation_pass':False,'payload':attach_source_evidence(research_intent_id,evidence,question)}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def research_model_create(question,baseline_run_id,target_bindings,time_origin,split,objectives,param_grid,
                          seeds,selection_top,max_loss,diagnostics,availability,information_mode,
                          time_atol=1e-9,data_bindings=None,parent_study_id=None):
    """从已审查且实际完成的自建模型基线创建固定研究协议。返回MS研究ID；须沿next_action实际校准，创建成功不表示研究通过。"""
    try:
        from ..research.model_study_entry import create_model_study
        result=create_model_study(question,baseline_run_id,target_bindings=target_bindings,time_origin=time_origin,
            split=split,objectives=objectives,param_grid=param_grid,seeds=seeds,selection_top=selection_top,
            max_loss=max_loss,diagnostics=diagnostics,availability=availability,information_mode=information_mode,
            time_atol=time_atol,data_bindings=data_bindings,parent_study_id=parent_study_id)
        return {'ok':True,'validation_pass':False,'payload':result}
    except Exception as exc:
        return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def research_calibrate(study_id, max_evaluations=1):
    """ST趋势研究返回新ID；MS自建模型按固定协议续接实际求值，最多max_evaluations次。ok不表示科学验收通过。"""
    try:
        if str(study_id).startswith('MS-'):
            from ..research.model_studies import advance_study
            s=advance_study(study_id,max_evaluations=max_evaluations)
            from ..research.model_intents import sync_study
            workflow=sync_study(study_id)
            if workflow:s['research_intent']=workflow
            from ..research.model_study_runs import next_action
            from ..research.model_studies import load_study
            s['next_action']=next_action(load_study(study_id))
            return {'ok':True,'validation_pass':s.get('conclusion')=='passed_declared_checks','payload':s}
        from ..research.studies import calibrate_study, summary
        s = calibrate_study(study_id)
        return {"ok": bool(s.get("run_id")), "validation_pass": s["calibration"]["status"] == "pass", "payload": summary(s)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_finalize(study_id):
    """用研究选中参数及事前第一个seed真实运行完整状态，并与该候选逐观测复现；返回大屏实际run_id后继续同号研究报告。"""
    try:
        from ..research.model_study_runs import finalize_study
        from ..research.model_intents import sync_study
        result=finalize_study(study_id)
        workflow=sync_study(study_id)
        if workflow:result['research_intent']=workflow
        return {'ok':True,'validation_pass':result.get('conclusion')=='passed_declared_checks','payload':result}
    except Exception as exc:return {'ok':False,'error':f'{type(exc).__name__}: {exc}'}


def research_report(study_id, kind="academic"):
    """仅由指定study_id生成同源DOCX/MD/6图/数值CSV/事实JSON/复现包；保留验证失败。"""
    try:
        if str(study_id).startswith('MS-'):
            from ..research.model_study_reports import generate_report
            from ..research.model_studies import load_study
            from ..research.model_study_runs import can_finalize
            study=load_study(study_id)
            intent=(study['protocol'].get('baseline',{}).get('manifest',{}).get('scenario_review') or {}).get('research_intent')
            if intent and can_finalize(study) and not study['state'].get('selected_run'):
                raise ValueError('须先research_finalize实际运行所选参数并核对状态，不能交付校准前的基线场景')
            result=generate_report(study_id,kind)
            from ..research.model_intents import sync_study
            workflow=sync_study(study_id,report=result)
            if workflow:result={**result,'research_intent':workflow,'request_complete':True}
            return {'ok':True,'payload':result}
        from ..research.study_reports import generate_report
        return {"ok": True, "payload": generate_report(study_id, kind)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_status(study_id=None):
    """读取真实研究合同、数据绑定、校准状态、运行与报告；不重算。无ID列历史。"""
    from ..research import studies, model_studies
    if str(study_id).startswith('MI-'):
        from ..research.model_intents import intent_summary
        return {'ok':True,'payload':intent_summary(study_id)}
    if str(study_id).startswith('MS-'):
        return {'ok':True,'payload':model_studies.summary(model_studies.load_study(study_id))}
    if study_id is None:
        return {'ok':True,'payload':sorted([*studies.list_studies(),*model_studies.list_studies()],
                                           key=lambda row:row.get('created_at',''),reverse=True)}
    return {"ok": True, "payload": studies.summary(studies.load(study_id)) if study_id else studies.list_studies()}
