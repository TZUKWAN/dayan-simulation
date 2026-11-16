"""负例测试（任务书 §六.8 必测项）：
每条验证"系统正确拒绝/降级/报告缺口"，不假装成功。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.collection import engine, presets, registry      # noqa: E402
from dayan.agent.data_tools import (build_data_requirement,              # noqa: E402
                                     build_collection_plan, run_preset,
                                     calibrate_model, check_data_quality)
from dayan.research.calibration import grid_search_calibrate             # noqa: E402
from dayan.research.quality import check_role_leakage, check_quality     # noqa: E402


def run_tests():
    passed, failed = 0, 0

    def check(name, cond, detail=""):
        nonlocal passed, failed
        if cond:
            passed += 1
            print(f"[PASS] {name}")
        else:
            failed += 1
            print(f"[FAIL] {name} {detail}")

    # 1) 缺必需变量名 → DataRequirement 校验拦截
    r = build_data_requirement("test", [{"concept": "人口", "unit": "人"}])
    check("负例: 缺变量名被校验拦截",
          r["ok"] and any("缺 name" in i for i in r["payload"]["issues"]))

    # 2) 缺概念定义 → 校验拦截
    r2 = build_data_requirement("test", [{"name": "x", "unit": "人"}])
    check("负例: 缺概念定义被拦截",
          r2["ok"] and any("缺概念" in i for i in r2["payload"]["issues"]))

    # 3) 金额缺价格基年 → 校验拦截
    r3 = build_data_requirement("test", [{"name": "gdp", "concept": "GDP",
                                           "unit": "亿元", "purpose": "calibration"}])
    check("负例: 金额缺基年被拦截",
          r3["ok"] and any("基年" in i for i in r3["payload"]["issues"]))

    # 4) 未知连接器 → 引擎拒绝
    try:
        engine.run_collection("nonexistent_conn", {})
        check("负例: 未知连接器拒绝", False, "未抛出")
    except ValueError:
        check("负例: 未知连接器拒绝", True)

    # 5) 预设占位符缺失 → 明确报错（不静默替代）
    try:
        presets.resolve_params(presets.get_preset("pop_employment_wb"), {})
        check("负例: 预设缺占位符报错", False, "未抛出")
    except ValueError:
        check("负例: 预设缺占位符报错", True)

    # 6) 校准无真实观测 → 拒绝（不基于合成目标）
    try:
        grid_search_calibrate(model_fn=lambda p, y: [1] * len(y),
                              param_grid={"a": [1, 2]}, observations=[])
        check("负例: 校准无观测拒绝", False, "未抛出")
    except ValueError:
        check("负例: 校准无观测拒绝", True)

    # 7) 校准超容忍阈值 → 如实 fail（不临时放宽）
    result = grid_search_calibrate(
        model_fn=lambda p, y: [p["a"] * yy for yy in y],
        param_grid={"a": [1, 2]},
        observations=[{"date": 2020, "value": 1000}, {"date": 2021, "value": 1100}],
        tolerance=0.001)
    check("负例: 校准超阈如实失败",
          result["status"] == "failed_tolerance" and
          "不临时放宽" in result.get("failure_note", ""))

    # 8) 角色泄漏拦截
    leak = check_role_leakage(["ds_001", "ds_002"], ["ds_002", "ds_003"])
    check("负例: 角色/数据泄漏拦截",
          leak["has_leakage"] and "ds_002" in leak["overlap"])

    # 9) 零记录质检 → 如实报 empty（不造假数据）
    q = check_quality([], variable_name="test")
    check("负例: 零记录如实报 empty", q["status"] == "empty")

    # 10) 缺失值质检 → 如实报缺失比例
    q2 = check_quality([{"date": 2020, "value": None}, {"date": 2021, "value": 100}],
                        variable_name="test", min_records=1)
    check("负例: 缺失值如实报告", q2["status"] in ("warn", "fail") and
          any("缺失" in i for i in q2["issues"]))

    # 11) run_preset 未知预设 → 明确报错
    r3 = run_preset("nonexistent_preset")
    check("负例: 未知预设报错", not r3["ok"] and "未知" in r3["error"])

    # 12) 非法 collection_id → 拒绝
    try:
        engine._dir("../../evil")
        check("负例: 非法collection_id拒绝", False, "未抛出")
    except ValueError:
        check("负例: 非法collection_id拒绝", True)

    # 13) fetch_url 非 HTTPS → 拒绝（SSRF 防护）
    from dayan.datasets import _public_url
    try:
        _public_url("http://example.com/data.json")
        check("负例: 非HTTPS拒绝", False, "未抛出")
    except ValueError:
        check("负例: 非HTTPS拒绝", True)

    # 14) 内网地址 → 拒绝（SSRF 防护）
    try:
        _public_url("https://192.168.1.1/data.json")
        check("负例: 内网地址拒绝", False, "未抛出")
    except ValueError:
        check("负例: 内网地址拒绝", True)

    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
