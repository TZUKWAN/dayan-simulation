"""数据质量检查与角色/映射合同（任务书 §3.5/§六.2）。

覆盖：非空记录数、字段覆盖率、时间/地域范围、缺失率、单位一致、
角色泄漏拦截（校准集与留出集不得重叠）。清洗/换算保存操作+哈希，可复算。
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import copy
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
QUALITY_DIR = Path(os.environ.get("DAYAN_DATA_DIR", ROOT / "data")) / "collection" / "quality"


def _now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _hash(obj) -> str:
    return hashlib.sha256(
        json.dumps(obj, sort_keys=True, ensure_ascii=False, default=str).encode()
    ).hexdigest()


def check_quality(records: list[dict], *, variable_name: str,
                  unit: str = "", frequency: str = "annual",
                  time_field: str = "date", value_field: str = "value",
                  geo_field: str = "country",
                  expected_geo: str = "", min_records: int = 3, expected_time_range: str = "") -> dict:
    """对一组已采记录做数据质量检查（返回结构化报告，不含编造结论）。"""
    issues: list[str] = []
    if not records:
        return {"variable": variable_name, "status": "empty",
                "issues": ["零记录——来源无数据或查询过窄"], "n_records": 0}

    n = len(records)
    time_vals, geo_vals, val_vals, missing_val = [], [], [], 0
    for r in records:
        tv, gv, vv = r.get(time_field), r.get(geo_field), r.get(value_field)
        if frequency == "annual" and tv is not None:
            try:
                year=float(tv)
                if not math.isfinite(year) or not year.is_integer():raise ValueError()
            except (ValueError,TypeError):
                issues.append("年度时间字段须为有限整数年份，不能把未解析的日期当覆盖完整")
        if tv is not None:
            time_vals.append(str(tv))
        if gv is not None:
            geo_vals.append(str(gv))
        if isinstance(vv, (int, float)) and math.isfinite(vv):
            val_vals.append(float(vv))
        else:
            missing_val += 1

    time_range = (min(time_vals), max(time_vals)) if time_vals else ("", "")
    unique_geo = sorted(set(geo_vals))
    coverage_pct = round(100 * (1 - missing_val / max(n, 1)), 1) if n else 0

    actual_units = sorted({str(r.get("unit")) for r in records if r.get("unit")})
    if unit and (not actual_units or actual_units != [unit]):
        issues.append(f"单位未核实或不匹配：需求{unit}，实际{actual_units}；换算须显式记录")
    if len(time_vals) != n:
        issues.append("有记录缺失时间字段")
    if len(set(time_vals)) != len(time_vals):
        issues.append("日期重复，须明确地区/群体维度")
    if expected_geo and (len(geo_vals) != n or any(v != expected_geo for v in geo_vals)):
        issues.append("存在缺失或不匹配的地域记录")
    if expected_time_range:
        from .request_contract import year_range
        start, end = map(int, year_range(expected_time_range).split(":"))
        observed = {int(float(t)) for t in time_vals}
        missing_years = sorted(set(range(start, end+1)) - observed)
        if missing_years or observed - set(range(start, end+1)):
            issues.append(f"年份覆盖不一致，缺失{missing_years}或存在范围外记录")
    if n < min_records:
        issues.append(f"记录数 {n} < 最低要求 {min_records}")
    if missing_val > 0:
        issues.append(f"缺失/非数值 {missing_val}/{n}（{round(100*missing_val/n,1)}%）"
                      "——须显式清理，不可静默填充")
    if expected_geo and unique_geo and expected_geo not in str(unique_geo):
        issues.append(f"地域不匹配：期望含 '{expected_geo}'，实际 {unique_geo[:5]}")
    if frequency == "annual" and time_range[0] and time_range[1]:
        try:
            span = int(float(time_range[1])) - int(float(time_range[0]))
            if span < 2:
                issues.append(f"年度数据仅覆盖 {span} 年（{time_range[0]}~{time_range[1]}），"
                              "难以建模趋势")
        except (ValueError, TypeError):
            pass

    status = "pass" if not issues else "fail"
    return {
        "variable": variable_name, "unit": unit, "status": status,
        "n_records": n, "coverage_pct": coverage_pct,
        "time_range": list(time_range), "unique_geo": unique_geo[:10],
        "value_stats": {
            "min": min(val_vals) if val_vals else None,
            "max": max(val_vals) if val_vals else None,
            "mean": round(sum(val_vals) / len(val_vals), 6) if val_vals else None,
            "n_valid": len(val_vals),
        },
        "issues": issues, "checked_at": _now(),
    }


def check_role_leakage(calibration_ids, holdout_ids, calibration_records=None, holdout_records=None):
    """A source batch may be split by time; overlap of observations is the leakage test."""
    batches = sorted(set(calibration_ids) & set(holdout_ids))
    overlap = []
    verified = calibration_records is not None and holdout_records is not None
    if verified:
        def key(r):
            return (str(r.get("country_id", r.get("country", ""))), str(r.get("indicator", "")), str(r.get("date", r.get("year", ""))))
        overlap = sorted(set(map(key, calibration_records)) & set(map(key, holdout_records)))
    return {"overlap": overlap, "shared_batches": batches,
            "has_leakage": bool(overlap) if verified else None,
            "verified": verified, "checked_at": _now(),
            "note": "按地区/指标/日期检查观测重叠；同批次不同年份可独立留出，单凭采集ID无法证明无泄漏"}


def clean_transform(records: list[dict], operations: list[dict]) -> tuple[list[dict], dict]:
    """显式清洗/转换（保存操作链与哈希，可复算；不静默填值）。

    操作类型：
      drop_missing_value: 剔除 value 缺失/非有限 的记录
      scale:              value *= factor
      filter_geo:         仅保留 geo_field == value 的记录
    """
    result = copy.deepcopy(records)
    ops_log = []
    for op in operations:
        kind = op.get("op")
        before = len(result)
        if kind == "drop_missing_value":
            result = [r for r in result
                      if isinstance(r.get("value"), (int, float)) and math.isfinite(r["value"])]
            ops_log.append({"op": kind, "before": before, "after": len(result),
                            "dropped": before - len(result)})
        elif kind == "scale":
            factor = float(op["factor"])
            if not math.isfinite(factor):
                raise ValueError("单位换算因子须为有限数值")
            if factor != 1 and any(r.get("unit") for r in result) and not op.get("target_unit"):
                raise ValueError("有单位的数据换算须明确target_unit，不能只改数值保留原单位")
            for r in result:
                if isinstance(r.get("value"), (int, float)):
                    r["value"] = round(r["value"] * factor, 10)
                    if not math.isfinite(r["value"]):
                        raise ValueError("换算产生非有限结果")
                    if op.get("target_unit"):
                        r["unit"] = op["target_unit"]
            ops_log.append({"op": kind, "factor": factor, "n_affected": len(result)})
        elif kind == "filter_geo":
            gf, gv = op.get("field", "country"), op["value"]
            result = [r for r in result if r.get(gf) == gv]
            ops_log.append({"op": kind, "field": gf, "value": gv,
                            "before": before, "after": len(result)})
        else:
            raise ValueError(f"未知清洗操作 {kind}")
    chain_hash = _hash({"input": records, "output": result, "operations": operations})
    return result, {"operations": ops_log, "input_n": len(records),
                    "output_n": len(result), "input_sha256": _hash(records), "output_sha256": _hash(result), "chain_hash": chain_hash,
                    "reproducible": True, "at": _now()}


def save_quality_report(report: dict, report_id: str = "") -> Path:
    QUALITY_DIR.mkdir(parents=True, exist_ok=True)
    rid = report_id or ("Q" + _now().replace("-", "").replace(":", "")
                        .replace("T", "_").replace("+0000", "")[:15])
    path = QUALITY_DIR / f"{rid}.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    return path
