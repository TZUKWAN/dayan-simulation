"""Explicit intervention contracts. Structural parameters are initialization-only by default."""
from __future__ import annotations

import math


def _control(param, label, lo, hi, default, unit="", integer=False):
    return {"param": param, "label": label, "minimum": lo, "maximum": hi,
            "default": default, "unit": unit, "integer": integer,
            "mutable_at_runtime": True}


def intervention_contract(model_id):
    mid = str(model_id).upper()
    if mid.startswith("USR"):
        from .model_index import resolve
        _, cls = resolve(mid)
        return [_control(name, meta.get("label", name), meta.get("minimum", -1e12),
                         meta.get("maximum", 1e12), meta["default"], meta.get("unit", ""),
                         meta.get("type") == "int")
                for name, meta in getattr(cls, "parameter_schema", {}).items() if meta.get("mutable")]
    if mid in {"NET052", "NET053", "NET-SIR"}:
        return [_control("beta", "传播率", 0, 2, .5, "每仿真时间单位"),
                _control("gamma", "恢复率", 0, 2, .2, "每仿真时间单位")]
    if mid == "NET106":
        return [_control("p", "随机慢化概率", 0, 1, .2),
                _control("vmax", "最高速度", 1, 10, 5, "格/步", True)]
    if mid == "CPL001":
        return [_control("bus_capacity", "单车接驳容量", 0, 500, 20, "人/车次", True),
                _control("information_rate", "官方信息纠偏率", 0, 2, .05, "每分钟"),
                _control("rumor_rate", "谣言扩散率", 0, 2, .4, "每分钟"),
                _control("flood_severity", "积水影响情景强度", 0, 1, .5)]
    if mid == "BEH001":
        return [_control("threshold", "邻居相似度阈值", 0, 1, .4)]
    if mid == "NET113":
        return [_control("v_des", "期望步行速度", .1, 3, 1.5, "米/仿真时间单位"),
                _control("exit_half", "出口半宽", .1, 5, 1.5, "米")]
    if mid == "ECO019":
        return [_control("a", "工资调整截距", 0, .2, .045),
                _control("b", "就业对工资的响应系数", 0, .3, .06)]
    if mid == "SYS002":
        # A change in c requires a queue-specific server reconfiguration; not a scalar setattr.
        return [_control("lam", "到达率", .1, 10, 2, "每仿真时间单位"),
                _control("mu", "单服务台服务率", .1, 10, 1, "每仿真时间单位")]
    return []


def validate_intervention_value(model_id, param, value):
    contract = {c["param"]: c for c in intervention_contract(model_id)}
    if param not in contract:
        raise ValueError(f"{model_id}.{param} 未声明为运行中可变参数（结构/初始参数不能直接修改）；"
                         f"可用参数：{list(contract)}")
    c = contract[param]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f"干预参数 {param} 必须是有限数值")
    if not c["minimum"] <= value <= c["maximum"]:
        raise ValueError(f"干预参数 {param} 必须在 [{c['minimum']}, {c['maximum']}] 内")
    if c["integer"] and int(value) != value:
        raise ValueError(f"干预参数 {param} 必须为整数")
    return int(value) if c["integer"] else float(value)
