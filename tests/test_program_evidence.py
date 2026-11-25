"""Structural checks do not execute generated code or claim domain validation."""
from copy import deepcopy

import pytest

from dayan.program_evidence import check_plan, fragments, state_dependencies
from dayan.program_scene import validate_scene, validate_frame
from dayan.scene_contract import reference
from dayan.scaling import check_scale
from dayan.program_models import population_plan
from test_program_runtime import definition


def plan(field='total_x'):
    return {'rule_refs':[{'mechanism':'实际位置推进','paths':['source.advance']}],
            'criteria':[{'id':'V1','fields':[field]}],
            'coverage':[{'role':'mechanism','quote':'真实随机移动','criteria':['V1']}]}


def test_source_paths_and_observations_trace_real_state_not_counts_or_zero_times():
    d=definition()
    assert 'def advance' in reference(d,'source.advance')
    assert len(fragments(d))==5
    evidence=check_plan(plan(),d)
    assert evidence['observables']['people']==['people#count']
    assert 'people#count' not in evidence['updated_fields']
    for field in ('people','firms'):
        with pytest.raises(ValueError,match='实际演化'):check_plan(plan(field),d)
    for expr in ('0.*float(state["people"].sum())','time','parameters["rate"]'):
        changed=deepcopy(d)
        changed['source']=changed['source'].replace('float(state["people"].sum())',expr)
        with pytest.raises(ValueError,match='实际演化'):check_plan(plan(),changed)
    with pytest.raises(ValueError,match='不存在'):reference(d,'source.invented')
    with pytest.raises(ValueError,match='advance可达'):
        check_plan({**plan(),'rule_refs':[{'mechanism':'假的动力学引用','paths':['source.frame']}]},d)


def test_new_state_dictionaries_local_metrics_and_pure_helpers_are_traced():
    d=definition()
    d['source']='''def advance(state,parameters,inputs,rng,time,dt):
    return {"state":{"balance":state["balance"]+dt},"events":[]}
def amount(state):
    return state["balance"]*2
def observe(state,parameters,inputs,time):
    metrics={}
    metrics["balance"]=amount(state)
    return metrics
'''
    evidence=state_dependencies(d)
    assert evidence['updated_fields']==['balance']
    assert evidence['observables']=={'balance':['balance']}
    check_plan(plan('balance'),d)


def test_missing_program_references_are_reported_together_without_rewriting_approved_plan():
    p=plan()
    p['rule_refs'][0]['paths']+=['source.integrate_segment','source.update_topology']
    original=deepcopy(p)
    with pytest.raises(ValueError) as failure:check_plan(p,definition())
    assert 'source.integrate_segment' in str(failure.value)
    assert 'source.update_topology' in str(failure.value)
    assert '实际顶层函数' in str(failure.value) and 'advance' in str(failure.value)
    assert p==original


def test_runtime_event_criteria_do_not_require_fabricated_observation_fields():
    p=plan()
    p['criteria'].append({'id':'E1','check':'event_count','event':'decision_accepted','target':2,'fields':[]})
    p['coverage'].append({'role':'mechanism','quote':'真实边界仅接受两次动作','criteria':['E1']})
    check_plan(p,definition())
    # This exception does not relax the actual dynamics/state criterion.
    unchanged=definition()
    unchanged['source']=unchanged['source'].replace('float(state["people"].sum())','0.*float(state["people"].sum())')
    with pytest.raises(ValueError,match='实际演化'):check_plan(p,unchanged)


def test_replaced_dynamic_relation_collection_has_same_count_evidence_as_inplace_assignment():
    # Reproduces the native public-contact case: advance returns a fresh state,
    # then observe counts its actual current relations. No values are injected.
    d={'kind':'program','source':'''def current_relations(inputs,time):
    return [row for row in inputs["edges"] if row["start"] <= time < row["end"]]
def advance(state,parameters,inputs,rng,time,dt):
    result=dict(state)
    result["relations"]=current_relations(inputs,time+dt)
    return {"state":result,"events":[]}
def observe(state,parameters,inputs,time):
    return {"edges":len(state["relations"]),"persons":len(state["ids"])}
'''}
    evidence=check_plan(plan('edges'),d)
    assert 'relations#count' in evidence['updated_fields']
    with pytest.raises(ValueError,match='实际演化'):check_plan(plan('persons'),d)
    unchanged={**d,'source':d['source'].replace('current_relations(inputs,time+dt)','state["relations"]')}
    with pytest.raises(ValueError,match='实际演化'):check_plan(plan('edges'),unchanged)


def test_program_population_roles_and_scene_match_actual_frame_contract():
    d=definition()
    d['populations'][0]['label']='居民'
    compiled=population_plan(d,{'n':13})
    check_scale({'entities':15,'populations':{'居民':13,'企业':2}},compiled)
    with pytest.raises(ValueError,match='各类主体'):
        check_scale({'entities':15,'populations':{'居民':12,'企业':3}},compiled)
    source='13名居民穿过出口，场景保留实际人员。'
    d['scenario']={'title':'出口测试','setting':'坐标直接来自模型','agent_label':'居民','source_request':source,
        'facilities':[{'id':'door','kind':'exit','label':'出口','role':'modeled',
                       'model_refs':['source.advance'],'frame_refs':['source.frame']}],
        'requirements':[{'quote':'穿过出口','model_refs':['source.advance'],'visual_refs':['source.frame']}]}
    validate_scene(d,source)
    actual={'space':{'bounds':[0,0,10,10],'unit':'m'},
            'facilities':[{'id':'door','type':'exit','x':8,'y':3,'width':2,'depth':1}]}
    validate_frame(actual,d)
    with pytest.raises(ValueError,match='全部场景设施'):validate_frame({**actual,'facilities':[]},d)
    with pytest.raises(ValueError,match='偏离'):validate_frame({**actual,'facilities':[{**actual['facilities'][0],'type':'road'}]},d)
    changed=deepcopy(d)
    changed['scenario']['facilities'][0]['model_refs']=['source.observe']
    with pytest.raises(ValueError,match='行为函数'):validate_scene(changed,source)
