"""Controlled provider protocol tests; actual persistence, compiler and numerical execution."""
from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest

from dayan.agent import design_checkpoint, model_design, model_tools, scenario_tools
from dayan.collection.storage import atomic_json, read_json
from dayan.run_store import get_store


SOURCE = "新建库存模型，记录库存增长。运行4步，步长0.5，随机种子7。"


class ControlledProvider:
    def __init__(self):
        self.now = time.monotonic()
        self.cost = 0.0
        self.calls = []
        self.on_call = None

    def complete(self, messages, *, purpose, audit, **options):
        self.calls.append({"purpose": purpose, "messages": deepcopy(messages), **options})
        audit.append({"call_id": f"protocol-{len(self.calls)}", "purpose": purpose, "ok": True})
        self.now += self.cost if purpose.startswith("model-design-") else 0
        if self.on_call:
            result = self.on_call(purpose)
            if result is not None:
                return result
        anchors = model_design._requirement_index(SOURCE)
        idea = {"approach": "恒定流入", "mechanisms": ["库存增长"], "assumptions": ["固定速率"],
                "risks": ["速率单位错误"], "alternatives": [{"structure": "恒定库存", "limitation": "没有流入"}]}
        criteria = [{"id": "V1", "check": "start", "fields": ["stock"], "target": 10, "reason": "设定初态"},
                    {"id": "V2", "check": "end", "fields": ["stock"], "target": 14, "reason": "两小时每小时两件"}]
        replies = {
            "model-design-concept": idea,
            "model-design-critique": {"issues": []},
            "model-design-revision": {**idea, "resolutions": []},
            "model-design-plan": {"kind": "stocks", "mechanisms": [{"mechanism": "库存增长", "paths": ["rates.stock"]}],
                "variables": ["库存单位为件"], "data": ["数学基准"], "assumptions": ["每小时流入两件"],
                "limitations": ["不是经验模型"], "scene": "汇总", "observables": ["stock"], "verification": ["首末值"],
                "criteria": criteria, "coverage": [{"requirement_id": ident, "role": "mechanism",
                    "implementation": "实际库存积分", "test": "首末值", "criteria": ["V1", "V2"]} for ident in anchors]},
            "model-design-review": {"approved": True, "issues": [],
                "checks": [{"requirement_id": ident, "verdict": "ready", "evidence": "库存积分"} for ident in anchors],
                "criteria": [{"id": row["id"], "verdict": "grounded", "evidence": row["reason"]} for row in criteria]},
            "build-model": {"name": "续接库存数值基准", "description": "用于验证阶段恢复后的实际执行", "kind": "stocks",
                "time_unit": "小时", "initial_state": {"stock": 10}, "rates": {"stock": 2}, "observables": {"stock": "stock"}},
            "scene-semantic-review": {"matched": True, "missing": [], "limitations": ["数学基准"],
                "checks": [{"quote": quote, "refs": ["rates.stock", "observables.stock"]} for quote in anchors.values()]},
        }
        return json.dumps(replies[purpose], ensure_ascii=False)


@pytest.fixture
def provider(monkeypatch, tmp_path):
    import dayan.llm_client
    control = ControlledProvider()
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("DAYAN_WALL_SECONDS", "240")
    for module in (model_design, model_tools, design_checkpoint, scenario_tools):
        monkeypatch.setattr(module, "time", SimpleNamespace(monotonic=lambda: control.now))
    for module in (model_design, model_tools, dayan.llm_client):
        monkeypatch.setattr(module, "complete", control.complete)
    return control


def advance(arguments):
    return model_tools.call_native_model("design_model", arguments, SOURCE, "continuation-owner")


def test_recheck_repairs_full_stage_shape_but_keeps_genuine_missing_evidence_blocked(provider):
    rechecks=[]
    complete={'approach':'库存增长数学思路；证据缺失时不补造来源','mechanisms':['库存增长'],
        'assumptions':['每小时流入两件'],'risks':['原任务所需补充证据尚未取得'],
        'alternatives':[{'structure':'实际源资料核验后继续','limitation':'当前不能冒充已核实'}],
        'resolutions':[{'id':'missing_source','change':'仍未取得所需源资料，保留关键缺口','status':'unresolved'}]}
    def respond(purpose):
        if purpose=='model-design-critique':
            return json.dumps({'issues':[{'id':'missing_source','severity':'critical',
                'problem':'缺少已要求的真实源资料','fix':'取得实际源资料再复核，不能编造证据'}]},ensure_ascii=False)
        if purpose=='model-design-revision':return json.dumps(complete,ensure_ascii=False)
        if purpose=='model-design-evidence_recheck':
            sent=provider.calls[-1]['messages']
            assert '"mechanisms":["实际机制说明字符串"]' in sent[0]['content']
            rechecks.append(sent)
            if len(rechecks)==1:
                return json.dumps({key:value for key,value in complete.items() if key!='mechanisms'},ensure_ascii=False)
            assert 'mechanisms' in sent[-1]['content']
            return json.dumps(complete,ensure_ascii=False)
    provider.on_call=respond
    result=advance({})
    assert not result['ok'] and result['payload']['status']=='blocked',result
    assert '方案存在未解决的关键缺陷' in result['error']
    assert '阶段定向修复后仍未通过' not in result['error']
    saved=model_design.load_design(result['design_id'])
    stage=next(row for row in saved['stages'] if row['step']=='evidence_recheck')
    assert stage['output']['resolutions'][0]['status']=='unresolved'
    assert len(rechecks)==2 and not get_store().history()
    assert result['payload']['next_action']['arguments']['revise_from']==saved['design_id']


def test_native_continuation_preserves_exact_settings_and_executes_actual_model(provider, tmp_path):
    provider.cost = 70
    args = {"ticks": 4, "dt": .5, "seed": 7}
    ident = None
    for index in range(5):
        result = advance(args)
        assert result["ok"], result
        design = result["payload"]
        ident = ident or design["design_id"]
        assert design["design_id"] == ident and len(design["stages"]) == index + 1
        assert design["executed"] is False and "run_id" not in design
        assert design["status"] == ("approved" if index == 4 else "pending")
        assert len(list((tmp_path / "model_designs").glob("MD-*.json"))) == 1
        args = design["next_action"]["arguments"]
        from dayan.agent.model_continuation import restore
        saved,_,_=restore(design['next_action']['action'],args['continuation_token'],{},SOURCE,'continuation-owner')
        assert saved["request"] == SOURCE and saved["seed"] == 7 and saved["dt"] == .5 and saved["ticks"] == 4
    assert [call["purpose"] for call in provider.calls] == [
        "model-design-" + stage for stage in ("concept", "critique", "revision", "plan", "review")]
    assert len(design["llm_calls"]) == 5
    assert all(call['thinking'] is True for call in provider.calls)
    assert min(call["timeout"] for call in provider.calls) == 176
    # The exact next_action restores the same full request and execution settings.
    run = model_tools.call_native_model("build_model", args, SOURCE, "continuation-owner")
    assert run["ok"], run
    saved = get_store().load(run["payload"]["run_id"])
    assert saved["request_text"] == SOURCE
    assert saved["observations"][-1]["stock"] == pytest.approx(14)
    assert saved["manifest"]["rng"]["seed"] == 7
    assert run["payload"]["design_id"] == ident
    assert len(provider.calls) == 7


def test_invalid_json_repair_is_preserved_across_budget_boundary(provider):
    provider.cost = 70
    provider.on_call = lambda purpose: '{"approach":' if len(provider.calls) == 1 else None
    first = advance({})["payload"]
    assert first["status"] == "pending" and not first["stages"]
    second = advance(first["next_action"]["arguments"])["payload"]
    assert second["status"] == "pending" and second["stages"][0]["step"] == "concept"
    assert len(provider.calls) == 2
    assert provider.calls[1]["messages"][2]["content"] == '{"approach":'
    assert "JSON" in provider.calls[1]["messages"][3]["content"]
    assert len(second["llm_calls"]) == 2
    assert "design_validation_error" in second["llm_calls"][0]


def test_transient_review_failure_keeps_reasoning_and_does_not_repeat_successful_stages(provider):
    failed = False

    def timeout_once(purpose):
        nonlocal failed
        if purpose == "model-design-review" and not failed:
            failed = True
            raise TimeoutError("controlled provider timeout")

    provider.on_call = timeout_once
    first = advance({})["payload"]
    assert first["status"] == "pending" and first["current_stage"] == "review"
    assert first["pause_reason"] == "transient_provider_error"
    second = advance(first["next_action"]["arguments"])["payload"]
    assert second["status"] == "approved"
    reviews = [call for call in provider.calls if call["purpose"] == "model-design-review"]
    assert len(reviews) == 2 and all(call["thinking"] is True for call in reviews)
    assert len(provider.calls) == 6 and len(second["stages"]) == 5


def test_uncaught_interruption_recovers_file_checkpoint_without_repeating_concept(provider, tmp_path):
    def interrupt(purpose):
        if purpose == "model-design-critique":
            raise KeyboardInterrupt("controlled interrupted invocation")

    provider.on_call = interrupt
    with pytest.raises(KeyboardInterrupt):
        advance({})
    path, = (tmp_path / "model_designs").glob("MD-*.json")
    record = read_json(path)
    assert record["inflight"]["step"] == "critique" and len(record["stages"]) == 1
    provider.on_call = None
    # Simulate a lost HTTP response: the client never received the new design_id.
    result = advance({})
    assert result["ok"] and result["payload"]["status"] == "approved"
    assert result["payload"]["design_id"] == record["design_id"]
    assert len(result["payload"]["interruptions"]) == 1
    assert [call["purpose"] for call in provider.calls].count("model-design-concept") == 1


def test_resumption_rejects_changed_request_session_options_and_corrupt_checkpoint(provider, tmp_path):
    provider.cost = 70
    first = advance({})["payload"]
    args = first["next_action"]["arguments"]
    cases = [({**args, "parameters": {"different": 1}}, SOURCE, "continuation-owner"),
             (args, SOURCE + "保留变化。", "continuation-owner"), (args, SOURCE, "another-session")]
    for changed, source, session in cases:
        result = model_tools.call_native_model("design_model", changed, source, session)
        assert not result["ok"]
    assert len(provider.calls) == 1
    path = tmp_path / "model_designs" / (first["design_id"] + ".json")
    record = read_json(path)
    record["stages"][0]["output"]["approach"] = "corrupt"
    atomic_json(path, record)
    result = advance(args)
    assert not result["ok"] and "内容校验失败" in result["error"]
    assert len(provider.calls) == 1


def test_killed_worker_releases_lock_and_an_identical_request_recovers(provider, tmp_path):
    marker = tmp_path / "entered-critique.txt"
    script = '''
import os, runpy, time
from pathlib import Path
fixture = runpy.run_path("tests/test_design_continuation.py")
from dayan.agent import model_design, model_tools
control = fixture["ControlledProvider"]()
def stop_in_critique(purpose):
    if purpose == "model-design-critique":
        Path(os.environ["CONTINUATION_TEST_MARKER"]).write_text("actual child reached critique")
        while True:
            time.sleep(.1)
control.on_call = stop_in_critique
model_design.complete = control.complete
model_tools.call_native_model("design_model", {}, fixture["SOURCE"], "continuation-owner")
'''
    process = subprocess.Popen([sys.executable, "-c", script], cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "CONTINUATION_TEST_MARKER": str(marker)}, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    try:
        end = time.monotonic() + 20
        while not marker.exists() and process.poll() is None and time.monotonic() < end:
            time.sleep(.05)
        assert marker.exists(), process.communicate(timeout=1)
        process.kill()
        process.wait(timeout=5)
        path, = (tmp_path / "model_designs").glob("MD-*.json")
        before = read_json(path)
        result = advance({})
        assert result["ok"] and result["payload"]["status"] == "approved", result
        assert result["payload"]["design_id"] == before["design_id"]
        assert len(result["payload"]["interruptions"]) == 1
        assert all(row["purpose"] != "model-design-concept" for row in provider.calls)
    finally:
        if process.poll() is None:
            process.kill()
        process.communicate(timeout=5)


def test_existing_model_continuation_retains_data_supersession_and_runs(provider, monkeypatch):
    from dayan.datasets import ingest

    source = "模拟SIS重复感染，运行4步，步长0.5，随机种子7。"
    provider.cost = 70
    original_complete = provider.complete

    def native_response(messages, **kwargs):
        value = json.loads(original_complete(messages, **kwargs))
        anchors = model_design._requirement_index(source)
        if kwargs["purpose"] == "model-design-plan":
            value.update(mechanisms=["重复感染"], observables=["I"], variables=["感染比例"],
                assumptions=["本参数点无新感染，恢复率0.2"],
                criteria=[{"id": "V1", "check": "start", "fields": ["I"], "target": .2, "reason": "绑定初态"},
                          {"id": "V2", "check": "end", "fields": ["I"], "target": .13406400920712788, "atol": 1e-6,
                           "reason": "零感染参数下I(2)=0.2exp(-0.4)，含积分容差"}],
                coverage=[{"requirement_id": ident, "role": "mechanism", "implementation": "原生SIS方程",
                           "test": "初态及比例域", "criteria": ["V1", "V2"]} for ident in anchors])
        if kwargs["purpose"] == "model-design-review":
            value["checks"] = [{"requirement_id": ident, "verdict": "ready", "evidence": "原生SIS方程"} for ident in anchors]
        return json.dumps(value, ensure_ascii=False)

    monkeypatch.setattr(model_design, "complete", native_response)
    data = ingest(b"fraction\n0.1\n0.3\n", name="续接数据规约夹具", format="csv", source="controlled fixture")
    binding = {"dataset_id": data["dataset_id"], "field": "fraction", "parameter": "i0", "aggregate": "mean",
               "source_unit": "fraction", "target_unit": "fraction"}
    parameters = {"i0": .3, "beta": 0, "gamma": .2}
    args = {"model_id": "NET052", "request": source, "parameters": parameters, "data_bindings": [binding]}
    for index in range(5):
        result = scenario_tools.reviewed_run(**args, _session="review-owner")
        assert result["ok"], result
        payload = result["payload"]
        if index < 4:
            assert payload["status"] == "pending" and not payload["executed"]
            args = payload["next_action"]["arguments"]
            assert args["parameters"] == parameters  # Existing-model continuation uses its own saved contract.
    assert payload["observations"][0]["I"] == pytest.approx(.2)
    assert len(payload["llm_calls"]) == 5 and payload["run_id"]
    record = model_design.load_design(payload["design_id"], "review-owner")
    assert record["execution"]["superseded_agent_parameters"] == {"i0": .3}
