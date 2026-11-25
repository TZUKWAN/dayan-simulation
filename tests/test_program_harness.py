"""Controlled LLM protocol fixtures with actual isolated execution; not live Agent proof."""
from copy import deepcopy
import json

import pytest

from dayan.agent import model_tools,model_design
from dayan.collection.storage import read_json
from dayan.scene_contract import review_definition
from dayan.run_store import get_store
from test_design_continuation import provider, SOURCE, ControlledProvider
from test_solver_sandbox import LIVE


def stock_program():
    return {'kind':'program','name':'程序接口库存数值基准','description':'明确数学规则的协议测试',
        'time_unit':'小时','parameters':{},'populations':[],
        'observables':{'stock':{'label':'库存','unit':'件','equation':'S'}},
        'equations':[{'id':'inflow','expression':'dS/dt=2; S(0)=10','function':'advance','meaning':'恒定流入'}],
        'solver':{'method':'精确线性积分','description':'S(t+dt)=S(t)+2dt'},
        'mechanisms':['库存增长'],'assumptions':['规定的数学初值'],'limitations':['不是经验研究'],
        'source':'''def initialize(parameters,inputs,rng):
    return {"stock":10.}
def advance(state,parameters,inputs,rng,time,dt):
    return {"state":{"stock":state["stock"]+2.*dt},"events":[]}
def observe(state,parameters,inputs,time):
    return {"stock":state["stock"]}
def frame(state,parameters,inputs,time):
    return {"stocks":{"stock":state["stock"]}}
def validate(state,parameters,inputs,time):
    if state["stock"]<0:raise ValueError("negative stock")
'''}


@LIVE
@pytest.mark.parametrize('transport',['native_call','http'])
def test_reviewed_program_build_uses_same_source_functions_criteria_run_and_archive(provider,monkeypatch,transport):
    def change(purpose):
        # Only the provider response is controlled. The public chain, review
        # validation, actual Docker solve, acceptance and archival all execute.
        base=json.loads(ControlledProvider().complete([],purpose=purpose,audit=[]))
        if purpose=='model-design-plan':
            base['kind']='program'
            base['mechanisms'][0]['paths']=['source.advance','equations.inflow']
        elif purpose=='build-model':base=stock_program()
        elif purpose=='scene-semantic-review':
            for row in base['checks']:row['refs']=['source.advance','source.observe','runtime_contract.program_clock']
        return json.dumps(base,ensure_ascii=False)
    provider.on_call=change
    designed=model_tools.call_native_model('design_model',{'ticks':4,'dt':.5,'seed':7},SOURCE,'continuation-owner')
    assert designed['ok'] and designed['payload']['status']=='approved',designed
    args=designed['payload']['next_action']['arguments']
    explicit={**args,'definition':stock_program(),'request':None}
    if transport=='http':
        from api_client import local_client
        from dayan.server import app
        monkeypatch.setenv('DAYAN_TASK_WORKER','1')  # Controlled provider is in this process; the solver below is real.
        with local_client(app) as client:
            response=client.post('/api/tools/validate_model',json={'origin':'dsh','session_id':'continuation-owner',
                'original_text':SOURCE,'arguments':explicit})
            assert response.status_code==200,response.text
            validate=response.json()
    else:
        validate=model_tools.call_native_model('validate_model',explicit,SOURCE,'continuation-owner')
    assert validate['ok'] and not validate['payload']['executed'],validate
    changed=model_tools.call_native_model('validate_model',{**explicit,'ticks':5},SOURCE,'continuation-owner')
    assert not changed['ok'] and '执行设置冲突' in changed['error'],changed
    built=model_tools.call_native_model('build_model',args,SOURCE,'continuation-owner')
    assert built['ok'],built
    record=get_store().load(built['payload']['run_id'])
    assert record['request_text']==SOURCE
    assert [row['stock'] for row in record['observations']]==[10,11,12,13,14]
    manifest=record['manifest']
    assert manifest['protocol']=='managed_program'
    assert manifest['scenario_review']['runtime_checks']['verification']['status']=='passed'
    assert manifest['execution_environment']['system']=='Linux'
    assert manifest['model_definition']['source']==stock_program()['source']
    assert len(manifest['llm_calls'])==7
    review=next(row for row in provider.calls if row['purpose']=='scene-semantic-review')
    sent=json.loads(review['messages'][1]['content'])
    assert 'source.advance' in sent['available_refs']
    assert 'state["stock"]+2.' in sent['functions']['advance']
    assert sent['runtime_contract']['program_state_dependencies']['observables']['stock']==['stock']
    compiled=next(row for row in provider.calls if row['purpose']=='build-model')
    assert 'kind="program"' in compiled['messages'][0]['content']
    planned=next(row for row in provider.calls if row['purpose']=='model-design-plan')
    assert '本阶段只按当前phase要求' in planned['messages'][0]['content']
    assert '完整定义字段：kind,name' not in planned['messages'][0]['content']


def test_program_plan_rejects_compiler_shape_and_unsampled_event_time():
    from dayan.agent.model_design import _plan
    plan=json.loads(ControlledProvider().complete([],purpose='model-design-plan',audit=[]))
    plan['kind']='program'
    plan['mechanisms'][0]['paths']=['source.advance']
    with pytest.raises(ValueError,match='当前是实施方案阶段'):
        _plan({**plan,'source':'PLACEHOLDER_SOURCE'},SOURCE,[],{'ticks':4,'dt':.5})
    plan['criteria'][1].update(check='at_time',time=.35)
    with pytest.raises(ValueError,match='event_time'):
        _plan(plan,SOURCE,[],{'ticks':4,'dt':.5})
    plan['criteria'][1]['time']=3.
    with pytest.raises(ValueError,match='超出本轮实际运行区间'):
        _plan(plan,SOURCE,[],{'ticks':4,'dt':.5})
    plan['criteria'][1]['time']=2.
    assert _plan(plan,SOURCE,[],{'ticks':4,'dt':.5})['criteria'][1]['time']==2.


@LIVE
def test_unreachable_approved_program_mapping_records_real_feedback_and_revises_without_fake_calls(provider,monkeypatch,tmp_path):
    """Controlled plan defect, actual public preflight/feedback/fork; no solver or cloud claim."""
    fixed=False
    def respond(purpose):
        base=json.loads(ControlledProvider().complete([],purpose=purpose,audit=[]))
        if purpose=='model-design-plan':
            base['kind']='program'
            base['mechanisms'][0]['paths']=['source.advance','equations.inflow']
            if not fixed:
                base['mechanisms'].append({'mechanism':'后续平台评分不属于基线推进',
                                           'paths':['source.post_run_score']})
        elif purpose=='model-design-revision' and fixed:
            inputs=json.loads(provider.calls[-1]['messages'][1]['content'])
            base['resolutions']=[{'id':row['id'],'status':'resolved',
                                 'change':'移除错误的非推进机制映射，保留原库存方程、全部数值目标和执行选项；不在advance插入假调用'}
                                for row in inputs['critique']]
        return json.dumps(base,ensure_ascii=False)
    provider.on_call=respond
    first=model_tools.call_native_model('design_model',{'ticks':4,'dt':.5,'seed':7},SOURCE,'continuation-owner')
    assert first['ok'] and first['payload']['status']=='approved',first
    parent=first['payload']['design_id'];before=model_design.load_design(parent)
    definition=stock_program()
    definition['source']+='\ndef post_run_score(state):\n    return state["stock"]\n'
    original=deepcopy(definition)
    args={**first['payload']['next_action']['arguments'],'definition':definition,'request':None}
    failed=model_tools.call_native_model('validate_model',args,SOURCE,'continuation-owner')
    assert not failed['ok'] and failed['payload']['status']=='revision_required',failed
    assert failed['payload']['executed'] is False and not get_store().history()
    feedback=failed['payload']['feedback_id']
    folder=tmp_path/'model_design_feedback'/parent
    assert read_json(folder/'latest.json')['feedback_id']==feedback
    record=read_json(folder/(feedback+'.json'))['record']
    expected={**original,'solver':{**original['solver'],'intervention_clock':'step'}}
    assert record['definition']==expected and record['evidence']['phase']=='program_plan_references'
    assert 'post_run_score' not in record['evidence']['advance_reachable_functions']
    assert '无效函数调用' in record['evidence']['instruction']
    fixed=True
    next_args=failed['payload']['next_action']['arguments']
    revised=model_tools.call_native_model('design_model',next_args,SOURCE,'continuation-owner')
    assert revised['ok'] and revised['payload']['status']=='approved',revised
    child=revised['payload']
    assert child['revision_of']==parent and child['design_id']!=parent
    assert child['request']==before['request'] and child['execution']==before['execution']
    assert model_design.load_design(parent)==before
    checked=model_tools.call_native_model('validate_model',{
        **child['next_action']['arguments'],'definition':definition,'request':None},SOURCE,'continuation-owner')
    assert checked['ok'] and checked['payload']['executed'] is False,checked
    assert definition==original and not get_store().history()


def test_program_research_support_cannot_invent_a_missing_platform_research_contract():
    from dayan.agent.model_design import _plan
    plan=json.loads(ControlledProvider().complete([],purpose='model-design-plan',audit=[]))
    plan['kind']='program';plan['mechanisms'][0]['paths']=['source.advance']
    plan['mechanisms'].append({'mechanism':'后续研究评分','paths':['execution.research']})
    with pytest.raises(ValueError,match='真实冻结研究意图'):
        _plan(plan,SOURCE,[],{'ticks':4,'dt':.5})


def test_program_research_support_uses_a_real_frozen_intent_without_fake_advance_scoring(tmp_path,monkeypatch):
    """Real prepared protocol and plan validation; controlled plan, no cloud or solve."""
    import test_design_continuation
    from test_model_research_intent import arguments,QUESTION
    from dayan.agent.model_design import _plan,_requirement_index
    from dayan.research.model_intents import prepare_intent,authoring_contract,load_intent
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    monkeypatch.setattr(test_design_continuation,'SOURCE',QUESTION)
    prepared=prepare_intent(**arguments(),session_id='program-research-support-owner')
    ident=prepared['research_intent_id'];before=load_intent(ident)['protocol']
    action=prepared['next_action']['arguments']
    research=authoring_contract(ident,QUESTION,'program-research-support-owner',action,[],None)
    plan=json.loads(ControlledProvider().complete([],purpose='model-design-plan',audit=[]))
    plan['kind']='program';plan['mechanisms'][0]['paths']=['source.advance']
    plan['mechanisms'].append({'mechanism':'同一意图后续校准、诊断与报告','paths':['execution.research']})
    for row in plan['coverage']:
        if '校准' in _requirement_index(QUESTION)[row['requirement_id']]:
            row.update(role='research',implementation='真实冻结意图 '+ident+' 的后续研究',criteria=[])
    checked=_plan(plan,QUESTION,[],{**action,'research':research})
    assert checked['rule_refs']==[{'mechanism':plan['mechanisms'][0]['mechanism'],'paths':['source.advance']}]
    assert checked['support_refs']==[plan['mechanisms'][-1]]
    assert checked['runtime_refs']==['execution.research']
    rows=[row for row in checked['coverage'] if row['role']=='research']
    assert rows and all(row['research_intent_id']==ident for row in rows)
    assert load_intent(ident)['protocol']==before
    assert not get_store().history()


def test_semantic_review_receives_real_prepared_input_receipts_and_host_solver_stage_boundaries(provider):
    from test_structured_program import bindings,definition
    from dayan.structured_inputs import prepare_bindings
    from dayan.custom_models import validate_definition
    b=bindings()
    _,inputs,evidence=prepare_bindings(b)
    request='使用实际接触输入累计人员接触秒数，保留原ID与当前边。'
    def respond(purpose):
        assert purpose=='scene-semantic-review'
        return json.dumps({'matched':True,'missing':[],'limitations':['受控回复只检验审核上下文，不是实际LLM判定'],
            'checks':[{'quote':request,'refs':['source.advance','runtime_contract.input_pipeline',
                                             'runtime_contract.relation_identity']}]},ensure_ascii=False)
    provider.on_call=respond
    reviewed=review_definition(request,validate_definition(definition(b)),[],{'data_bindings':evidence,'dt':20},plan=None)
    assert reviewed['matched']
    call=next(row for row in provider.calls if row['purpose']=='scene-semantic-review')
    sent=json.loads(call['messages'][1]['content'])
    pipeline=sent['runtime_contract']['input_pipeline']
    assert pipeline['phase']=='before_solver_execution'
    assert [item['records_used'] for item in pipeline['prepared_ports']]==[3,2]
    assert all(item['usage_status']=='prepared_not_yet_executed' for item in pipeline['prepared_ports'])
    assert pipeline['prepared_ports'][0]['input_sha256']==evidence[0]['input_sha256']
    assert inputs['people']['columns']['id']==['001','002','003']
    assert '不要求沙箱联网' in call['messages'][0]['content']
    assert '原始持久ID' in sent['runtime_contract']['relation_identity']


def test_program_discovery_does_not_use_dsl_grammar_to_deny_available_algorithms(monkeypatch):
    from dayan.agent.scenario_tools import modeling_guide
    from dayan import engine_capabilities
    # Read-only discovery fixture; no claim of a solver or scientific run here.
    monkeypatch.setattr(engine_capabilities,'program_status',lambda:{'available':True,'image_id':'explicit-discovery-fixture'})
    guide=modeling_guide('构建连续状态与离散事件双向反馈的数值仿真，无需外部数据或论文。')['payload']
    assert guide['program_engine']['eligible'] and guide['next_tools']['custom_model']=='build_model'
    assert guide['design_first'] and guide['dsl_blocked_by']
    assert any('kind=program' in row for row in guide['notes'])
    assert 'diagnostic_bindings' in guide['model_research']['diagnostic_binding']
    unavailable={'available':False,'reason':'explicit unavailable fixture'}
    monkeypatch.setattr(engine_capabilities,'program_status',lambda:unavailable)
    closed=modeling_guide('构建连续状态与离散事件双向反馈的数值仿真。')['payload']
    assert not closed['program_engine']['eligible']
    assert closed['next_tools']['custom_model'] is None


def test_program_semantic_rejection_and_missing_function_refs_stay_fail_closed(monkeypatch):
    import dayan.llm_client
    from dayan.custom_models import validate_definition
    d=validate_definition(stock_program())
    calls=[]
    def rejected(messages,**kwargs):
        calls.append(messages)
        return json.dumps({'matched':False,'missing':['原需求的非线性反馈没有实现'],
            'checks':[{'quote':'要求非线性反馈','refs':['source.advance']}],'limitations':[]})
    monkeypatch.setattr(dayan.llm_client,'complete',rejected)
    with pytest.raises(ValueError,match='非线性反馈'):review_definition('要求非线性反馈',d,[])
    assert len(calls)==1
