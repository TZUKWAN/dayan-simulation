"""Actual registered-program evaluations against a known mathematical fixture."""
from copy import deepcopy
import json

import pytest

from dayan import datasets
from dayan.custom_models import register
from dayan.research.model_evaluation import prepare_evaluation, evaluate_role, evaluate_diagnostic, score_observations, model_identity
from dayan.solvers.codec import digest
from test_solver_sandbox import LIVE
from test_program_harness import stock_program


def program():
    d = stock_program()
    d['parameters'] = {'growth': {'type': 'float', 'default': 2., 'minimum': -1, 'maximum': 4, 'unit': '件/小时'}}
    d['source'] = d['source'].replace('2.*dt', 'parameters["growth"]*dt')
    d['source'] = d['source'].replace('def advance(state,parameters,inputs,rng,time,dt):',
        'def advance(state,parameters,inputs,rng,time,dt):\n    if parameters["growth"] < 0: raise ValueError("fixture intentional negative growth failure")')
    d['source'] = d['source'].replace('return {"stock":state["stock"]}',
                                     'return {"stock":state["stock"],"score":10*state["stock"]}')
    d['observables']['score'] = {'label': '纯数学第二通道', 'unit': '点', 'equation': 'Q=10*S'}
    d['equations'][0]['expression'] = 'dS/dt=growth; S(0)=10'
    return d


def study(tmp_path, monkeypatch, **changes):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path/'data'))
    model = register(program())
    rows = [{'t': i, 'stock': 10+2*i, 'score': 10*(10+2*i)} for i in range(6)]
    record = datasets.ingest(json.dumps(rows).encode(), name='已知参数数学夹具', format='json', source='test-fixture')
    bindings = []
    for name, unit in [('stock','件'), ('score','点')]:
        bindings.append({'id': name, 'dataset_id': record['dataset_id'], 'observable': name,
            'fields': {'t': {'type': 'number', 'unit': '小时'}, 'v': {'type': 'number', 'unit': unit},
                       'available':{'type':'number','unit':'小时'}},
            'columns': {'t': {'field': 't', 'source_unit': '小时'}, 'v': {'field': name, 'source_unit': unit},
                        'available':{'field':'t','source_unit':'小时'}},
            'time_field': 't', 'value_field': 'v', 'series_by': [], 'time_origin': '实验零点',
            'available_field':'available','availability_basis':'数学夹具规定即时可知，不是现实发布数据'})
    kwargs = {'target_bindings': bindings, 'time_origin': '实验零点',
        'split': {'kind': 'forward_time', 'training_end': 1, 'validation_end': 3},
        'execution': {'parameters': {}, 'ticks': 10, 'dt': .5, 'data_bindings': [],
                      'experiment': 'known-equation-fixture', 'time_atol': 1e-10},
        'objectives': {name: {'weight': w, 'scale': {'kind': 'training_std'}} for name,w in [('stock',1),('score',3)]},
        'availability': [], 'information_mode': 'forecast'}
    kwargs.update(changes)
    return prepare_evaluation(model['model_id'], **kwargs)


def test_objective_scales_use_only_training_and_require_exact_model_times(tmp_path,monkeypatch):
    c = study(tmp_path,monkeypatch)
    assert c['objectives']['stock']['scale'] == 1
    assert c['objectives']['score']['scale'] == 10
    assert c['targets']['roles']['holdout'][0]['time'] == 4
    bad = deepcopy(c['execution'])
    bad['dt'] = 2
    with pytest.raises(ValueError,match='不对应实际模型步'):
        study(tmp_path,monkeypatch,execution=bad)
    with pytest.raises(ValueError,match='零权重'):
        study(tmp_path,monkeypatch,objectives={**{n:{'weight':1,'scale':{'kind':'training_std'}} for n in ('stock','score')},
                                              'score':{'weight':0,'scale':{'kind':'training_std'}}})


def test_missing_duplicate_and_nonfinite_actual_observations_cannot_score_as_success(tmp_path,monkeypatch):
    c = study(tmp_path,monkeypatch)
    target = c['targets']['roles']['training']
    good = [{'sim_t':0.,'stock':10.,'score':100.},{'sim_t':1.,'stock':12.,'score':120.}]
    assert score_observations(good,target,c['objectives'],time_atol=1e-10)['loss'] == 0
    for observations, pattern in [(good[:1], '恰好匹配'), ([good[0],good[0]], '严格递增'),
                                  ([good[0],{'sim_t':1.,'stock':12.,'score':None}], '有限'),
                                  ([good[0],{**good[1],'stock':float('inf')}], '有限')]:
        with pytest.raises(ValueError,match=pattern):
            score_observations(observations,target,c['objectives'],time_atol=1e-10)


def test_dsl_units_preserve_old_model_identity_and_enable_real_same_evaluator(tmp_path,monkeypatch):
    from dayan.custom_models import factory,validate_definition
    from dayan.output_contract import output_contract
    from dayan.runtime import run_model_full
    from dayan.research.model_studies import create_study,advance_study
    c=study(tmp_path,monkeypatch)
    d={'kind':'stocks','name':'DSL参数恢复数值夹具','description':'线性导数的已知解析解，仅验证程序协议',
       'time_unit':'小时','parameters':{'growth':{'default':2.,'minimum':0.,'maximum':4.,'unit':'件/小时'}},
       'initial_state':{'stock':10.},'rates':{'stock':'growth'},'observables':{'stock':'stock','score':'10*stock'}}
    old=register(d)
    assert 'observable_units' not in factory(old['model_id']).definition
    assert register(d)['model_id']==old['model_id']
    assert run_model_full(old['model_id'],ticks=2,dt=.5,seed=7).observations[-1]['stock']==12.
    with pytest.raises(ValueError,match='未声明的单位'):model_identity(old['model_id'])
    with pytest.raises(ValueError,match='完整覆盖'):validate_definition({**d,'observable_units':{'stock':'件'}})
    model=register({**d,'observable_units':{'stock':'件','score':'点'}})
    assert model['model_id']!=old['model_id']
    assert output_contract(model['model_id'],reference_results={})['fields']['stock']['unit']=='件'
    evaluation=prepare_evaluation(model['model_id'],target_bindings=c['targets']['bindings'],time_origin=c['targets']['time_origin'],
        split=c['targets']['split'],execution=c['execution'],
        objectives={name:{'weight':obj['weight'],'scale':obj['declaration']} for name,obj in c['objectives'].items()},
        availability=[],information_mode='forecast')
    made=create_study('DSL已知线性方程参数恢复，不是现实拟合',evaluation,param_grid={'growth':[1.,2.,3.]},
        seeds=[7],selection_top=2,max_loss={role:0. for role in ('training','validation','holdout')})
    done=advance_study(made['study_id'],max_evaluations=6)
    assert done['conclusion']=='passed_declared_checks' and done['selection']['parameters']=={'growth':2.}
    assert done['completed_trials']==6 and done['holdout']['loss']==0


@LIVE
def test_candidate_loss_is_from_actual_container_model_and_failed_trials_remain(tmp_path,monkeypatch):
    c = study(tmp_path,monkeypatch)
    original_holdout = deepcopy(c['targets']['roles']['holdout'])
    exact = evaluate_role(c,parameters={'growth':2.},seed=19,role='training',directory=tmp_path/'exact')
    wrong = evaluate_role(c,parameters={'growth':1.},seed=19,role='training',directory=tmp_path/'wrong')
    failed = evaluate_role(c,parameters={'growth':-1.},seed=19,role='training',directory=tmp_path/'failed')
    held = evaluate_role(c,parameters={'growth':2.},seed=29,role='holdout',directory=tmp_path/'held')
    assert exact['status'] == held['status'] == wrong['status'] == 'evaluated', (exact,wrong,held)
    assert exact['loss'] == held['loss'] == 0
    assert wrong['loss'] == pytest.approx(.5)
    assert failed['status'] == 'failed' and failed['loss'] is None
    assert 'negative growth failure' in failed['error']['message']
    assert json.loads((tmp_path/'failed/result.json').read_text(encoding='utf-8')) == failed
    fit = json.loads((tmp_path/'wrong/fit.json').read_text(encoding='utf-8'))
    assert fit['observables']['stock']['rmse'] == pytest.approx((.5)**.5)
    assert fit['observables']['score']['rmse'] == pytest.approx(50**.5)
    manifest = json.loads((tmp_path/'exact/manifest.json').read_text(encoding='utf-8'))
    observations = json.loads((tmp_path/'exact/observations.json').read_text(encoding='utf-8'))
    assert manifest['actual']['parameters']['growth'] == 2.
    assert manifest['protocol'] == 'managed_program'
    assert all(segment['container_removed'] for segment in manifest['solver_segments'])
    assert [row['sim_t'] for row in observations] == [0.,.5,1.]
    assert exact['observations_sha256'] == digest(observations)
    assert not (tmp_path/'data/research_runs/runs').exists()  # no trial spam in ordinary history
    assert c['targets']['roles']['holdout'] == original_holdout
    changed = deepcopy(c)
    changed['execution']['dt'] = 1
    with pytest.raises(ValueError,match='哈希不一致'):
        evaluate_role(changed,parameters={'growth':2.},seed=19,role='training',directory=tmp_path/'tampered')
    assert not (tmp_path/'tampered').exists()


@LIVE
def test_full_horizon_diagnostic_execution_does_not_score_holdout(tmp_path,monkeypatch):
    from dayan.research.model_studies import _verified_trial
    c=study(tmp_path,monkeypatch)
    path=tmp_path/'diagnostic'
    result=evaluate_diagnostic(c,parameters={'growth':2.},seed=19,directory=path)
    assert result['status']=='executed' and result['loss'] is None, result
    assert result['actual']['final_t']==5.
    assert json.loads((path/'observations.json').read_text(encoding='utf-8'))[-1]['stock']==20.
    fit=json.loads((path/'fit.json').read_text(encoding='utf-8'))
    assert fit['status']=='not_scored' and 'points' not in fit
    assert _verified_trial(path)==result
    with pytest.raises(ValueError,match='角色不合法'):
        evaluate_role(c,parameters={},seed=19,role='diagnostic',directory=tmp_path/'wrong-role')
