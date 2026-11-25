"""Persisted search/recovery with real solver trials; intentionally non-empirical."""
from copy import deepcopy
import json
import math

import pytest

from dayan import datasets
from dayan.custom_models import register
from dayan.research.model_evaluation import prepare_evaluation
from dayan.research.model_studies import create_study, advance_study, load_study, directory
from dayan.solvers.codec import digest
from test_model_evaluation import study,program
from test_solver_sandbox import LIVE


def create(evaluation, **kw):
    options = {'param_grid': {'growth': [1.,2.,-1.]}, 'seeds': [19], 'selection_top': 2,
               'max_loss': {'training': 0.,'validation': 0.,'holdout': 0.}}
    options.update(kw)
    return create_study('数值夹具：训练验证选型后独立检查故意偏离的留出；不代表现实数据', evaluation, **options)


def test_protocol_rejects_duplicate_seeds_grid_and_unscoped_acceptance_before_run(tmp_path,monkeypatch):
    c = study(tmp_path,monkeypatch)
    for change, pattern in [({'seeds':[3,3]},'重复seed'), ({'param_grid':{'growth':[1.,1.]}},'候选重复'),
                            ({'param_grid':{'unknown':[1]}},'待估参数须存在'),
                            ({'max_loss':{'holdout':1.}},'逐分区'), ({'selection_top':4},'短名单')]:
        with pytest.raises(ValueError,match=pattern): create(c,**change)


def test_obsolete_execution_contract_stops_study_before_running_all_candidates(tmp_path,monkeypatch):
    c=study(tmp_path,monkeypatch)
    c['source_fingerprint']='0'*64
    c['sha256']=digest({k:v for k,v in c.items() if k!='sha256'})
    created=create(c)
    result=advance_study(created['study_id'],max_evaluations=10)
    assert result['status']=='invalidated' and result['completed_trials']==1
    assert result['conclusion']=='pre_execution_contract_invalidated'
    assert not list(directory(created['study_id']).glob('trials/*/attempt-*/manifest.json'))
    assert advance_study(created['study_id'])==result


def test_predeclared_diagnostics_finish_before_holdout_and_resume_published_results(tmp_path,monkeypatch):
    from test_model_diagnostics import evaluation,specs
    from dayan.research.model_diagnostics import load_diagnostics
    c=evaluation(tmp_path,monkeypatch)
    made=create_study('解析衰减夹具的完整研究，非实证结论',c,param_grid={'rate':[-2.,-1.]},
        seeds=[7],selection_top=2,max_loss={role:1e-3 for role in ('training','validation','holdout')},
        diagnostics=specs())
    sid=made['study_id'];folder=directory(sid)
    assert load_study(sid)['protocol']['diagnostics']==specs()
    one=advance_study(sid,max_evaluations=4)
    assert one['stage']=='diagnostics' and one['selection']['parameters']=={'rate':-1.}
    assert one['completed_trials']==4 and one['holdout'] is None
    assert not (folder.parent/'holdout_exposures'/f'{sid}.json').exists()
    before=(folder/'state.json').read_bytes()
    two=advance_study(sid,max_evaluations=1)
    assert two['diagnostics']['completed_trials']==1 and two['stage']=='diagnostics'
    assert two['holdout'] is None
    # The real sidecar result was published, but simulate loss of the later study
    # state write. A subsequent call reuses that actual trial and only adds one.
    (folder/'state.json').write_bytes(before)
    three=advance_study(sid,max_evaluations=1)
    assert three['diagnostics']['completed_trials']==2
    assert len(list((folder/'diagnostics').glob('trials/*/attempt-*')))==2
    assert not (folder.parent/'holdout_exposures'/f'{sid}.json').exists()
    done=advance_study(sid,max_evaluations=9)
    assert done['status']=='complete' and done['conclusion']=='passed_declared_checks'
    assert done['completed_trials']==5 and done['diagnostics']['completed_trials']==5
    assert done['selection']==one['selection']
    assert done['holdout']['parameters']=={'rate':-1.}
    assert (folder.parent/'holdout_exposures'/f'{sid}.json').is_file()
    diagnostics=load_diagnostics(c,{'rate':-1.},specs(),[7],directory=folder/'diagnostics')
    assert diagnostics['status']=='complete'
    assert advance_study(sid)==done
    # A resealed fabricated report still fails independent recomputation from
    # the actual preserved numerical trials.
    path=folder/'diagnostics'/'result.json'
    altered=json.loads(path.read_text(encoding='utf-8'))
    altered['reports'][0]['profiles'][0]['points'][0]['metrics']['x']['mean']=999
    altered['sha256']=digest({k:v for k,v in altered.items() if k!='sha256'})
    path.write_text(json.dumps(altered),encoding='utf-8')
    with pytest.raises(ValueError,match='未由实际试验'):load_study(sid)


def test_failed_numerical_checks_stop_before_holdout_exposure(tmp_path,monkeypatch):
    from test_model_diagnostics import evaluation,refinement
    c=evaluation(tmp_path,monkeypatch)
    kwargs={'param_grid':{'rate':[-1.]},'seeds':[7],'selection_top':1,
            'max_loss':{role:1e-3 for role in ('training','validation','holdout')}}
    bad={**refinement(),'dts':[.25,.125,.0625]}
    with pytest.raises(ValueError,match='当前实际dt'):
        create_study('事前无效诊断',c,diagnostics=[bad],**kwargs)
    made=create_study('故意零数值容差的负例',c,diagnostics=[refinement(0.)],**kwargs)
    sid=made['study_id'];folder=directory(sid)
    done=advance_study(sid,max_evaluations=10)
    assert done['status']=='failed' and done['conclusion']=='failed_predeclared_diagnostics'
    assert done['stage']=='diagnostics' and done['completed_trials']==2
    assert done['diagnostics']['completed_trials']==3 and done['holdout'] is None
    assert 'holdout_exposure' not in done
    assert not (folder.parent/'holdout_exposures'/f'{sid}.json').exists()
    assert not list((folder/'trials').glob('holdout-*'))
    assert advance_study(sid)==done


def test_selected_baseline_with_inapplicable_ablation_is_not_silently_accepted(tmp_path,monkeypatch):
    from test_model_diagnostics import evaluation,specs
    c=evaluation(tmp_path,monkeypatch)
    made=create_study('选型等于消融控制的明确失败夹具',c,param_grid={'rate':[0.]},seeds=[7],selection_top=1,
        max_loss={role:None for role in ('training','validation','holdout')},diagnostics=[specs()[-1]])
    done=advance_study(made['study_id'],max_evaluations=5)
    assert done['status']=='failed' and done['conclusion']=='diagnostic_protocol_invalidated'
    assert '相同运行冒充消融' in done['error'] and done['holdout'] is None
    assert not (directory(made['study_id']).parent/'holdout_exposures'/f"{made['study_id']}.json").exists()


@LIVE
def test_resume_real_search_preserves_failed_trials_and_never_reselects_on_holdout(tmp_path,monkeypatch):
    c = study(tmp_path,monkeypatch)
    # Deliberately inconsistent held-out observations are a negative control:
    # they must not make the optimizer choose a different growth parameter.
    rows = [{'t':i,'stock':10+2*i+(100 if i>=4 else 0),
             'score':10*(10+2*i+(100 if i>=4 else 0))} for i in range(6)]
    record = datasets.ingest(json.dumps(rows).encode(),name='故意偏离的留出协议夹具',format='json',source='test-negative-control')
    bindings = deepcopy(c['targets']['bindings'])
    for b in bindings: b['dataset_id'] = record['dataset_id']
    c = prepare_evaluation(c['model']['model_id'],target_bindings=bindings,time_origin=c['targets']['time_origin'],
        split=c['targets']['split'],execution=c['execution'],
        objectives={name:{'weight':obj['weight'],'scale':obj['declaration']} for name,obj in c['objectives'].items()},
        availability=[],information_mode='forecast')
    first = create(c)
    sid = first['study_id']
    folder = directory(sid)
    before = (folder/'state.json').read_bytes()
    assert first['stage'] == 'training' and first['completed_trials'] == 0
    one = advance_study(sid,max_evaluations=1)
    assert one['completed_trials'] == 1 and one['stage'] == 'training'
    assert one['holdout'] is None
    assert create(c)['study_id'] == sid
    attempts_before = list((folder/'trials').glob('*/attempt-*'))
    # Reproduce a worker dying after publishing its actual result but before
    # publishing state. Reuse the earlier genuine state snapshot, not fake output.
    (folder/'state.json').write_bytes(before)
    two = advance_study(sid,max_evaluations=1)
    assert two['completed_trials'] == 2
    assert all((path/'result.json').exists() for path in attempts_before)
    assert len(list((folder/'trials').glob('*/attempt-*'))) == 2
    done = advance_study(sid,max_evaluations=10)
    assert done['status'] == 'complete' and done['stage'] == 'complete'
    assert done['completed_trials'] == 6 and done['failed_trials'] == 1
    assert done['selection']['parameters'] == {'growth':2.}
    assert done['selection']['loss'] == 0
    assert done['selection']['replicate_summary']['sample_sd'] is None  # one seed cannot estimate dispersion
    assert done['holdout']['loss'] == pytest.approx(10000.)
    assert done['conclusion'] == 'failed_predeclared_tolerance'
    assert done['acceptance'] == {'training':True,'validation':True,'holdout':False}
    assert done['holdout_exposure']['independence_status'] == 'no_prior_platform_exposure_record'
    again = advance_study(sid,max_evaluations=10)
    assert again == done
    loaded = load_study(sid)
    held = [trial for trial in loaded['state']['trials'] if trial['role'] == 'holdout']
    assert len(held) == 1 and held[0]['candidate'] == done['selection']['candidate']
    assert len(list((folder/'trials').glob('*/attempt-*'))) == 6
    revised = create(c,param_grid={'growth':[2.,3.]},selection_top=1,parent_study_id=sid)
    assert revised['study_id'] != sid
    assert revised['previous_exposures_at_creation'][0]['study_id'] == sid
    # Changing the actual persisted evidence invalidates the study on read.
    observation_path = folder/loaded['state']['trials'][0]['directory']/'observations.json'
    observation_path.write_text('[]',encoding='utf-8')
    with pytest.raises(ValueError,match='运行证据发生变化'): load_study(sid)


@LIVE
def test_stochastic_replicates_use_each_actual_loss_not_loss_of_mean_prediction(tmp_path,monkeypatch):
    c=study(tmp_path,monkeypatch)
    d=program()
    d['source']=d['source'].replace('parameters["growth"]*dt',
                                   'parameters["growth"]*dt+rng.normal(0.,0.1*dt**0.5)')
    d['equations'][0]['expression']='dS=growth*dt+0.1*dW; S(0)=10'
    d['solver']['description']='数学夹具：独立正态增量标准差0.1*sqrt(dt)，不作现实随机性解释'
    model=register(d)
    c=prepare_evaluation(model['model_id'],target_bindings=c['targets']['bindings'],time_origin=c['targets']['time_origin'],
        split=c['targets']['split'],execution=c['execution'],
        objectives={name:{'weight':obj['weight'],'scale':obj['declaration']} for name,obj in c['objectives'].items()},
        availability=[],information_mode='forecast')
    made=create(c,param_grid={'growth':[2.]},seeds=[19,29],selection_top=1,
                max_loss={role:None for role in ('training','validation','holdout')})
    done=advance_study(made['study_id'],max_evaluations=6)
    assert done['conclusion']=='evaluated_without_full_acceptance_thresholds'
    assert done['completed_trials']==6 and done['failed_trials']==0
    held=done['holdout']
    a,b=held['replicate_losses']
    assert a!=b
    assert held['loss']==pytest.approx((a+b)/2)
    assert held['replicate_summary']['sample_sd']==pytest.approx(abs(a-b)/math.sqrt(2))
    assert held['replicate_summary']['mean_standard_error']==pytest.approx(abs(a-b)/2)
    assert '不是参数区间或现实预测区间' in held['replicate_summary']['scope']
