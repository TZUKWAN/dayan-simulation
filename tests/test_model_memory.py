"""Research memory follows the real design, model and archive entry points."""
import hashlib
import hmac
import json

import pytest

from api_client import local_client
from dayan.access import access_token
from dayan.agent import model_design, model_tools
from dayan.datasets import ingest
from dayan.history_records import change
from dayan.research import model_memory
from dayan.run_store import get_store
from dayan.server import app


ORIGINAL = "新建供水库存存量模型，按恒定流入口径观测供水库存。运行4步，步长0.5，随机种子7。"
FRESH = "新建供水库存存量模型，研究固定排水及库存变化。运行4步，步长0.5，随机种子9。"


@pytest.fixture
def platform(tmp_path, monkeypatch):
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    # Keep the test provider in this process. The tool still executes and archives the real model.
    monkeypatch.setenv("DAYAN_TASK_WORKER", "1")
    return local_client(app)


def native(client, action, source, session, key, arguments=None, proof=None):
    if proof is None:
        message = f"dayan-research-memory-v1\n{session}\n{key}"
        proof = hmac.new(access_token().encode(), message.encode(), hashlib.sha256).hexdigest()
    response = client.post(f"/api/tools/{action}", json={
        "origin": "dsh", "session_id": session, "original_text": source, "arguments": arguments or {},
        "research_scope": key, "research_scope_proof": proof,
    })
    assert response.status_code == 200, response.text
    return response.json()


@pytest.fixture
def provider(monkeypatch):
    """Controlled LLM decisions for the phase boundaries. Execution uses the actual solver."""
    import dayan.llm_client

    calls = []

    def complete(messages, *, audit, purpose, **_):
        content = json.loads(messages[1]["content"])
        source = next(content[name] for name in ("original_request", "原始需求", "request") if name in content)
        calls.append((purpose, source, content))
        audit.append({"call_id": f"test-provider-{len(calls)}", "purpose": purpose, "ok": True})
        draining = "排水" in source
        rate = -1 if draining else 2
        mechanism = "固定排水降低供水库存" if draining else "恒定流入增长供水库存"
        idea = {"approach": mechanism, "mechanisms": [mechanism], "assumptions": ["速率在期内恒定"],
                "risks": ["越过有效库存范围"], "alternatives": [{"structure": "恒定库存", "limitation": "无流量"}]}
        anchors = model_design._requirement_index(source)
        criteria = [{"id": "V1", "check": "start", "fields": ["stock"], "target": 10, "reason": "初始库存"},
                    {"id": "V2", "check": "end", "fields": ["stock"], "target": 10 + 2 * rate,
                     "reason": "恒定速率乘两小时"}]
        outputs = {
            "model-design-concept": idea,
            "model-design-critique": {"issues": []},
            "model-design-revision": {**idea, "resolutions": []},
            "model-design-plan": {
                "kind": "stocks", "mechanisms": [{"mechanism": mechanism, "paths": ["rates.stock"]}],
                "variables": ["库存件数"], "data": ["假设值"], "assumptions": idea["assumptions"],
                "limitations": ["机制验算"], "scene": "存量汇总", "observables": ["stock"],
                "verification": ["核对起止库存"], "criteria": criteria,
                "coverage": [{"requirement_id": ident, "role": "mechanism", "implementation": mechanism,
                              "test": "核对计算存量", "criteria": ["V1", "V2"]} for ident in anchors],
            },
            "model-design-review": {
                "approved": True, "issues": [],
                "checks": [{"requirement_id": ident, "verdict": "ready", "evidence": "真实存量演化"}
                           for ident in anchors],
                "criteria": [{"id": row["id"], "verdict": "grounded", "evidence": row["reason"]}
                             for row in criteria],
            },
            "build-model": {
                "name": mechanism, "description": mechanism, "kind": "stocks", "time_unit": "小时",
                "mechanisms": [mechanism], "initial_state": {"stock": 10},
                "parameters": {} if draining else {"refill": {"default": 2, "unit": "件/小时"}},
                "rates": {"stock": rate if draining else "refill"},
                "observables": {"stock": "stock"},
            },
            "scene-semantic-review": {
                "matched": True, "missing": [], "limitations": ["机制验算"],
                "checks": [{"quote": quote, "refs": ["rates.stock", "observables.stock"]}
                           for quote in anchors.values()],
            },
        }
        return json.dumps(outputs[purpose], ensure_ascii=False)

    monkeypatch.setattr(model_design, "complete", complete)
    monkeypatch.setattr(model_tools, "complete", complete)
    monkeypatch.setattr(dayan.llm_client, "complete", complete)
    return calls


def test_native_memory_is_advisory_after_concept_and_scoped(platform, provider):
    project = "a" * 64
    dataset = ingest(b"reading\n1\n3\n", name="供水机制验算", format="csv", source="定向测试夹具")
    binding = {"dataset_id": dataset["dataset_id"], "field": "reading", "parameter": "refill",
               "aggregate": "mean", "source_unit": "件/小时", "target_unit": "件/小时"}
    first = native(platform, "build_model", ORIGINAL, "memory-first", project, {"data_bindings": [binding]})
    assert first["ok"], first
    old = first["payload"]
    assert old["observations"][-1]["stock"] == pytest.approx(14)
    assert old["memory_index"] == {"indexed_run_ids": [old["run_id"]], "errors": []}
    assert old["research_memory"]["status"] == "empty"

    second = native(platform, "build_model", FRESH, "memory-second", project)
    assert second["ok"], second
    new = second["payload"]
    assert new["model_id"] != old["model_id"]
    assert new["observations"][-1]["stock"] == pytest.approx(8)
    assert new["manifest"]["rng"]["seed"] == 9
    assert new["memory_index"]["indexed_run_ids"] == [new["run_id"]]
    phases = {purpose: content for purpose, source, content in provider if source == FRESH}
    assert phases["model-design-concept"]["execution"]["prior"] == {}
    assert "historical_references" not in phases["model-design-concept"]
    assert [phase for phase, body in phases.items() if "historical_references" in body] == ["model-design-critique"]
    references = phases["model-design-critique"]["historical_references"]
    assert [row["run_id"] for row in references] == [old["run_id"]]
    assert references[0]["equations"]["rates"] == {"stock": "refill"}
    mapping, = references[0]["data_fields"]
    assert mapping["aggregate"] == "mean" and mapping["source_unit"] == "件/小时"
    assert mapping["sha256"] == dataset["sha256"]
    saved = get_store().load(new["run_id"])
    assert saved["request_text"] == FRESH
    assert not saved["manifest"]["data_bindings"]
    assert saved["manifest"]["scenario_review"]["model_design"]["research_memory"]["references"] == [
        {"run_id": old["run_id"], "model_id": old["model_id"]}]

    other = native(platform, "design_model", FRESH, "memory-first", "b" * 64)
    assert other["ok"] and other["payload"]["research_memory"]["status"] == "empty"
    forged = native(platform, "design_model", FRESH, "memory-spoof", project, proof="0" * 64)
    assert not forged["ok"] and "绑定校验失败" in forged["error"]

    change(get_store(), None, old["run_id"], deleted=True)
    remaining = model_memory.references("project-" + project, "memory-first", FRESH,
                                        {"approach": "供水库存", "mechanisms": ["排水"]})
    assert [ref["run_id"] for ref in remaining] == [new["run_id"]]


def test_legacy_import_uses_its_original_scope_and_only_certified_runs(platform, provider, tmp_path, monkeypatch):
    from dayan.research.integration_events import append_event
    from dayan.model_index import resolve

    project = "a" * 64
    accepted = native(platform, "build_model", ORIGINAL, "memory-owner", project)
    assert accepted["ok"], accepted
    run_id = accepted["payload"]["run_id"]
    plain = model_tools.build_model(definition=accepted["payload"]["definition"], ticks=1)
    assert plain["ok"], plain
    append_event("previous-native", "build_model", accepted)
    append_event("previous-native", "build_model", plain)
    scope = model_memory.native_scope("previous-native")
    ideas = {"approach": "供水库存", "mechanisms": ["排水"]}
    assert model_memory.references("project-" + "b" * 64, "previous-native", FRESH, ideas) == []
    refs = model_memory.references(scope, "previous-native", FRESH, ideas)
    assert [ref["run_id"] for ref in refs] == [run_id]
    model_id = accepted["payload"]["model_id"]
    assert resolve(model_id)[0] == "fixed_step"
    available = platform.get("/api/models/runnable").json()["models"]
    assert {"model_id": model_id, "protocol": "fixed_step"} in available
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path / "another-workspace"))
    assert resolve(model_id) == (None, None)
    assert model_memory.references("project-" + project, None, FRESH, ideas) == []
    other = local_client(app).get("/api/models/runnable").json()["models"]
    assert all(row["model_id"] != model_id for row in other)
