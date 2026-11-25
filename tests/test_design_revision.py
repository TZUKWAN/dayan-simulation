"""Real compiler feedback and solver, controlled provider for revision protocol."""
import json
from copy import deepcopy

import pytest

import test_design_continuation as fixture
from test_design_continuation import provider
from dayan.agent import model_design, model_tools
from dayan.run_store import get_store
from dayan.collection.storage import read_json, atomic_json


def test_explicit_revision_retries_failed_stage_and_keeps_failure_feedback(provider, monkeypatch):
    import dayan.llm_client
    original = provider.complete
    attempts = []

    def complete(messages, **kwargs):
        result = json.loads(original(messages, **kwargs))
        inputs = json.loads(messages[1]['content'])
        if kwargs['purpose'] == 'model-design-critique':
            attempts.append(messages)
            if len(attempts) <= 2:
                return '{"issues":['
            assert any(row.get('content') == '{"issues":[' for row in messages)
        if kwargs['purpose'] == 'model-design-revision' and inputs.get('implementation_feedback'):
            result['resolutions'] = [{'id': issue['id'], 'status': 'resolved',
                'change': '本修订完整返回结构化审查；原文、实际库存流入和终值14保持'}
                for issue in inputs['critique']]
        return json.dumps(result, ensure_ascii=False)

    for module in (model_design, model_tools, dayan.llm_client):
        monkeypatch.setattr(module, 'complete', complete)
    rejected = fixture.advance({})
    assert not rejected['ok'] and rejected['payload']['status'] == 'blocked', rejected
    parent_id = rejected['design_id']
    parent = deepcopy(model_design.load_design(parent_id))
    assert len(attempts) == 2
    repeated = fixture.advance({'design_id': parent_id})
    assert not repeated['ok'] and len(attempts) == 2
    revised = fixture.advance(rejected['payload']['next_action']['arguments'])
    assert revised['ok'] and revised['payload']['status'] == 'approved', revised
    child = revised['payload']
    assert len(attempts) == 3 and child['revision_of'] == parent_id
    assert model_design.load_design(parent_id) == parent
    inherited = [row for values in model_design.load_design(child['design_id'])['stage_failures'].values()
                 for row in values if row['kind'] == 'validation']
    assert len(inherited) == 2 and all(row['attempt_design_id'] == parent_id for row in inherited)
    assert all(row['response'] == '{"issues":[' for row in inherited)
    built = model_tools.call_native_model('build_model', child['next_action']['arguments'],
                                         fixture.SOURCE, 'continuation-owner')
    assert built['ok'] and built['payload']['observations'][-1]['stock'] == pytest.approx(14), built
    assert get_store().load(built['payload']['run_id'])['request_text'] == fixture.SOURCE


def test_explicit_proposal_revision_changes_agent_choices_but_rechecks_and_preserves_user_constraints(provider,monkeypatch):
    import dayan.llm_client
    from dayan.agent.design_revision import fork_revision
    from dayan.agent.design_checkpoint import digest
    original=provider.complete
    def complete(messages,**kwargs):
        value=json.loads(original(messages,**kwargs))
        context=json.loads(messages[1]['content'])
        purpose=kwargs['purpose']
        growth=context.get('execution',{}).get('parameters',{}).get('growth',2.)
        if purpose=='model-design-plan':
            value['criteria'][1]['target']=10+growth*2
            value['assumptions']=[f'本次数值流入速率为{growth}件每小时']
        if purpose=='model-design-revision':
            value['resolutions']=[{'id':issue['id'],'status':'resolved',
                'change':'按显式自主参数修订重新推导终值，原文4步/0.5步长/种子7保持'} for issue in context['critique']]
        if purpose=='build-model':
            value['parameters']={'growth':{'type':'float','default':2.,'minimum':0,'maximum':10}}
            value['rates']['stock']='growth'
        return json.dumps(value,ensure_ascii=False)
    for module in (model_design,model_tools,dayan.llm_client):monkeypatch.setattr(module,'complete',complete)
    first=fixture.advance({'parameters':{'growth':2.}})
    assert first['ok'] and first['payload']['status']=='approved',first
    parent_id=first['payload']['design_id'];before=deepcopy(model_design.load_design(parent_id))
    args={'revise_from':parent_id,'revise_proposal':True,'parameters':{'growth':3.}}
    result=fixture.advance(args)
    assert result['ok'] and result['payload']['status']=='approved',result
    child=result['payload']
    assert child['revision_of']==parent_id and child['execution']['parameters']=={'growth':3.}
    assert child['plan']['criteria'][1]['target']==16.
    assert child['implementation_feedback']['phase']=='execution_proposal_revision'
    assert child['implementation_feedback']['evidence']['changes']['parameters']=={
        'before':{'growth':2.},'after':{'growth':3.}}
    assert model_design.load_design(parent_id)==before
    again=fixture.advance(args)
    assert again['payload']['design_id']==child['design_id']
    built=model_tools.call_native_model('build_model',child['next_action']['arguments'],fixture.SOURCE,'continuation-owner')
    assert built['ok'] and built['payload']['observations'][-1]['stock']==16.,built
    assert get_store().load(built['payload']['run_id'])['request_text']==fixture.SOURCE
    changed=deepcopy(before['execution']);changed['ticks']=3
    with pytest.raises(ValueError,match='用户原话明确指定'):
        fork_revision(parent_id,fixture.SOURCE,changed,before['session_id'],before['memory_scope'],revise_proposal=True)
    # Explicit protocol marker tests that this path cannot bypass an MI freeze;
    # it is not presented as an actual prepared/calibrated scientific study.
    frozen=deepcopy(before);frozen['execution']['research']={'research_intent_id':'controlled-freeze-marker'}
    frozen['execution_sha256']=digest(frozen['execution']);atomic_json(model_design._path(parent_id),frozen)
    changed=deepcopy(frozen['execution']);changed['parameters']={'growth':3.}
    with pytest.raises(ValueError,match='冻结科研协议'):
        fork_revision(parent_id,fixture.SOURCE,changed,before['session_id'],before['memory_scope'],revise_proposal=True)


def bad_mapping(provider, monkeypatch):
    import dayan.llm_client
    original = provider.complete
    def complete(messages, **kwargs):
        response = json.loads(original(messages, **kwargs))
        inputs = json.loads(messages[1]["content"])
        purpose = kwargs["purpose"]
        if purpose == "model-design-plan" and "implementation_feedback" not in inputs:
            response["observables"].append("capacity")
            response["criteria"][1].update(fields=["capacity"], target=100)
            for row in response["coverage"]:
                row["criteria"] = ["V2"]
        if purpose == "build-model" and "capacity" in inputs["已通过审查的实施方案"]["observables"]:
            response["observables"]["capacity"] = 100
        if purpose == "model-design-revision" and "implementation_feedback" in inputs:
            response["resolutions"] = [{"id": row["id"], "change": "库存增长检查读取实际stock状态，终点14；容量不能证明流入",
                                       "status": "resolved"} for row in inputs["critique"]]
        return json.dumps(response, ensure_ascii=False)
    for module in (model_design, model_tools, dayan.llm_client):
        monkeypatch.setattr(module, "complete", complete)
    first = fixture.advance({})
    assert first["ok"] and first["payload"]["status"] == "approved", first
    parent = first["payload"]["design_id"]
    args = first["payload"]["next_action"]["arguments"]
    result = model_tools.call_native_model("build_model", args, fixture.SOURCE, "continuation-owner")
    assert not result["ok"] and result["payload"]["status"] == "revision_required", result
    assert result["payload"]["evidence"]["observables"] == {"capacity": 100}
    return parent, result["payload"]["next_action"]["arguments"]


def test_actual_compile_failure_revises_plan_without_repeating_research_or_changing_request(provider, monkeypatch):
    parent, args = bad_mapping(provider, monkeypatch)
    before = model_design.load_design(parent)
    assert not get_store().history()
    revised = fixture.advance(args)
    assert revised["ok"] and revised["payload"]["status"] == "approved", revised
    child = revised["payload"]
    assert child["design_id"] != parent and child["revision_of"] == parent
    assert child["request"] == before["request"] and child["execution"] == before["execution"]
    assert child["plan"]["criteria"][1]["target"] == 14
    assert model_design.load_design(parent) == before
    purposes = [row["purpose"] for row in provider.calls]
    assert purposes.count("model-design-concept") == 1 and purposes.count("model-design-critique") == 1
    assert purposes[-3:] == ["model-design-revision", "model-design-plan", "model-design-review"]
    assert child["plan"]["resolutions"][0]["id"].startswith("implementation_")
    assert [row["purpose"] for row in child["llm_calls"]].count("build-model") == 1
    # A lost revision response resumes the same derived design, not another fork.
    again = fixture.advance(args)
    assert again["ok"] and again["payload"]["design_id"] == child["design_id"]
    assert len(provider.calls) == len(purposes)
    action = child["next_action"]
    result = model_tools.call_native_model(action["action"], action["arguments"], fixture.SOURCE, "continuation-owner")
    assert result["ok"] and result["payload"]["observations"][-1]["stock"] == pytest.approx(14), result
    saved = get_store().load(result["payload"]["run_id"])
    assert saved["request_text"] == fixture.SOURCE and saved["manifest"]["scenario_review"]["runtime_checks"]["verification"]["status"] == "passed"


def test_revision_cannot_skip_actual_failure_or_cross_session_or_tamper_feedback(provider, tmp_path, monkeypatch):
    first = fixture.advance({})["payload"]
    unavailable = fixture.advance({"revise_from": first["design_id"]})
    assert not unavailable["ok"], unavailable
    parent, args = bad_mapping(provider, monkeypatch)
    wrong = model_tools.call_native_model("design_model", args, fixture.SOURCE, "other-owner")
    assert not wrong["ok"], wrong
    folder = tmp_path / "model_design_feedback" / parent
    ident = read_json(folder / "latest.json")["feedback_id"]
    path = folder / (ident + ".json")
    feedback = read_json(path)
    feedback["record"]["error"] = "tampered"
    atomic_json(path, feedback)
    invalid = fixture.advance(args)
    assert not invalid["ok"] and "编译反馈校验失败" in invalid["error"], invalid


@pytest.mark.parametrize('redundant_parent', [False, True])
def test_actual_semantic_rejection_is_preserved_and_revised_before_execution(provider, tmp_path, monkeypatch, redundant_parent):
    import dayan.llm_client
    original = provider.complete
    revision_review_contexts = []

    def complete(messages, **kwargs):
        response = json.loads(original(messages, **kwargs))
        inputs = json.loads(messages[1]["content"])
        purpose = kwargs["purpose"]
        if purpose == "build-model" and not inputs.get("真实实施反馈"):
            response["rates"]["stock"] = -2
        if purpose == "scene-semantic-review" and inputs["definition"]["rates"]["stock"] == -2:
            response.update(matched=False, missing=["原文要求库存增长，实际rates.stock=-2使库存减少"])
        if purpose == "model-design-revision" and "implementation_feedback" in inputs:
            response["resolutions"] = [{"id": row["id"], "change": "修正流入符号为+2，保留库存含义、终值14和原文",
                                       "status": "resolved"} for row in inputs["critique"]]
        if purpose == "model-design-review" and inputs.get("implementation_feedback"):
            revision_review_contexts.append(inputs)
            old_definition = inputs["implementation_feedback"].get("definition", {})
            if old_definition.get("rates", {}).get("stock") == -2:
                # Reproduce the real circular rejection: the new plan is correct,
                # but the reviewer grades the previous failed implementation.
                response.update(approved=False, issues=["旧源码仍为-2，无法批准新方案"])
                for criterion in response["criteria"]:
                    criterion["verdict"] = "insufficient"
        return json.dumps(response, ensure_ascii=False)

    for module in (model_design, model_tools, dayan.llm_client):
        monkeypatch.setattr(module, "complete", complete)
    parent = fixture.advance({})["payload"]
    initial = model_design.load_design(parent["design_id"])
    args = parent["next_action"]["arguments"]
    bad = model_tools.call_native_model("build_model", args, fixture.SOURCE, "continuation-owner")
    assert not bad["ok"] and bad["payload"]["status"] == "revision_required", bad
    assert bad["payload"]["evidence"]["phase"] == "semantic_review"
    assert bad["payload"]["evidence"]["review"]["matched"] is False
    assert not get_store().history()
    prior_call_count = len(provider.calls)
    repeated = model_tools.call_native_model("build_model", args, fixture.SOURCE, "continuation-owner")
    assert repeated["payload"]["feedback_id"] == bad["payload"]["feedback_id"]
    assert len(provider.calls) == prior_call_count  # Cached negative never becomes approval by re-review.
    revision_args = bad["payload"]["next_action"]["arguments"]
    wrong = fixture.advance({**revision_args, 'design_id': 'MD-' + '0' * 32})
    assert not wrong['ok'] and len(provider.calls) == prior_call_count
    if redundant_parent:
        revision_args = {**revision_args, 'design_id': parent['design_id']}
    revised = fixture.advance(revision_args)
    assert revised["ok"] and revised["payload"]["status"] == "approved", revised
    child = revised["payload"]
    assert child["request"] == initial["request"] and child["execution"] == initial["execution"]
    assert model_design.load_design(parent["design_id"]) == initial
    feedback = child["implementation_feedback"]
    assert feedback["definition"]["rates"]["stock"] == -2
    assert feedback["evidence"]["review"]["matched"] is False
    assert revision_review_contexts
    review_feedback = revision_review_contexts[-1]["implementation_feedback"]
    assert "definition" not in review_feedback and "prior_plan" not in review_feedback
    assert review_feedback["feedback_id"] == feedback["feedback_id"]
    assert review_feedback["error"] == feedback["error"]
    result = model_tools.call_native_model("build_model", child["next_action"]["arguments"],
                                          fixture.SOURCE, "continuation-owner")
    assert result["ok"], result
    assert result["payload"]["observations"][-1]["stock"] == pytest.approx(14)
    saved = get_store().load(result["payload"]["run_id"])
    assert saved["manifest"]["model_definition"]["rates"]["stock"] == 2
    assert saved["request_text"] == fixture.SOURCE
    purposes = [row["purpose"] for row in provider.calls]
    assert purposes.count("model-design-concept") == purposes.count("model-design-critique") == 1
    assert purposes.count("scene-semantic-review") == 2  # Old and corrected definition, once each.


def test_blocked_plan_returns_audited_revision_and_reuses_valid_stages(provider,monkeypatch):
    import dayan.llm_client
    original=provider.complete
    def complete(messages,**kwargs):
        response=json.loads(original(messages,**kwargs))
        inputs=json.loads(messages[1]['content'])
        if kwargs['purpose']=='model-design-plan' and not inputs.get('implementation_feedback'):
            response['criteria'][1]['target']=13.
        if kwargs['purpose']=='model-design-review' and inputs['plan']['criteria'][1]['target']==13.:
            response.update(approved=False,issues=['库存10+2×2=14；方案终点13没有数值依据'])
            response['criteria'][1]['verdict']='insufficient'
        if kwargs['purpose']=='model-design-revision' and inputs.get('implementation_feedback'):
            response['resolutions']=[{'id':row['id'],'change':'独立重算终点14，修正事前数值目标并保留原文与机制',
                                      'status':'resolved'} for row in inputs['critique']]
        return json.dumps(response,ensure_ascii=False)
    for module in (model_design,model_tools,dayan.llm_client):monkeypatch.setattr(module,'complete',complete)
    denied=fixture.advance({})
    assert not denied['ok'] and denied['payload']['status']=='blocked',denied
    parent_id=denied['design_id']
    before=model_design.load_design(parent_id)
    assert before['review']['approved'] is False and not get_store().history()
    action=denied['payload']['next_action']
    assert action['action']=='design_model' and action['arguments']['revise_from']==parent_id
    call_count=len(provider.calls)
    premature=model_tools.call_native_model('build_model',{'design_id':parent_id},fixture.SOURCE,'continuation-owner')
    assert not premature['ok'] and premature['payload']['next_action']==action,premature
    assert len(provider.calls)==call_count and not get_store().history()
    wrong=model_tools.call_native_model('design_model',action['arguments'],fixture.SOURCE,'other-owner')
    assert not wrong['ok']
    changed=fixture.advance({**action['arguments'],'parameters':{'unrequested':1.}})
    assert not changed['ok'] and '执行设置' in changed['error'],changed
    provider.cost=70
    corrected=fixture.advance(action['arguments'])
    assert corrected['ok'] and corrected['payload']['status']=='pending',corrected
    pending_child=corrected['payload']['design_id']
    # Actual lost revision response: the next caller has only the same original
    # request/options. Recover the child instead of reopening its blocked parent.
    corrected=fixture.advance({})
    assert corrected['payload']['design_id']==pending_child
    for _ in range(4):
        if corrected['payload']['status']=='approved':break
        corrected=fixture.advance(corrected['payload']['next_action']['arguments'])
    assert corrected['ok'] and corrected['payload']['status']=='approved',corrected
    provider.cost=0
    child=corrected['payload']
    assert child['revision_of']==parent_id and child['request']==before['request']
    assert child['execution']==before['execution'] and child['plan']['criteria'][1]['target']==14.
    assert child['implementation_feedback']['phase']=='design_review_rejection'
    assert child['implementation_feedback']['parent_sha256']
    assert model_design.load_design(parent_id)==before
    purposes=[row['purpose'] for row in provider.calls]
    assert purposes.count('model-design-concept')==purposes.count('model-design-critique')==1
    again=fixture.advance(action['arguments'])
    assert again['payload']['design_id']==child['design_id'] and len(provider.calls)==len(purposes)
    built=model_tools.call_native_model('build_model',child['next_action']['arguments'],fixture.SOURCE,'continuation-owner')
    assert built['ok'] and built['payload']['observations'][-1]['stock']==14.,built


def test_premature_build_returns_same_pending_design_next_step(provider):
    provider.cost=70
    first=fixture.advance({})
    assert first['ok'] and first['payload']['status']=='pending'
    count=len(provider.calls)
    follow=first['payload']['next_action']
    result=model_tools.call_native_model('build_model',follow['arguments'],fixture.SOURCE,'continuation-owner')
    assert result['ok'] and result['payload']['status']=='pending',result
    assert result['payload']['next_action']['action']=='design_model'
    assert result['payload']['next_action']['arguments']['design_id']==first['payload']['design_id']
    assert len(provider.calls)==count and not get_store().history()
