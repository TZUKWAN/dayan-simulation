"""Agent tools backed by actual dataset operations."""
from .. import datasets


def collect_data(url=None, path=None, name="输入数据", format="json", license="unknown", role="input", bbox=None):
    try:
        if sum(item is not None for item in (url, path, bbox)) != 1:
            raise ValueError("只指定url、项目内path或OSM道路bbox之一")
        if bbox is not None:
            result = datasets.osm_roads(bbox)
        elif url is not None:
            result = datasets.fetch(url, name=name, format=format, license=license, role=role)
        else:
            result = datasets.import_file(path, name=name, format=format, license=license, role=role)
        return {"ok": True, "payload": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def analyze_data(dataset_id, path=""):
    try:
        return {"ok": True, "payload": datasets.analyze(dataset_id, path)}
    except Exception as exc:
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
        from ..collection import engine
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
    """将完整真实数据页归档为可直接用于run.data_bindings的数据集；拒绝目录/门户文本。"""
    try:
        import json
        from ..research.studies import verified_records
        from ..collection.evidence import artifact_role
        task, rows = verified_records(collection_id)
        if artifact_role(task["connector"], rows, {"artifact_role": task.get("artifact_role")} if task.get("artifact_role") else {}) != "dataset":
            raise ValueError("仅实际dataset可导入模型；此批次是目录/文本/文献元数据")
        license = ((task["pages"][0].get("meta") or {}).get("provenance") or {}).get("license", "unknown")
        result = datasets.ingest(json.dumps(rows, ensure_ascii=False, allow_nan=False).encode(),
            name=task["name"], format="json", source=f"collection:{collection_id}", license=license, role=role,
            metadata={"collection_id": collection_id, "pages": task["pages"]})
        return {"ok": True, "payload": result}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_create(question, collection_id, model_family, param_grid, tolerance,
                    holdout_years=1, budget=500, forecast_years=0):
    """按原始问题建立不可变研究合同。显式模型族/网格/阈值，校验实测国家指标年份；返回study_id。"""
    try:
        from ..research.studies import create_study, summary
        return {"ok": True, "payload": summary(create_study(question, collection_id, model_family,
            param_grid, tolerance, holdout_years, budget, forecast_years))}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_calibrate(study_id):
    """用统一真实引擎评估网格并归档最终模型，返回新study_id。ok表示执行完成，validation_pass单独报告。"""
    try:
        from ..research.studies import calibrate_study, summary
        s = calibrate_study(study_id)
        return {"ok": bool(s.get("run_id")), "validation_pass": s["calibration"]["status"] == "pass", "payload": summary(s)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_report(study_id, kind="academic"):
    """仅由指定study_id生成同源DOCX/MD/6图/数值CSV/事实JSON/复现包；保留验证失败。"""
    try:
        from ..research.study_reports import generate_report
        return {"ok": True, "payload": generate_report(study_id, kind)}
    except Exception as exc:
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def research_status(study_id=None):
    """读取真实研究合同、数据绑定、校准状态、运行与报告；不重算。无ID列历史。"""
    from ..research import studies
    return {"ok": True, "payload": studies.summary(studies.load(study_id)) if study_id else studies.list_studies()}
