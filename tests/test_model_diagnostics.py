"""Real numerical diagnostic executions, with independent analytic references."""
from copy import deepcopy
import json
import math

import pytest

from dayan import datasets
from dayan.custom_models import register
from dayan.research.model_evaluation import prepare_evaluation
from dayan.research.model_diagnostics import diagnostic_contract, advance_diagnostics
from test_solver_sandbox import LIVE


def evaluation(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    d={'kind':'stocks','name':'衰减的数值诊断夹具','description':'dx/dt=rate*x；独立RK4多项式与解析解参考',
       'time_unit':'second','parameters':{'rate':{'type':'float','default':-1.,'minimum':-2.,'maximum':0.,'unit':'1/second'}},
       'initial_state':{'x':1.},'rates':{'x':'rate*x'},'observables':{'x':'x'},'observable_units':{'x':'1'}}
    model=register(d)
    record=datasets.ingest(json.dumps([{'t':t,'x':math.exp(-t)} for t in (0,1,2)]).encode(),
        name='明确的解析解夹具',format='json',source='test-analytic-reference')
    binding={'id':'x','dataset_id':record['dataset_id'],'observable':'x','time_origin':'数学起点',
        'fields':{'time':{'type':'number','unit':'second'},'value':{'type':'number','unit':'1'}},
        'columns':{'time':{'field':'t','source_unit':'second'},'value':{'field':'x','source_unit':'1'}},
        'time_field':'time','value_field':'value','series_by':[]}
    return prepare_evaluation(model['model_id'],target_bindings=[binding],time_origin='数学起点',
        split={'kind':'forward_time','training_end':0,'validation_end':1},
        execution={'parameters':{},'ticks':4,'dt':.5,'experiment':'numerical-diagnostics','time_atol':1e-10,'data_bindings':[]},
        objectives={'x':{'weight':1.,'scale':{'kind':'external','value':1.,'unit':'1','basis':'已知解析解的单位初态'}}},
        availability=[],information_mode='retrospective_conditioning')


def refinement(limit=1e-3):
    return {'id':'time','kind':'time_refinement','basis':'细化同一RK4模型，按独立递推与解析解核验',
            'outputs':{'x':{'unit':'1','scale':1.}},'dts':[.5,.25,.125],
            'dynamics':'deterministic','max_scaled_change':limit}


def specs():
    return [refinement(),
        {'id':'rate_response','kind':'parameter_sweep','basis':'固定初值，扫描实际衰减系数',
         'outputs':{'x':{'unit':'1','scale':1.}},'parameter':'rate','values':[-2.,-1.,0.]},
        {'id':'remove_decay','kind':'ablation','basis':'方程rate*x在rate=0时该项严格为零',
         'outputs':{'x':{'unit':'1','scale':1.}},'parameters':{'rate':0.},
         'mechanism':'线性衰减','rule_refs':['rates.x','parameters.rate']}]


def rk4(rate,dt,time):
    z=rate*dt
    return (1+z+z*z/2+z**3/6+z**4/24)**round(time/dt)


def test_diagnostic_declarations_reject_changed_horizon_units_and_unproven_strong_convergence(tmp_path,monkeypatch):
    c=evaluation(tmp_path,monkeypatch)
    assert diagnostic_contract(c,specs(),[7])==specs()
    for changed,pattern in [({'dts':[.25,.125,.0625]},'当前实际dt'),
                            ({'dts':[.5,.3,.1]},'整数细分'),
                            ({'outputs':{'x':{'unit':'kg','scale':1.}}},'单位'),
                            ({'dynamics':'strong_convergence','max_scaled_mc_se':1.},'强收敛'),
                            ({'dynamics':'ensemble_moments','max_scaled_mc_se':1.},'至少两个')]:
        with pytest.raises(ValueError,match=pattern):diagnostic_contract(c,[{**refinement(),**changed}],[7])
    bad=specs()[-1]
    bad['rule_refs']=['parameters.rate']
    with pytest.raises(ValueError,match='实际行为/方程'):diagnostic_contract(c,[bad],[7])


def test_refinement_response_and_ablation_run_real_same_model_and_resume_without_duplicate_jobs(tmp_path,monkeypatch):
    c=evaluation(tmp_path,monkeypatch)
    folder=tmp_path/'diagnostics'
    one=advance_diagnostics(c,{'rate':-1.},specs(),[7],directory=folder,max_evaluations=1)
    assert one['status']=='running' and one['completed_trials']==1 and one['total_trials']==5
    done=advance_diagnostics(c,{'rate':-1.},specs(),[7],directory=folder,max_evaluations=9)
    assert done['status']=='complete' and done['new_evaluations']==4
    assert done['completed_trials']==5  # the actual same baseline and ablation jobs are reused
    time,response,ablation=done['reports']
    assert time['status']=='within_declared_resolution_checks'
    assert time['strong_convergence']=='not_established'
    for profile in time['profiles']:
        assert [p['sim_t'] for p in profile['points']]==[0.,.5,1.,1.5,2.]
        for point in profile['points']:
            assert point['metrics']['x']['mean']==pytest.approx(rk4(-1.,profile['dt'],point['sim_t']),abs=1e-12)
    orders=[row['empirical_order'] for row in time['empirical_orders'] if row['empirical_order'] is not None]
    assert orders and all(3.5<p<4.6 for p in orders)
    for profile in response['profiles'][1:]:
        assert profile['points'][-1]['metrics']['x']['mean']==pytest.approx(rk4(profile['parameters']['rate'],.5,2),abs=1e-12)
    expected=1-rk4(-1,.5,2)
    assert ablation['differences_from_baseline'][0]['points'][-1]['metrics']['x']['mean']==pytest.approx(expected)
    before=list(folder.glob('trials/*/attempt-*'))
    again=advance_diagnostics(c,{'rate':-1.},specs(),[7],directory=folder,max_evaluations=1)
    assert again['new_evaluations']==0 and again['sha256']==done['sha256']
    assert list(folder.glob('trials/*/attempt-*'))==before
    for path in before:
        fit=json.loads((path/'fit.json').read_text(encoding='utf-8'))
        assert fit['status']=='not_scored' and fit['loss'] is None
    with pytest.raises(ValueError,match='协议/模型/所选参数已改变'):
        advance_diagnostics(c,{'rate':-.5},specs(),[7],directory=folder)


def test_failed_resolution_is_preserved_and_same_ablated_control_is_rejected(tmp_path,monkeypatch):
    c=evaluation(tmp_path,monkeypatch)
    result=advance_diagnostics(c,{'rate':-1.},[refinement(0.)],[7],directory=tmp_path/'strict',max_evaluations=3)
    assert result['status']=='failed'
    assert result['reports'][0]['max_scaled_change']>0.
    with pytest.raises(ValueError,match='已经处于指定消融设置'):
        advance_diagnostics(c,{'rate':0.},[specs()[-1]],[7],directory=tmp_path/'same')


def test_anomalous_middle_resolution_is_rejected_even_when_coarse_and_finest_agree(tmp_path,monkeypatch):
    base=evaluation(tmp_path,monkeypatch)
    # Deliberately wrong timestep-dependent integrator, not an empirical model.
    # Coarse/fine stay at x=1; only the middle dt=.25 drifts to x=3.
    model=register({'kind':'stocks','name':'中间步长故障负例','description':'显式数值故障，用于独立检出漏检',
        'time_unit':'second','parameters':{'rate':{'type':'float','default':1.,'minimum':0.,'maximum':2.,'unit':'1/second'}},
        'initial_state':{'x':1.},'rates':{'x':'rate if dt == 0.25 else 0'},
        'observables':{'x':'x'},'observable_units':{'x':'1'}})
    c=prepare_evaluation(model['model_id'],target_bindings=base['targets']['bindings'],
        time_origin=base['targets']['time_origin'],split=base['targets']['split'],execution=base['execution'],
        objectives={'x':{'weight':1.,'scale':{'kind':'external','value':1.,'unit':'1','basis':'明确数值故障的单位尺度'}}},
        availability=[],information_mode='retrospective_conditioning')
    result=advance_diagnostics(c,{'rate':1.},[refinement(.01)],[7],directory=tmp_path/'middle',max_evaluations=3)
    report=result['reports'][0]
    assert [profile['points'][-1]['metrics']['x']['mean'] for profile in report['profiles']]==[1.,3.,1.]
    assert result['status']=='failed',report
    assert report['max_scaled_change']==2.
    from dayan.research.model_studies import create_study,advance_study,directory
    made=create_study('数值中间层故障应阻止留出评分',c,param_grid={'rate':[1.]},seeds=[7],selection_top=1,
        max_loss={role:1. for role in ('training','validation','holdout')},diagnostics=[refinement(.01)])
    completed=advance_study(made['study_id'],max_evaluations=8)
    assert completed['status']=='failed' and completed['conclusion']=='failed_predeclared_diagnostics'
    assert completed['holdout'] is None
    assert not (directory(made['study_id']).parent/'holdout_exposures'/(made['study_id']+'.json')).exists()


@LIVE
def test_random_refinement_compares_actual_seed_moments_without_claiming_coupled_paths(tmp_path,monkeypatch):
    from test_model_evaluation import study,program
    c=study(tmp_path,monkeypatch)
    d=program()
    d['source']=d['source'].replace('parameters["growth"]*dt','parameters["growth"]*dt+rng.normal(0.,0.1*dt**0.5)')
    d['equations'][0]['expression']='dS=growth*dt+0.1*dW'
    model=register(d)
    c=prepare_evaluation(model['model_id'],target_bindings=c['targets']['bindings'],time_origin=c['targets']['time_origin'],
        split=c['targets']['split'],execution=c['execution'],
        objectives={name:{'weight':obj['weight'],'scale':obj['declaration']} for name,obj in c['objectives'].items()},
        availability=[],information_mode='forecast')
    spec={**refinement(1.),'outputs':{'stock':{'unit':'件','scale':1.}},
          'dynamics':'ensemble_moments','max_scaled_mc_se':.5,'basis':'两seed协议核验，不宣称充分的Monte Carlo精度'}
    result=advance_diagnostics(c,{'growth':2.},[spec],[19,29],directory=tmp_path/'random',max_evaluations=6)
    assert result['completed_trials']==6 and result['status']=='complete',result
    report=result['reports'][0]
    last=report['differences_from_baseline'][-1]['points'][-1]['metrics']['stock']
    a,b=last['values']
    assert a!=b and last['mean']==pytest.approx((a+b)/2)
    assert last['mean_standard_error']==pytest.approx(abs(a-b)/2)
    assert report['strong_convergence']=='not_established'
    assert all(row['empirical_order'] is None for row in report['empirical_orders'])
