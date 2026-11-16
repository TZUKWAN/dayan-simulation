"""端到端链路验收：自然语言→规约→采集→质检→校准→留出→政策→报告。

验证的是「全链路真的通了」，不是逐组件独立正确。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dayan.agent.data_tools import (build_data_requirement,              # noqa: E402
                                     build_collection_plan, execute_plan,
                                     check_data_quality, calibrate_model)
from dayan.collection import engine                                      # noqa: E402
from dayan.research.calibration import time_split                        # noqa: E402
from dayan.research.quality import check_role_leakage, clean_transform   # noqa: E402
from dayan.research.report_academic import generate_academic_report      # noqa: E402


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

    # ---- 1. 构建规约 ----
    r = build_data_requirement(
        question="E2E: 中国人口趋势指数模型",
        variables=[{"name": "pop_total", "concept": "人口总量", "unit": "人",
                     "purpose": "calibration", "geo_level": "national",
                     "time_range": "2018:2022", "min_records": 3}],
        geo_scope="中国", time_scope="2018:2022")
    check("E2E-1: DR构建通过", r["ok"] and not r["payload"]["issues"])
    req = r["payload"]["requirement"]

    # ---- 2. 自动生成采集计划 ----
    plan = build_collection_plan(req)
    plan_data = plan["payload"]["plan"]
    check("E2E-2: 采集计划自动生成", plan_data["plan_id"].startswith("CP-") and
          len(plan_data["steps"]) >= 1 and
          plan_data["steps"][0]["connector"] != "(无匹配路由)")

    # ---- 3. 修改参数指向校准段并执行 ----
    plan_data["steps"][0]["params"]["date"] = "2018:2021"
    plan_data["steps"][0]["params"]["country"] = "CHN"
    plan_data["steps"][0]["params"]["per_page"] = 20
    ex = execute_plan(plan_data, page_budget=1)
    check("E2E-3: 真实采集执行成功",
          ex["ok"] and ex["payload"]["summary"]["done"] >= 1 and
          ex["payload"]["summary"]["total_records"] > 0)

    # ---- 4. 质检 ----
    records = engine.records_preview(plan_data["steps"][0]["collection_id"], 100)
    valid = [r for r in records if r.get("country_id") == "CHN" and r.get("value")]
    q = check_data_quality(valid, variable_name="pop_total", unit="人", min_records=3)
    check("E2E-4: 质检通过", q["ok"] and q["payload"]["status"] == "pass",
          f"status={q.get('payload', {}).get('status')}")

    # ---- 5. 清洗 + 切分 ----
    valid_sorted = sorted(valid, key=lambda r: int(r["date"]))
    cleaned, clean_log = clean_transform(valid_sorted, [{"op": "drop_missing_value"}])
    cal, hold = time_split(cleaned, holdout_years=1, time_field="date")
    check("E2E-5: 清洗+切分有数据", len(cal) >= 2 and len(hold) >= 1,
          f"cal={len(cal)} hold={len(hold)}")

    # ---- 6. 泄漏检查 ----
    leak = check_role_leakage([r["date"] for r in cal], [r["date"] for r in hold])
    check("E2E-6: 无泄漏", not leak["has_leakage"])

    # ---- 7. 校准+留出 ----
    model_fn = "lambda params, years: [params['K'] / (1 + math.exp(-params['r'] * (y - params['t_mid']))) for y in years]"
    grid = {"K": [1414000000, 1415000000],
             "r": [0.3, 0.5, 0.7],
             "t_mid": [2008, 2010, 2012]}
    cal_rec = [{"date": r["date"], "value": r["value"]} for r in cal if r.get("value")]
    hold_rec = [{"date": r["date"], "value": r["value"]} for r in hold if r.get("value")]
    cr = calibrate_model(model_fn, grid, cal_rec, holdout_records=hold_rec,
                         tolerance=2000000, calibration_name="E2E_Logistic")
    check("E2E-7: 校准通过（有真实RMSE改善）",
          cr["ok"] and cr["payload"]["status"] == "pass" and
          cr["payload"]["improvement_vs_baseline"] is not None and
          cr["payload"]["improvement_vs_baseline"] > 0,
          f"loss={cr.get('payload', {}).get('best_loss')} "
          f"improve={cr.get('payload', {}).get('improvement_vs_baseline')}")

    # ---- 8. 报告生成 ----
    uc_data = {"requirement": req, "calibration": cr["payload"],
               "n_records_used": len(cleaned),
               "plan": plan_data}
    report_path = generate_academic_report(uc_data)
    report_text = Path(report_path).read_text(encoding="utf-8")
    check("E2E-8: 学术报告生成（含校准/留出/局限）",
          "RMSE" in report_text and "留出" in report_text and "局限" in report_text)

    # ---- 9. 复现证据在盘 ----
    task = engine.get_task(plan_data["steps"][0]["collection_id"])
    check("E2E-9: 原始快照在盘可复核",
          task is not None and len(task.get("pages", [])) >= 1 and
          all(Path(ROOT / "data" / "collections" / p["raw"]).exists()
              for p in task["pages"]))

    print(f"\n端到端: {passed}/{passed + failed} 步通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(run_tests())
