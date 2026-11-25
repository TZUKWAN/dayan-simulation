"""Time-specific acceptance checks must use the requested actual observation."""
import json
from zipfile import ZipFile

import pytest

from dayan.agent.verification import criteria_for_plan, evaluate_criteria


def criteria():
    return criteria_for_plan([
        {"id": "V1", "check": "balance", "fields": ["mass"], "target": 1, "reason": "反射守恒"},
        {"id": "V2", "check": "at_step", "step": 1, "fields": ["corner"], "target": .5,
         "reason": "第一次同步更新后角格两个反射项贡献0.5"},
        {"id": "V3", "check": "at_time", "time": 1, "fields": ["east", "south"], "target": .5,
         "reason": "两个内部邻格各贡献0.25"},
    ], ["mass", "corner", "east", "south"])


def test_points_do_not_become_final_values_or_silently_snap_to_missing_time():
    rows = [{"sim_t": 0, "mass": 1, "corner": 1, "east": 0, "south": 0},
            {"sim_t": 1, "mass": 1, "corner": .5, "east": .25, "south": .25},
            {"sim_t": 2, "mass": 1, "corner": .375, "east": .1875, "south": .1875}]
    checks = criteria()
    assert all(row["passed"] for row in evaluate_criteria(checks, rows))
    altered = [{**row, "step": 2} if row["check"] == "at_step" else row for row in checks]
    assert not evaluate_criteria(altered, rows)[1]["passed"]
    missing = [{**row, "time": .5} if row["check"] == "at_time" else row for row in checks]
    point = evaluate_criteria(missing, rows)[2]
    assert not point["passed"] and point["measured"]["matched_rows"] == 0
    ambiguous = evaluate_criteria(checks, [*rows, rows[1]])[2]
    assert not ambiguous["passed"] and ambiguous["measured"]["matched_rows"] == 2
    assert not any(row["passed"] for row in evaluate_criteria(checks, []))


def test_unsupported_temporal_fields_are_rejected_instead_of_ignored():
    base = [{"id": "V1", "check": "balance", "fields": ["mass"], "target": 1, "reason": "守恒"},
            {"id": "V2", "check": "end", "step": 1, "fields": ["corner"], "target": .5, "reason": "首步"}]
    with pytest.raises(ValueError, match="不支持的验收字段"):
        criteria_for_plan(base, ["mass", "corner"])
    base[1]["check"] = "at_step"
    for step in (True, -1, 1.5):
        with pytest.raises(ValueError, match="非负整数"):
            criteria_for_plan([base[0], {**base[1], "step": step}], ["mass", "corner"])
    checked = criteria_for_plan(base, ["mass", "corner"])
    assert checked[1]["step"] == 1


def test_real_diffusion_and_report_keep_the_first_step_check(tmp_path, monkeypatch):
    from dayan.agent.tools import _archive_run
    from dayan.custom_models import register
    from dayan.agent.scenario_tools import report_run

    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DAYAN_REPORTS_DIR", str(tmp_path / "reports"))
    from dayan import report_gen
    monkeypatch.setattr(report_gen, "REPORTS_DIR", tmp_path / "reports")
    model = register({"name": "指定时点反射扩散验算", "description": "真实同步更新的定向测试", "kind": "agents", "time_unit": "MCS",
        "agents": {"grid": {"rows": 5, "columns": 5, "degree": 4, "boundary": "reflecting",
                             "reductions": {"local_mean": {"op": "mean", "field": "u"}}},
            "initial": {"u": "1 if id == 0 else 0"}, "update": {"u": "local_mean"}, "color_by": "u",
            "measures": {"at_corner": "u if id == 0 else 0", "at_east": "u if id == 1 else 0",
                         "at_south": "u if id == 5 else 0"}},
        "observables": {"mass": "sum_u", "corner": "sum_at_corner", "east": "sum_at_east", "south": "sum_at_south"}})
    acceptance = {"criteria": criteria(), "observables": ["mass", "corner", "east", "south"], "events": {},
                  "spatial": True, "execution": {"ticks": 3, "dt": 1, "seed": 7, "parameters": {}}}
    run = _archive_run(model["model_id"], {}, 3, 7, 1, None, None, review={}, acceptance=acceptance)
    assert run["ok"], run
    assert run["payload"]["observations"][-1]["corner"] != .5
    actual = run["payload"]["manifest"]["scenario_review"]["runtime_checks"]["verification"]
    assert actual["criteria"][1]["measured"]["selected_times"] == [1]
    report = report_run(run["payload"]["run_id"], "corner")
    assert report["ok"], report
    path = next((tmp_path / "reports").glob("*.docx"))
    facts = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
    assert facts["run_id"] == run["payload"]["run_id"]
    with ZipFile(path) as file:
        xml = file.read("word/document.xml").decode()
    assert "第 1 步" in xml and "模型时刻 1" in xml
