"""One evidence chain for collection → data binding → actual model calibration/run → reports.

Each stage publishes a new immutable study, never edits old scientific results.
The supported trend families are descriptive baselines, not a substitute for a requested mechanism.
Other platform models use the common run/data_bindings tools.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import re
import uuid

from .request_contract import parse_data_request, INDICATORS
from .calibration import time_split, grid_search_calibrate
from .quality import check_quality, check_role_leakage
from ..collection import engine
from .. import datasets, custom_models
from ..runtime import run_model_full
from ..run_store import get_store, utc_now

ROOT = Path(__file__).resolve().parents[2]


def base():
    return Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "studies"


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        allow_nan=False, separators=(",", ":")).encode()).hexdigest()


def directory(study_id):
    if not re.fullmatch(r"ST-[a-f0-9]{24}", str(study_id)):
        raise ValueError("非法study_id")
    return base() / study_id


def save(artifact):
    result = {**artifact, "study_id": "ST-" + uuid.uuid4().hex[:24], "created_at": utc_now()}
    result["artifact_sha256"] = digest(result)
    target = directory(result["study_id"])
    target.mkdir(parents=True, exist_ok=False)
    (target / "study.json").write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
    return result


def load(study_id):
    result = json.loads((directory(study_id) / "study.json").read_text(encoding="utf-8"))
    if digest({k: v for k, v in result.items() if k != "artifact_sha256"}) != result["artifact_sha256"]:
        raise ValueError("研究产物哈希校验失败")
    datasets.load(result["training_dataset"]["dataset_id"])
    if result.get("run_id"):
        run = get_store().load(result["run_id"])
        if digest(run["observations"]) != result["run_observations_sha256"]:
            raise ValueError("研究所引用的模型运行版本不一致")
    return result


def summary(study):
    keys = ("study_id", "parent_study_id", "created_at", "phase", "question", "contract", "collection_id", "model_id",
            "model_family", "unit", "quality", "data_binding", "run_id", "artifact_sha256", "limitations")
    out = {k: study[k] for k in keys if k in study}
    out["source_evidence"] = {
        "collection_id": study["collection_id"],
        "dataset_id": study["training_dataset"]["dataset_id"],
        "dataset_role": study["training_dataset"]["role"],
        "dataset_sha256": study["training_dataset"]["sha256"],
        "source_pages": [{"url": p["url"], "sha256": p["sha256"]} for p in study["source_pages"]],
        "id_meanings": "C前缀是采集批次；DS前缀是模型绑定数据集；二者不可互称。",
    }
    cal = study.get("calibration")
    if cal:
        out["calibration"] = {k: v for k, v in cal.items() if k not in ("evaluations", "training")}
        out["calibration"]["training"] = cal.get("training")
        out["interpretation"] = interpretation(study)
    out["artifact_url"] = f"/api/research/studies/{study['study_id']}"
    if study.get("run_id"):
        out["workbench_url"] = f"/?run={study['run_id']}&study={study['study_id']}"
    return out


def interpretation(study):
    """Deterministic observation/model comparisons; an AI must not reverse their direction."""
    predicted = {r["date"]: r["predicted"] for r in study.get("predictions", [])}
    holdout = study.get("holdout", [])
    rows = [{"date": r["date"], "observed": r["value"], "predicted": predicted[r["date"]],
             "observed_minus_predicted": r["value"]-predicted[r["date"]]}
            for r in holdout if r["date"] in predicted]
    if not rows:
        return {"holdout_comparisons": [], "direction": "not_available"}
    residuals = [r["observed_minus_predicted"] for r in rows]
    if all(v > 1e-9 for v in residuals):
        direction, note = "model_underpredicts_all_holdout", "全部留出年份实测值高于模型预测，模型低估该指标。"
    elif all(v < -1e-9 for v in residuals):
        direction, note = "model_overpredicts_all_holdout", "全部留出年份实测值低于模型预测，模型高估该指标。"
    elif all(abs(v) <= 1e-9 for v in residuals):
        direction, note = "equal_within_numeric_tolerance", "留出观测与模型预测在数值容差内一致。"
    else:
        direction, note = "mixed", "留出残差方向不一致，不能笼统声称模型全部高估或低估。"
    first = study["records"][0]
    last = rows[-1]
    observed_change = last["observed"]-first["value"]
    model_change = last["predicted"]-predicted[first["date"]]
    if observed_change < 0 and model_change < 0:
        if observed_change > model_change + 1e-9:
            note += "从共同初始年到最后留出年，实际下降幅度小于模型下降幅度；模型预测下降过快。"
        elif observed_change < model_change - 1e-9:
            note += "从共同初始年到最后留出年，实际下降幅度大于模型下降幅度；模型预测下降过慢。"
    return {"direction": direction, "holdout_comparisons": rows,
            "observed_change_from_initial": observed_change, "model_change_from_initial": model_change,
            "residual_definition": "observed - predicted", "interpretation_text": note,
            "causal_identification": "not_established", "policy_effect_estimate": None}


def list_studies():
    if not base().exists():
        return []
    rows = []
    for path in base().glob("ST-*/study.json"):
        try:
            rows.append(summary(load(path.parent.name)))
        except (ValueError, OSError) as exc:
            rows.append({"study_id": path.parent.name, "phase": "integrity_failed", "error": str(exc)})
    return sorted(rows, key=lambda s: s.get("created_at", ""), reverse=True)


def for_run(run_id):
    """Resolve the research contract for a replayed run; reports must not lose its calibration."""
    if not re.fullmatch(r"[A-Za-z0-9_-]{3,120}", str(run_id)):
        raise ValueError("非法运行ID")
    for path in sorted(base().glob("ST-*/study.json"), reverse=True):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("run_id") == run_id:
            return load(record["study_id"])
    return None


def verified_records(collection_id):
    task = engine.get_task(collection_id)
    if not task or task.get("status") != "done":
        raise ValueError("研究绑定需要完整done采集；partial/failed/empty不能作为完整数据")
    records_path = engine._dir(collection_id) / "records.jsonl"
    rows = [json.loads(line) for line in records_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if len(rows) != task["n_records"]:
        raise ValueError("采集行数与账本不一致")
    pages = {p["idx"]: p for p in task["pages"]}
    for page in pages.values():
        if hashlib.sha256((engine.BASE / page["raw"]).read_bytes()).hexdigest() != page["sha256"]:
            raise ValueError("原始来源快照损坏")
    accepted_rows = []
    for page in pages.values():
        if page.get("records_file"):
            content = (engine.BASE / page["records_file"]).read_bytes()
            if page.get("records_sha256") and hashlib.sha256(content).hexdigest() != page["records_sha256"]:
                raise ValueError("归一化页哈希不一致")
            accepted_rows.extend(json.loads(line) for line in content.decode("utf-8").splitlines() if line.strip())
    if accepted_rows and accepted_rows != rows:
        raise ValueError("合并记录与已接受的不可变页不一致")
    for row in rows:
        if row.get("_sha256") != pages.get(row.get("_page"), {}).get("sha256"):
            raise ValueError("记录与来源页哈希关联失败")
    return task, rows


def create_study(question, collection_id, model_family, param_grid, tolerance,
                 holdout_years=1, budget=500, forecast_years=0, validation_years=0, selection_top=3):
    contract = parse_data_request(question)
    if contract["errors"]:
        raise ValueError("；".join(contract["errors"]))
    family = str(model_family)
    if family not in ("linear", "exponential", "logistic"):
        raise ValueError("研究趋势模型须显式选择linear/exponential/logistic；机制模型请用模型合同+run绑定，不会替换为人口模板")
    # An explicit mechanism/shape in the user request has priority over the supplied family.
    for pattern, expected in ((r"线性|linear", "linear"), (r"指数|exponential", "exponential"), (r"logistic|逻辑斯蒂", "logistic")):
        if re.search(pattern, question, re.I) and expected != family:
            raise ValueError("所选模型族与原始请求不一致")
    if re.search(r"微观|主体行为|多智能体|SIR|Goodwin|因果|政策干预", question, re.I):
        raise ValueError("趋势拟合不覆盖请求的机制/因果/主体模型，须先建立相应机制模型，不能替代需求")
    task, raw_rows = verified_records(collection_id)
    if task["connector"] not in ("worldbank", "worldbank_data360"):
        raise ValueError("此研究时间序列适配器仅支持已核验WB统计记录；其他来源请通过显式数据映射运行模型，不能猜字段/单位")
    if task["params"].get("indicator") != contract["indicator"] or task["params"].get("country") != contract["country"] or task["params"].get("date") != contract["date"]:
        raise ValueError("采集查询与原始研究需求的国家/指标/时期不一致")
    unit = INDICATORS[contract["indicator"]]["unit"]
    records = []
    for row in raw_rows:
        if row.get("country_id") != contract["country"] or row.get("indicator") != contract["indicator"]:
            raise ValueError("实际返回记录国家/指标不匹配，不会过滤掉不匹配记录后宣称完整")
        if row.get("unit") != unit or row.get("frequency", "annual") != "annual":
            raise ValueError("采集实际单位或频率与研究合同不一致")
        if row.get("value") is None:
            raise ValueError(f"{row.get('date')}缺失实测值；需显式修订研究时间范围/数据缺口，不能静默填充")
        if not re.fullmatch(r"\d{4}", str(row.get("date") or "")):
            raise ValueError("指标记录不是四位整数年份")
        value, date = float(row["value"]), int(row["date"])
        if not math.isfinite(value):
            raise ValueError("统计值非有限")
        records.append({"date": date, "value": value, "country_id": row["country_id"],
            "indicator": row["indicator"], "unit": unit, "source_sha256": row["_sha256"]})
    records.sort(key=lambda r: r["date"])
    quality = check_quality(records, variable_name=contract["indicator"], unit=unit, geo_field="country_id",
        expected_geo=contract["country"], expected_time_range=contract["date"], min_records=4)
    if quality["status"] != "pass":
        raise ValueError("数据质量合同未满足：" + "；".join(quality["issues"]))
    if type(validation_years) is not int or validation_years < 0:
        raise ValueError("验证年份数须为非负整数")
    if validation_years and (type(selection_top) is not int or not 1 <= selection_top <= 30):
        raise ValueError("验证候选数须为1..30的整数")
    training, holdout = time_split(records, holdout_years=holdout_years)
    validation = []
    if validation_years:
        training, validation = time_split(training, holdout_years=validation_years)
    if len(training) < 3:
        raise ValueError("训练时间点至少3个，须另外保留独立的后续年份")
    role_check = check_role_leakage([collection_id], [collection_id], training, holdout)
    if validation:
        role_check["validation_pairs"] = [
            check_role_leakage([collection_id], [collection_id], group, validation)
            for group in (training, holdout)
        ]
        role_check["has_leakage"] |= any(pair["has_leakage"] for pair in role_check["validation_pairs"])
    if validation:
        import numpy as np
        q1, q3 = (float(v) for v in np.quantile([r["value"] for r in training], [.25,.75]))
        low, high = q1-1.5*(q3-q1), q3+1.5*(q3-q1)
        quality["outliers"] = {"method": "training_iqr_1.5", "fences": [low, high],
                               "flagged_years": [r["date"] for r in records if not low <= r["value"] <= high],
                               "treatment": "retained"}
    if role_check["has_leakage"]:
        raise ValueError("数据角色重叠")
    required = {"linear": {"slope"}, "exponential": {"r"}, "logistic": {"r", "K"}}[family]
    if set(param_grid) != required or not all(isinstance(v, list) and v for v in param_grid.values()):
        raise ValueError(f"{family}参数网格必须且仅含{sorted(required)}，初值直接来自真实首年数据")
    if tolerance is None or not math.isfinite(float(tolerance)) or float(tolerance) < 0:
        raise ValueError("须在校准前声明非负RMSE阈值（使用指标原单位）")
    if not isinstance(forecast_years, int) or not 0 <= forecast_years <= 30:
        raise ValueError("forecast_years须为0..30")
    p0 = training[0]["value"]
    if family != "linear" and p0 <= 0:
        raise ValueError("指数/Logistic模型需要正初值，不能替换统计口径")
    params = {"p0": {"default": p0, "minimum": -1e14, "maximum": 1e14, "unit": unit}}
    for key, vals in param_grid.items():
        vals = [float(v) for v in vals]
        if not all(math.isfinite(v) and abs(v) <= 1e14 for v in vals):
            raise ValueError("参数网格包含非法值")
        if key == "K" and min(vals) <= p0:
            raise ValueError("此Logistic增长模型的容量K须高于初值")
        params[key] = {"default": vals[0], "minimum": min(vals), "maximum": max(vals),
                       "unit": {"r": "1/year", "slope": f"{unit}/year", "K": unit}[key]}
    rate = {"linear": "slope", "exponential": "r*x", "logistic": "r*x*(1-x/K)"}[family]
    limitations = ["这是单变量描述性趋势模型，不建立当地政策效应或人群行为的因果识别。",
        "有限网格及有限留出点不能证明参数结构可识别；外推风险需单独评估。",
        "单位按已核验指标代码定义映射，非从指标标题猜测；不作无记录的单位换算。"]
    definition = {"name": f"{contract['country']} {contract['definition']['concept']} / {family}",
        "description": f"真实{unit}序列；dx/dt={rate}；初值取{training[0]['date']}实测。只作描述性基准。",
        "kind": "stocks", "time_unit": "year", "parameters": params,
        "initial_state": {"x": "p0"}, "rates": {"x": rate},
        "observables": {"value": "x"}, "assumptions": ["年度时间步；RK4确定性积分", "首年观测直接初始化，随后年份不回灌目标值"],
        "limitations": limitations}
    registered = custom_models.register(definition, original_request=question)
    dataset = datasets.ingest(json.dumps(training, ensure_ascii=False, allow_nan=False).encode(),
        name=question, format="json", source=f"collection:{collection_id}", license="World Bank CC BY 4.0 (indicator terms apply)",
        role="calibration", metadata={"unit":unit,"scope":contract['country'],"frequency":"annual",
            "collection_id": collection_id, "raw_pages": [p["sha256"] for p in task["pages"]],
            "transform": {"sort_by": "date ASC", "date": "integer year", "value": "float", "unit_mapping": contract["indicator"]},
            "holdout_excluded": [r["date"] for r in holdout], "validation_excluded": [r["date"] for r in validation],
            "input_records_sha256": digest(raw_rows)})
    binding = {"dataset_id": dataset["dataset_id"], "field": "value", "aggregate": "first", "parameter": "p0", "scale": 1,
               "source_unit":unit,"target_unit":unit,"source_scope":contract['country'],"target_scope":contract['country'],"order_by":"date"}
    return save({"schema_version": 2 if validation else 1, "phase": "prepared", "question": question, "contract": contract,
        "collection_id": collection_id, "source_pages": task["pages"], "records": records,
        "training": training, "validation": validation, "holdout": holdout, "quality": quality, "role_check": role_check,
        "selection_top": selection_top if validation else None,
        "unit": unit, "model_family": family, "model_id": registered["model_id"], "model_definition": registered["definition"],
        "training_dataset": dataset, "data_binding": binding, "param_grid": param_grid,
        "tolerance": float(tolerance), "budget": int(budget), "forecast_years": forecast_years,
        "base_year": training[0]["date"], "limitations": limitations})


def calibrate_study(study_id):
    source = load(study_id)
    if source["phase"] != "prepared":
        raise ValueError("此研究已校准；如需变更模型/范围/阈值，请创建新研究版本")
    # Every grid point uses the very same production engine/model as the archived final run.
    def execute(params, years, capture=False):
        horizon = max(int(y) for y in years) - source["base_year"]
        rr = run_model_full(source["model_id"], parameters=params, ticks=horizon, dt=1, seed=0,
            capture_state=capture, strict=True, data_bindings=[source["data_binding"]])
        lookup = {round(float(o["sim_t"])) + source["base_year"]: float(o["value"]) for o in rr.observations}
        return rr, [lookup[int(y)] for y in years]
    cal = grid_search_calibrate(model_fn=lambda p,y: execute(p,y)[1], param_grid=source["param_grid"],
        observations=source["training"], holdout_observations=source["holdout"], tolerance=source["tolerance"],
        budget=source["budget"], name=source["question"], validation_observations=source.get("validation"),
        selection_top=source.get("selection_top") or 3)
    result = {k: v for k, v in source.items() if k not in ("study_id", "created_at", "artifact_sha256")}
    result.update(parent_study_id=study_id, phase="calibrated" if cal.get("best_params") else "calibration_failed", calibration=cal)
    if cal.get("best_params"):
        years = list(range(source["base_year"], source["records"][-1]["date"] + source["forecast_years"] + 1))
        rr, predictions = execute(cal["best_params"], years, True)
        # Compare the final archive against the exact predictions used in calibration and holdout.
        expected = dict(zip(cal["training"]["dates"], cal["training"]["predicted"]))
        for role in (cal.get("selection",{}).get("validation"), cal.get("holdout")):
            if role and role.get("predicted"):
                expected.update(dict(zip(role["dates"], role["predicted"])))
        if any(not math.isclose(expected[y], p, rel_tol=1e-12, abs_tol=1e-9) for y,p in zip(years,predictions) if y in expected):
            raise ValueError("最终运行与校准预测不一致，停止发布研究")
        run_id = get_store().save_run(rr, "research", intent=source["question"], request_text=source["question"])
        result.update(run_id=run_id, run_manifest=rr.manifest, run_observations_sha256=digest(rr.observations),
                      predictions=[{"date": y, "predicted": p} for y,p in zip(years,predictions)])
    return save(result)
