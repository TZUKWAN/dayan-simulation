"""Protect explicit constraints from the native user's durable message before tool dispatch."""
import json
import math
import re
from .request_contract import parse_data_request


def protect(tool, arguments, original_text, session_id=""):
    args = dict(arguments)
    if not original_text:
        return args
    if tool in ("research_calibrate", "research_report"):
        from .studies import load
        study = load(args["study_id"])
        if study["question"] != original_text and args["study_id"] not in original_text:
            # A short follow-up may refer to this native session's most recent actual study.
            latest = None
            if session_id:
                from .integration_events import events
                latest = next((e for e in reversed(events(session_id)) if e.get("ok") and e.get("study_id")), None)
            scope = parse_data_request(original_text)
            referential = not any(scope.get(k) for k in ("country", "indicator", "date"))
            if not (referential and latest and latest["study_id"] == args["study_id"]):
                raise ValueError("研究不属于本次原始需求；不能拿旧结果代替本次任务。明确study_id或引用本会话当前研究才可复用")
    if tool == "build_model":
        args["request"] = original_text
    if tool not in ("research_create", "run_preset", "collect_source"):
        return args
    contract = parse_data_request(original_text)
    if (tool == "run_preset" and args.get("preset_id") == "pop_employment_wb") or (tool == "collect_source" and args.get("connector") == "worldbank"):
        if tool == "run_preset":
            from ..collection.presets import get_preset, resolve_params
            params = resolve_params(get_preset(args["preset_id"]), args.get("values", {}))
        else:
            params = args.get("params", {})
        for field in ("country", "indicator", "date"):
            if contract.get(field) and params.get(field) != contract[field]:
                raise ValueError(f"DSH工具参数{field}与原始用户需求冲突；不执行替换后的采集")
    if tool == "research_create":
        if contract["errors"]:
            raise ValueError("原始DSH需求尚有缺口："+"；".join(contract["errors"]))
        args["question"] = original_text
        split = re.search(r"末尾\s*(\d+)\s*年.*?留出", original_text)
        if split and int(split[1]) != args.get("holdout_years", 1):
            raise ValueError("DSH留出划分与原始要求冲突")
        tolerance = re.search(r"阈值\s*(?:均为|均|为|是)?\s*([\d.]+)", original_text)
        if tolerance and not math.isclose(float(tolerance[1]), float(args["tolerance"]), abs_tol=1e-12):
            raise ValueError("DSH误差阈值与原始事前要求冲突，不能事后放宽")
        for key, values in args.get("param_grid", {}).items():
            match = re.search(r"(?<![A-Za-z0-9_])"+re.escape(key)+r"\s*=\s*(\[[^\]]+\])", original_text)
            if match and json.loads(match[1]) != values:
                raise ValueError(f"DSH参数{key}网格与原始用户要求冲突")
        budget = re.search(r"预算\s*(?:最多|不超过|为|是)?\s*(\d+)", original_text)
        if budget:
            args["budget"] = min(int(args.get("budget", budget[1])), int(budget[1]))
    return args
