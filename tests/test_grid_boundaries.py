"""Analytic boundary checks through the real build/run/archive/checkpoint paths."""
import numpy as np
import pytest

from dayan.agent.model_tools import build_model
from dayan.agent.scenario_tools import modeling_guide
from dayan.custom_models import validate_definition, population_plan
from dayan.population import entity_at
from dayan.run_store import get_store
from dayan.runtime import run_model_full, resume_from_checkpoint
from dayan.scaling import check_scale, scale_intent


def diffusion(boundary, backend):
    return {'name':'格面边界扩散验算', 'description':'从左下角单位脉冲开始的四邻等权扩散',
            'kind':'agents','time_unit':'MCS','agents':{
                'backend':backend,'grid':{'rows':5,'columns':5,'degree':4,'boundary':boundary,
                    'reductions':{'local':{'op':'mean','field':'u'}}},
                'initial':{'u':'1 if id == 0 else 0'}, 'update':{'u':'local'}, 'color_by':'u'},
            'observables':{'mass':'sum_u'}}


def test_mathematical_report_keeps_the_executed_boundary_and_external_background():
    from dayan.model_method import model_method
    for boundary,term in [('reflecting','格面反射'),('absorbing','吸收'),('periodic','周期环绕')]:
        definition=diffusion(boundary,'array')
        if boundary=='absorbing':definition['agents']['grid']['boundary_values']={'u':2}
        method=model_method('USR_TEST',validate_definition(definition))
        assert any(term in text for text in method['integration'])
        assert any(row['expression']=='boundary = '+boundary for row in method['equations'])
        if boundary!='periodic':assert not any('周期' in text for text in method['integration'])
        if boundary=='absorbing':assert any(row['group']=='吸收域外背景值' and row['expression']=='u = 2' for row in method['equations'])


@pytest.mark.parametrize('backend',['scalar','array'])
@pytest.mark.parametrize('boundary',['periodic','reflecting','absorbing'])
def test_boundary_impulse_mass_and_checkpoint(tmp_path, monkeypatch, boundary, backend):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    result=build_model(definition=diffusion(boundary,backend),ticks=3,seed=7)
    assert result['ok'],result
    record=get_store().load(result['payload']['run_id'])
    frame=record['state_frames'][1]
    actual=[entity_at(frame,str(i))['u'] for i in range(25)]
    expected=np.zeros(25)
    expected[[1,5]]=.25
    if boundary=='periodic':expected[[4,20]]=.25
    if boundary=='reflecting':expected[0]=.5
    assert actual==expected.tolist()
    assert record['manifest']['scale']['boundary']==boundary
    if backend=='array':assert frame['population']['grid']['boundary']==boundary
    assert [row['mass'] for row in record['observations']] == ([1,.5,.375,.28125] if boundary=='absorbing' else [1]*4)
    partial=run_model_full(record['model_id'],ticks=2,seed=7,checkpoint_at=2)
    continued=resume_from_checkpoint(partial.checkpoint,steps=1,dt=1)
    assert continued.observations[-1]==record['observations'][-1]


@pytest.mark.parametrize('backend',['scalar','array'])
def test_absorbing_ghost_is_not_an_agent_to_imitate(tmp_path,monkeypatch,backend):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    definition=diffusion('absorbing',backend)
    definition['agents']['initial']={'u':'id + 1','payoff':-1}
    definition['agents']['grid']['reductions']['local']={'op':'pick_max','field':'u','by':'payoff'}
    result=build_model(definition=definition,ticks=1,seed=7)
    assert result['ok'],result
    frame=get_store().load(result['payload']['run_id'])['state_frames'][-1]
    assert entity_at(frame,'0')['u']==6 # First real neighbor (south), not a zero-valued ghost.


def test_boundary_contract_preserves_explicit_request():
    valid=validate_definition(diffusion('reflecting','array'))
    request=scale_intent('5×5 四邻网格，反射边界')
    check_scale(request,population_plan(valid))
    valid['agents']['grid']['boundary']='periodic'
    with pytest.raises(ValueError,match='边界'):
        check_scale(request,population_plan(valid))
    invalid=diffusion('circular-fiction','array')
    with pytest.raises(ValueError,match='boundary'):
        validate_definition(invalid)
    for name in ('反射边界','吸收边界'):
        guide=modeling_guide(f'5×5 四邻元胞自动机，{name}进行扩散')['payload']
        assert guide['custom_engine']=='fixed_grid',guide
        assert guide['next_tools']['custom_model']=='build_model'


def test_actual_run_cannot_certify_a_different_boundary(tmp_path,monkeypatch):
    from dayan.custom_models import register
    from dayan.agent.verification import certify_run,RunVerificationError
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    model=register(diffusion('reflecting','array'))
    run=run_model_full(model['model_id'],ticks=1,seed=7)
    acceptance={'observables':['mass'],'criteria':[],'events':{},'spatial':True,
        'execution':{'ticks':1,'dt':1,'seed':7,'parameters':{},
                     'verified_scale':{'entities':25,'grid':{'rows':5,'columns':5},'boundary':'absorbing'}}}
    with pytest.raises(RunVerificationError,match='边界'):
        certify_run(run,{},acceptance)


@pytest.mark.parametrize('backend',['scalar','array'])
def test_declared_external_background_is_used_and_never_implied(tmp_path,monkeypatch,backend):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    definition=diffusion('absorbing',backend)
    definition['agents']['initial']['u']=0
    definition['agents']['grid']['boundary_values']={'u':2}
    result=build_model(definition=definition,ticks=1,seed=7)
    assert result['ok'],result
    saved=get_store().load(result['payload']['run_id'])
    assert saved['observations'][-1]['mass']==10 # Twenty outside-facing stencil legs, each contributes 2/4.
    assert entity_at(saved['state_frames'][-1],'0')['u']==1
    definition['agents']['grid']['boundary']='reflecting'
    with pytest.raises(ValueError,match='boundary_values'):
        validate_definition(definition)
