"""Regression for DSH-bound explicit DSL submission and preflight."""

import json
import tempfile
from pathlib import Path

import pytest

from dayan.agent.tools import TOOL_SPECS
from dayan.server import app
from dayan.task_manager import close_managers
from api_client import local_client


ORIGINAL = "新建二维点阵场景。3个主体沿 x 轴前进，观测横坐标均值。运行4步，步长0.5，种子7。"


def definition():
    return {
        "name": "点阵位移",
        "description": "三个点按一致速度沿横轴前进",
        "kind": "agents",
        "time_unit": "秒",
        "parameters": {"n": {"type": "int", "default": 3, "minimum": 1, "maximum": 20}},
        "initial_state": {},
        "rates": {},
        "agents": {"count": "n", "initial": {"x": "id", "y": 0}, "update": {"x": "x+dt"}},
        "space": {"width": 10, "height": 4, "unit": "格"},
        "observables": {"x_mean": "mean_x"},
        "visualization": {"glyph": "point", "color_by": "x", "label": "横坐标"},
        "scenario": {
            "title": "二维点阵",
            "setting": "宽十格、高四格的平面",
            "agent_label": "点",
            "requirements": [
                {"quote": "3个主体沿 x 轴前进", "model_refs": ["agents.count", "agents.update.x"],
                 "visual_refs": ["visualization.color_by", "space"]},
                {"quote": "观测横坐标均值", "model_refs": ["observables.x_mean"],
                 "visual_refs": ["visualization.color_by"]},
            ],
        },
    }


def test_authoring_parameter_values_are_checked_before_any_design_or_cloud_call(monkeypatch,tmp_path):
    from dayan.agent import model_tools
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    def no_design(*args,**kwargs):
        raise AssertionError('Malformed execution values reached model design')
    monkeypatch.setattr(model_tools,'create_design',no_design)
    for wrong in ({'grid_rows':{'type':'int','default':60,'unit':'1'}},{'grid_rows':[60,80]}):
        rejected=model_tools.call_native_model('design_model',{'parameters':wrong},ORIGINAL,'parameter-shape-owner')
        assert not rejected['ok'] and 'parameters.grid_rows' in rejected['error']
        assert 'definition.parameters' in rejected['error']
    assert not list(tmp_path.glob('model_designs/MD-*.json'))
    model=definition();model['scenario']['source_request']=ORIGINAL
    checked=model_tools.validate_model(model,parameters={'n':3},ticks=4,dt=.5,seed=7)
    assert checked['ok'],checked
    assert checked['payload']['execution']['parameters']=={'n':3} and not checked['payload']['executed']
    spec=next(s for s in TOOL_SPECS if s['name']=='design_model')
    assert '实际运行取值' in spec['parameters']['properties']['parameters']['description']


@pytest.fixture
def platform(monkeypatch):
    with tempfile.TemporaryDirectory() as folder:
        monkeypatch.setenv("DAYAN_DATA_DIR", folder)
        client = local_client(app)
        try:
            yield client, Path(folder)
        finally:
            close_managers()


def call(client, tool, arguments, *, original=ORIGINAL):
    response = client.post(f"/api/tools/{tool}", json={
        "origin": "dsh", "session_id": "native-contract-regression",
        "original_text": original, "arguments": arguments,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_native_explain_uses_real_original_when_request_is_omitted(platform,monkeypatch):
    import dayan.llm_client
    from dayan.research.native_contract import protect
    monkeypatch.setenv('DAYAN_TASK_WORKER','1')
    questions=[]
    def complete(messages,**kwargs):
        questions.append(json.loads(messages[1]['content'])['question'])
        assert kwargs['purpose']=='explain-archived-result'
        return '受控解释供应商，仅核对原生问题绑定；未调用真实LLM或运行模型。'
    monkeypatch.setattr(dayan.llm_client,'complete',complete)
    client,folder=platform
    result=call(client,'explain',{})
    assert result['ok'] and result['payload']['mode']=='explanation',result
    assert questions==[ORIGINAL]
    explicit='解释这次工具校验为什么失败。'
    assert protect('explain',{'request':explicit},ORIGINAL)['request']==explicit
    with pytest.raises(ValueError,match='缺少用户原文'):protect('explain',{},'')
    assert not (folder/'research_runs').exists()


def test_schema_declares_exclusive_build_modes_and_dsl():
    specs = {spec["name"]: spec for spec in TOOL_SPECS}
    build = specs["build_model"]
    branches = build["parameters"]["oneOf"]
    assert {tuple(branch["required"]) for branch in branches} == {("request",), ("definition",)}
    assert "各属性独立初始化" in build["instructions"]
    assert "agents.grid" in build["instructions"] and "pick_max" in build["instructions"]
    assert specs["validate_model"]["parameters"]["required"] == ["definition"]


def test_native_preflight_preserves_original_constraints_without_running(platform):
    client, folder = platform
    draft = definition()
    draft["scenario"]["source_request"] = "助手自己改写的要求"
    result = call(client, "validate_model", {
        "definition": draft, "ticks": 20, "dt": 0.2, "seeds": [1, 2], "parameters": {"n": 8},
    })
    assert result["ok"], result
    payload = result["payload"]
    assert payload["execution"] == {"ticks": 4, "dt": 0.5, "seed": 7, "parameters": {"n": 3}}
    assert payload["semantic_review_pending"] and not payload["executed"]
    assert not (folder / "custom_models").exists()
    assert not (folder / "runs").exists()
    receipt = json.loads((folder / "integrations/dsh/native-contract-regression.jsonl").read_text(encoding="utf-8"))
    assert receipt["tool"] == "validate_model" and "run_id" not in receipt


@pytest.mark.parametrize(("section", "key", "expression", "error"), [
    ("initial", "y", "x+1", "未知变量 x"),
    ("update", "x", "x>1 ? 1 : 0", "A if 条件 else B"),
    ("update", "x", "sum(x)", "不支持的函数调用"),
])
def test_explicit_build_and_preflight_use_same_compiler(platform, section, key, expression, error):
    client, folder = platform
    draft = definition()
    draft["agents"][section][key] = expression
    preview = call(client, "validate_model", {"definition": draft})
    build = call(client, "build_model", {"definition": draft, "request": None})
    assert not preview["ok"] and not build["ok"]
    assert preview["error"] == build["error"]
    assert f"agents.{section}.{key}" in build["error"] and error in build["error"]
    assert build["llm_calls"] == []
    assert not (folder / "custom_models").exists()


def test_native_build_rejects_ambiguous_mode_and_keeps_original_quote(platform):
    client, _ = platform
    draft = definition()
    both = call(client, "build_model", {"definition": draft, "request": ORIGINAL})
    assert not both["ok"] and "之一" in both["error"]
    draft["scenario"]["source_request"] = "改成不同的模型"
    draft["scenario"]["requirements"][0]["quote"] = "改成不同的模型"
    forged = call(client, "build_model", {"definition": draft})
    assert not forged["ok"] and "逐字来自用户原文" in forged["error"]


@pytest.mark.parametrize(("extra", "field"), [
    ({"observables_note": "横坐标均值"}, "observables_note"),
    ({"mechanisms": [{"name": "位移"}]}, "definition.mechanisms"),
])
def test_bad_definition_field_is_named(platform, extra, field):
    client, _ = platform
    draft = {**definition(), **extra}
    preview = call(client, "validate_model", {"definition": draft})
    assert not preview["ok"] and field in preview["error"]


def test_native_request_mode_uses_user_message(platform,monkeypatch):
    import dayan.engine_capabilities as capabilities
    from dayan.agent import model_tools
    monkeypatch.setenv('DAYAN_TASK_WORKER','1')
    monkeypatch.setattr(capabilities,'program_status',lambda:{'available':True,'fixture':'request binding only'})
    sources=[]
    def observe_source(source,*args,**kwargs):
        sources.append(source)
        raise RuntimeError('controlled planning boundary; no model or cloud call')
    monkeypatch.setattr(model_tools,'create_design',observe_source)
    client, _ = platform
    result = call(client, "build_model", {"request": "创建一个存量模型"}, original="创建多层场景")
    assert not result["ok"] and 'controlled planning boundary' in result['error']
    assert sources==['创建多层场景']
    assert result["llm_calls"] == []
    invalid = call(client, "build_model", {"request": 3})
    assert not invalid["ok"] and "request必须为非空用户需求" in invalid["error"]


def test_valid_native_dsl_cannot_skip_design_review(platform):
    client, folder = platform
    result = call(client, "build_model", {"definition": definition()})
    assert not result["ok"] and "design_model" in result["error"]
    assert not result["llm_calls"] and not (folder / "custom_models").exists()


def test_approved_design_is_bound_to_inputs_and_content(monkeypatch, tmp_path):
    from dayan.agent.model_design import _digest, approved_plan

    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    from dayan.source_version import source_fingerprint
    execution = {"ticks": 4, "dt": 0.5, "seed": 7, "parameters": {"n": 3}}
    plan = {"kind": "agents", "observables": ["x_mean"]}
    ident = "MD-" + "a" * 32
    record = {"status": "approved", "review": {"approved": True}, "session_id": "original-session",
              "design_id": ident, "request": ORIGINAL, "source_fingerprint": source_fingerprint(),
              "execution_sha256": _digest(execution), "plan": plan, "plan_sha256": _digest(plan)}
    assert approved_plan(ident, ORIGINAL, execution, "original-session", record=record) == record
    for request, options, session in (("变更需求", execution, "original-session"),
                                      (ORIGINAL, {**execution, "ticks": 8}, "original-session"),
                                      (ORIGINAL, execution, "other-session")):
        with pytest.raises(ValueError, match="已变化"):
            approved_plan(ident, request, options, session, record=record)
    record["plan"]["observables"] = ["changed"]
    with pytest.raises(ValueError, match="内容校验失败"):
        approved_plan(ident, ORIGINAL, execution, "original-session", record=record)


def test_rejected_design_does_not_reach_compiler(monkeypatch, tmp_path):
    from dayan.agent import model_design, model_tools

    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    idea = {"approach": "用存量方程", "mechanisms": ["增长"], "assumptions": ["固定流入"], "risks": ["单位"],
            "alternatives": [{"structure": "静态库存", "limitation": "没有流入过程"}]}
    critique = {"issues": [{"id": "units", "severity": "critical", "problem": "流入单位缺失", "fix": "检验单位"}]}
    addressed = [{"id": "units", "change": "说明时间单位", "status": "resolved"}]
    source = "新建存量模型，输出库存"
    plan = {"kind": "stocks", "mechanisms": ["增长"], "variables": ["库存"], "data": ["假设值"],
            "assumptions": ["逐步增加"], "limitations": ["仅验证线性增长"], "scene": "汇总", "observables": ["stock"], "verification": ["检查终值"],
            "criteria": [{"id": "V1", "check": "start", "fields": ["stock"], "target": 0, "reason": "初态定义"},
                         {"id": "V2", "check": "end", "fields": ["stock"], "target": 10, "reason": "单次积分预期"}],
            "rule_refs": [{"mechanism": "增长", "paths": ["rates.stock"]}],
            "coverage": [{"quote": source, "role": "mechanism", "implementation": "库存方程",
                          "test": "终值核验", "criteria": ["V2"]}],
            "resolutions": addressed}
    verdict = {"approved": False, "issues": ["每步与每天的单位仍不一致"], "checks": [], "criteria": []}
    replies = iter((idea, critique, {**idea, "resolutions": addressed}, plan, verdict, plan, verdict))

    def test_response(messages, *, audit, purpose, **kwargs):
        audit.append({"call_id": purpose, "ok": True})
        return json.dumps(next(replies), ensure_ascii=False)

    monkeypatch.setattr(model_design, "complete", test_response)
    monkeypatch.setattr(model_tools, "complete", lambda *a, **k: pytest.fail("compiler called before approval"))
    result = model_tools.build_model(request=source)
    assert not result["ok"] and "单位仍不一致" in result["error"]
    record = model_design.load_design(result["design_id"])
    assert record["status"] == "blocked" and record["review"] == verdict
    assert [step["step"] for step in record["stages"]] == ["concept", "critique", "revision", "plan", "review", "plan", "review"]
    assert not (tmp_path / "custom_models").exists()


def test_decorative_observable_does_not_verify_real_mechanism():
    from dayan.agent.model_design import check_definition

    plan = {"kind": "agents", "observables": ["x_mean"], "rule_refs": [
                {"mechanism": "位移", "paths": ["agents.update.x"]}],
            "coverage": [{"quote": "主体发生位移", "role": "mechanism", "criteria": ["V1"]}],
            "criteria": [{"id": "V1", "fields": ["x_mean"]}]}
    draft = definition()
    check_definition(plan, draft)
    draft["observables"]["x_mean"] = "t+1"
    with pytest.raises(ValueError, match="未读取实际演化"):
        check_definition(plan, draft)
    draft["agents"]["update"]["x"] = "x"
    with pytest.raises(ValueError, match="没有作用于状态"):
        check_definition(plan, draft)


def test_structural_references_are_checked_separately_from_equations():
    from dayan.agent.model_design import _plan, check_definition

    source = "横向移动，记录初始位置"
    evolution = {"mechanism": "横向移动", "paths": ["agents.update.x"]}
    layout = {"mechanism": "初始位置编号与归档帧", "paths": ["agents.initial.x", "state_frames.entities", "execution.seed"]}
    plan = {
        "kind": "agents", "mechanisms": [evolution, layout],
        "variables": ["坐标"], "data": ["预设"], "assumptions": ["水平移动"],
        "limitations": ["数值验证"], "verification": ["用坐标检查位移"], "scene": "点阵",
        "observables": ["x_mean"],
        "criteria": [
            {"id": "V1", "check": "start", "fields": ["x_mean"], "target": 1, "reason": "三点平均"},
            {"id": "V2", "check": "nondecreasing", "fields": ["x_mean"], "reason": "持续向右"},
            {"id": "V3", "check": "delta", "fields": ["x_mean"], "min": 1, "max": 3, "reason": "实际位移"},
        ],
        "coverage": [{"requirement_id": "U1", "role": "mechanism", "implementation": "用 x 更新",
                      "test": "水平位移", "criteria": ["V3"]}],
    }
    approved = _plan(plan, source, [], {})
    assert approved["rule_refs"] == [evolution]
    assert approved["support_refs"] == [layout]
    assert approved["runtime_refs"] == ["execution.seed", "state_frames.entities"]
    check_definition(approved, definition())
    with pytest.raises(ValueError, match="实际状态演化规则"):
        _plan({**plan, "mechanisms": [layout]}, source, [], {})


def test_native_design_keeps_equation_paths_and_resumes_with_same_options(monkeypatch, tmp_path):
    from dayan.agent import model_design, model_tools

    source = "新建存量模型，输出库存"
    monkeypatch.setenv("DAYAN_DATA_DIR", str(tmp_path))
    concept = {"approach": "固定流入", "mechanisms": ["库存增长"], "assumptions": ["常量流入"],
               "risks": ["量纲错配"], "alternatives": [{"structure": "静态库存", "limitation": "不能体现流入"}]}
    criteria = [
        {"id": "V1", "check": "start", "fields": ["stock"], "target": 0, "reason": "初态定义"},
        {"id": "V2", "check": "end", "fields": ["stock"], "target": 1, "reason": "单位流入乘以时长"},
    ]
    plan = {"kind": "stocks", "mechanisms": [{"mechanism": "库存增长",
            "paths": ["initial_state.stock", "rates.stock", "observables.stock"]}],
            "variables": ["存量单位是件"], "data": ["假设值"], "assumptions": ["固定流入"],
            "limitations": ["无实际校准"], "scene": "汇总", "observables": ["stock"],
            "verification": ["核对首末值"], "criteria": criteria,
            "coverage": [{"requirement_id": "U1", "role": "mechanism", "implementation": "固定流入",
                          "test": "检查终值", "criteria": ["V2"]}]}
    malformed = {**plan, "observables": ["stock（库存，单位为件）"]}
    with pytest.raises(ValueError, match="stock（库存，单位为件）"):
        model_design._plan(malformed, source, [], {})
    verdict = {"approved": True, "issues": [], "checks": [
        {"requirement_id": "U1", "verdict": "ready", "evidence": "存量方程与实际输出"},
    ], "criteria": [{"id": row["id"], "verdict": "grounded", "evidence": row["reason"]} for row in criteria]}
    critique = {"issues": [{"id": "archives", "severity": "limitation", "problem": "正式归档待运行",
                           "fix": "运行后核对同一模型归档号"}]}
    resolution = [{"id": "archives", "change": "按每个种子的真实归档验收", "status": "unresolved"}]
    replies = iter((concept, critique, {**concept, "resolutions": resolution}, plan, verdict))

    def planning_response(messages, *, audit, purpose, **kwargs):
        assert json.loads(messages[1]["content"])["original_request"] == source
        if purpose == "model-design-review":
            assert kwargs["thinking"] is True
        audit.append({"call_id": purpose, "ok": True})
        return json.dumps(next(replies), ensure_ascii=False)

    monkeypatch.setattr(model_design, "complete", planning_response)
    result = model_tools.call_native_model("design_model", {"ticks": 4, "dt": .25, "seeds": [7, 8]},
                                           source, "native-phase-continuation")
    payload = result["payload"]
    assert result["ok"], result
    assert payload["prompt_protocol"] == "phased_v5"
    assert payload["plan"]["mechanisms"] == ["库存增长"]
    assert payload["plan"]["rule_refs"] == plan["mechanisms"]
    assert payload["plan"]["resolutions"] == resolution
    model_design.check_definition(payload["plan"], {"kind": "stocks", "initial_state": {"stock": 0},
                                                   "rates": {"stock": 1}, "observables": {"stock": "stock"}})
    next_action = payload["next_action"]
    assert next_action["action"] == "build_model"
    from dayan.agent.model_continuation import restore
    saved,_,_=restore(next_action['action'],next_action['arguments']['continuation_token'],{},source,'native-phase-continuation')
    assert saved['seeds']==[7,8]

    def compilation_response(messages, **kwargs):
        request = json.loads(messages[1]["content"])
        assert request["原始需求"] == source
        assert request["已通过审查的实施方案"]["rule_refs"] == plan["mechanisms"]
        raise RuntimeError("reached compilation with the approved plan")

    monkeypatch.setattr(model_tools, "complete", compilation_response)
    run = model_tools.call_native_model(next_action["action"], next_action["arguments"],
                                        source, "native-phase-continuation")
    assert not run["ok"] and "reached compilation with the approved plan" in run["error"]
    assert len(list((tmp_path / "model_designs").glob("MD-*.json"))) == 1
