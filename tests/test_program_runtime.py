"""Real isolated mathematical verification models, not empirical or native-Agent studies."""
from copy import deepcopy
import json
import os
from pathlib import Path
import platform
import time
from zipfile import ZipFile

import numpy as np
import pytest

from dayan.custom_models import register, factory, validate_definition
from dayan.program_models import population_plan
from dayan.runtime import run_model_full, param_contract, resume_from_checkpoint
from dayan.run_progress import RunPaused, RunProgress
from dayan.run_store import get_store, state_stream
from dayan.solvers.codec import decode
from test_solver_sandbox import LIVE, MODEL

FRAME = '''def frame(state, parameters, inputs, time):
    return {"populations":[
        {"id":"people","type":"person","columns":{"x":state["people"],"y":np.zeros(len(state["people"]))},
         "units":{"x":"m","y":"m"}},
        {"id":"firms","type":"firm","columns":{"capital":state["firms"]},"units":{"capital":"CNY"}}],
        "relations":[{"id":"edge-"+str(i),"source":"people:"+str(a),"target":"people:"+str(b)}
                     for i,(a,b) in enumerate(state["edges"].tolist())],
        "stocks":{"balance":float(state["balance"])},"space":{"bounds":[-5.,-2.,20.,2.],"unit":"m"}}
'''


def definition():
    code=MODEL.replace('inputs["positions"].copy()','np.arange(parameters["n"],dtype=float)')
    start,end=code.index('def frame('),code.index('def validate(')
    code=code[:start]+FRAME+'\n'+code[end:]
    return {'kind':'program','name':'受管混合求解数值验算','description':'随机个体、异类企业、动态图及常微分解析解核验',
        'time_unit':'s','source':code,
        'parameters':{'n':{'type':'int','default':9,'minimum':3,'maximum':100000,'unit':'person'},
                      'rate':{'type':'float','default':.7,'minimum':0,'maximum':2,'unit':'1/s'}},
        'observables':{key:{'label':key,'unit':unit,'equation':equation} for key,unit,equation in [
            ('total_x','m','sum(x_i)'),('balance','CNY','B'),('people','person','len(x)'),
            ('firms','firm','len(firms)'),('edges','edge','len(E)')]},
        'populations':[
            {'id':'people','type':'person','label':'人员','count':'n','dynamic':False,
             'attributes':{key:{'kind':'numeric','unit':'m'} for key in ('x','y')}},
            {'id':'firms','type':'firm','label':'企业','count':2,'dynamic':False,
             'attributes':{'capital':{'kind':'numeric','unit':'CNY'}}}],
        'solver':{'method':'SciPy solve_ivp + seeded Gaussian updates + NetworkX graph rewiring',
                  'description':'rtol=1e-11, atol=1e-12; 同一dt末观察；随机位置仅用于数值复现检查'},
        'equations':[{'id':'B','expression':'dB/dt = rate*(10-B)','function':'advance','meaning':'从B(0)=5趋近10'},
                     {'id':'X','expression':'x_i(k+1)=x_i(k)+N(0,0.25^2)','function':'advance','meaning':'每步正态增量'},
                     {'id':'G','expression':'E(k+1)={(a+1 mod n,b+1 mod n):(a,b) in E(k)}',
                      'function':'advance','meaning':'实际关系边循环重标端点'}],
        'mechanisms':['异类人口','随机位置','连续状态','动态图'],
        'assumptions':['数值验证模型，数据为规定初值，不是实证研究'],
        'limitations':['不具有现实政策预测含义']}


def test_program_registration_is_metadata_only_and_preserves_declared_parameter_and_population_contract(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    d=definition()
    d['source']='raise RuntimeError("must never execute on host")\n'+d['source']
    mid=register(d)['model_id']
    assert factory(mid).clock_type=='managed_program'
    assert param_contract(mid)['params']['n']['type']=='int'
    assert population_plan(validate_definition(d),{'n':42})['entities']==44
    with pytest.raises(ValueError,match='不得取整'):population_plan(d,{'n':3.5})
    with pytest.raises(ValueError,match='对应函数'):validate_definition({**d,'equations':[{**d['equations'][0],'function':'invented'}]})


@LIVE
def test_program_runs_full_numerics_archives_real_environment_and_reports_same_data(tmp_path,monkeypatch):
    from api_client import local_client
    from dayan.server import app
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR',str(tmp_path/'reports'))
    model=register(definition())
    observed=[]
    rr=run_model_full(model['model_id'],parameters={'n':15,'rate':1.2},ticks=5,dt=.2,seed=19,
        capture_state=True,full_frames=True,checkpoint_at=0,on_step=lambda t,view:observed.append((t,view.observe())))
    assert len(rr.observations)==len(rr.state_frames)==len(observed)==6
    assert rr.observations[-1]['balance']==pytest.approx(10-5*np.exp(-1.2),abs=1e-9)
    assert rr.observations[-1]['people']==15 and rr.manifest['actual']['entities']==17
    assert [e['sim_t'] for e in rr.events]==pytest.approx([.1,.3,.5,.7,.9])
    assert all(e['etype']=='relationship_update' for e in rr.events)
    initial=decode(rr.checkpoint['solver_checkpoint']['state'])
    assert rr.checkpoint['t']==0 and float(initial['balance'])==5
    assert rr.state_frames[-1]['relations']!=rr.state_frames[0]['relations']
    assert rr.manifest['model_method']['source']=='archived_program'
    assert all(r['container_removed'] for r in rr.manifest['solver_segments'])
    rid=get_store().save_run(rr,source='actual_isolated_numerical_verification',request_text='数值验证：非原生Agent、非实证模型')
    record=get_store().load(rid)
    m=record['manifest']
    assert m['software']['python'].startswith('3.13.') and m['environment']['system']=='Linux'
    assert m['orchestrator_environment']['python']==platform.python_version()
    assert m['software']['numpy']=='2.2.6' and m['software']['scipy']=='1.17.0'
    archive=tmp_path/'data'/'research_runs'/'code_versions'/(m['code_version']+'.zip')
    with ZipFile(archive) as z:
        assert {'dayan/solvers/Dockerfile','dayan/solvers/requirements.lock','scripts/build_solver_image.py'}<=set(z.namelist())
    stream=state_stream(record)
    assert stream['frames'][-1]['statistics']['density']['n']==15
    assert stream['frames'][-1]['statistics']['distributions']['firms.capital']['mean']==2.5
    with local_client(app) as client:
        response=client.post('/api/report',json={'run_id':rid,'model_id':model['model_id'],
                           'distribution_field':'firms.capital','entity_id':'firms:1','entity_metric':'capital'})
        assert response.status_code==200,response.text
        path=Path(response.json()['path'])
        facts=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
        assert facts['view_analysis']['distribution']['mean']==2.5
        assert facts['view_analysis']['distribution']['not_applicable']==15
        assert 'entity_distribution' in [f['kind'] for f in facts['view_analysis']['figures']]


@LIVE
def test_real_program_recovery_keeps_numerical_rng_graph_events_and_original_endpoint(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    mid=register(definition())['model_id']
    args=dict(ticks=5,dt=.2,seed=19,capture_state=True,full_frames=True)
    expected=run_model_full(mid,**args)
    class PauseAfterSegment(RunProgress):
        def should_pause(self):return self.record is not None
    progress=PauseAfterSegment(tmp_path/'progress',time.monotonic()+600)
    with pytest.raises(RunPaused):run_model_full(mid,**args,_progress=progress)
    first=progress.record
    assert first['state']['solver_checkpoint']['step']==1 and first['row_count']==2
    progress=RunProgress(tmp_path/'progress',time.monotonic()+600)
    actual=run_model_full(mid,**args,_progress=progress)
    assert actual.observations==expected.observations and actual.events==expected.events
    def strip(frames):return [{k:v for k,v in fr.items() if k!='run_id'} for fr in frames]
    assert strip(actual.state_frames)==strip(expected.state_frames)
    assert actual.checkpoint['solver_checkpoint']==expected.checkpoint['solver_checkpoint']
    assert actual.manifest['execution_recovery']['from_step']==1
    assert [r['from_step'] for r in actual.manifest['solver_segments']]==[0,1]
    assert actual.manifest['run_id']==first['state']['run_id']
    with pytest.raises(ValueError,match='已变化'):
        run_model_full(mid,**{**args,'seed':20},_progress=RunProgress(tmp_path/'progress',time.monotonic()+600))


@LIVE
def test_actual_program_frame_contract_rejects_changed_population_units(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    d=definition()
    d['source']=d['source'].replace('"capital":"CNY"','"capital":"USD"')
    mid=register(d)['model_id']
    with pytest.raises(ValueError,match='单位偏离'):run_model_full(mid,ticks=0,dt=1,seed=0,capture_state=True)
    assert not list((tmp_path/'research_runs').glob('R*'))


@LIVE
def test_continuous_policy_times_relative_changes_and_recovery_match_analytic_solution(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    d=definition()
    d['source']='''from scipy.integrate import solve_ivp
def initialize(parameters,inputs,rng):
    return {"balance":5.}
def advance(state,parameters,inputs,rng,time,dt):
    result=solve_ivp(lambda t,y:parameters["rate"]*(10-y),[time,time+dt],[state["balance"]],rtol=1e-11,atol=1e-12)
    return {"state":{"balance":float(result.y[0,-1])},"events":[]}
def observe(state,parameters,inputs,time):
    return {"balance":state["balance"],"rate_read":parameters["rate"]}
def frame(state,parameters,inputs,time):
    return {"stocks":state}
def validate(state,parameters,inputs,time):
    if not 5<=state["balance"]<=10:raise ValueError("balance invariant")
'''
    d['populations']=[]
    d['parameters']={'rate':{**d['parameters']['rate'],'mutable':True}}
    d['observables']={'balance':d['observables']['balance'],
                      'rate_read':{'label':'实际读取速率','unit':'1/s','equation':'rate'}}
    d['equations']=d['equations'][:1]
    d['solver']['intervention_clock']='continuous'
    mid=register(d)['model_id']
    args=dict(ticks=5,dt=.2,seed=5,capture_state=True,full_frames=True,interventions=[
        {'at_t':0.,'params':{'rate':.5}},{'at_t':.35,'params':{'rate':'*2'}},{'at_t':.75,'params':{'rate':'+.5'}}])
    full=run_model_full(mid,**args)
    assert full.observations[-1]['balance']==pytest.approx(10-5*np.exp(-.95),abs=1e-9)
    assert [row['sim_t'] for row in full.observations]==[step*.2 for step in range(6)]
    assert [row['rate_read'] for row in full.observations]==[.5,.5,1.,1.,1.5,1.5]
    assert [event['sim_t'] for event in full.events]==[0.,.35,.75]
    assert full.manifest['actual']['final_effective_parameters']=={'rate':1.5}
    class PauseAfterSegment(RunProgress):
        def should_pause(self):return self.record is not None
    with pytest.raises(RunPaused):
        run_model_full(mid,**args,_progress=PauseAfterSegment(tmp_path/'progress',time.monotonic()+600))
    resumed=run_model_full(mid,**args,_progress=RunProgress(tmp_path/'progress',time.monotonic()+600))
    assert resumed.observations==full.observations and resumed.events==full.events
    assert resumed.checkpoint['solver_checkpoint']==full.checkpoint['solver_checkpoint']
    d['solver']['intervention_clock']='step'
    discrete=register(d)['model_id']
    count=len(list((tmp_path/'data'/'solver_jobs').glob('*.json')))
    with pytest.raises(ValueError,match='步间干预'):run_model_full(discrete,**args)
    assert len(list((tmp_path/'data'/'solver_jobs').glob('*.json')))==count


@LIVE
def test_public_resume_forks_actual_boundary_preserves_pending_policy_rng_and_allows_explicit_extension(tmp_path,monkeypatch):
    from dayan.solvers.codec import digest
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    d=definition()
    d['parameters']['rate']['mutable']=True
    d['solver']['intervention_clock']='continuous'
    mid=register(d)['model_id']
    args=dict(dt=.2,seed=19,capture_state=True,full_frames=True,interventions=[
        {'at_t':.35,'params':{'rate':.4}},{'at_t':1.1,'params':{'rate':'*2'}}])
    full=run_model_full(mid,ticks=9,**args)
    first=run_model_full(mid,ticks=7,checkpoint_at=2,**args)
    original=deepcopy(first.checkpoint)
    middle=resume_from_checkpoint(original,steps=2,dt=.2,capture_state=True,with_initial=True)
    assert middle.observations==full.observations[2:5]
    strip=lambda frames:[{k:v for k,v in fr.items() if k!='run_id'} for fr in frames]
    assert strip(middle.state_frames)==strip(full.state_frames[2:5])
    assert middle.manifest['actual']['effective_parameters']['rate']==.4
    assert middle.manifest['continuation']=={'parent_checkpoint_sha256':original['checkpoint_sha256'],
        'from_t':.4,'parent_endpoint':1.4000000000000001,'requested_endpoint':.8,
        'extended_endpoint':False,'reinitialized':False}
    assert middle.checkpoint['ticks']==7 and middle.checkpoint['interventions'][-1]['at_t']==1.1
    continued=resume_from_checkpoint(middle.checkpoint,steps=5,dt=.2,capture_state=True)
    assert continued.observations==full.observations[5:]
    assert strip(continued.state_frames)==strip(full.state_frames[5:])
    assert continued.events==[e for e in full.events if e['sim_t']>.8]
    assert continued.checkpoint['solver_checkpoint']==full.checkpoint['solver_checkpoint']
    assert continued.manifest['continuation']['extended_endpoint'] is True
    assert continued.manifest['actual']['n_steps']==5 and continued.manifest['actual']['final_t']==1.8
    assert original==first.checkpoint
    assert len({x.manifest['run_id'] for x in [first,middle,continued]})==3
    empty=resume_from_checkpoint(original,steps=0,dt=.2,with_initial=False)
    assert empty.observations==[] and empty.events==[]
    assert empty.checkpoint['solver_checkpoint']==original['solver_checkpoint']
    captured=resume_from_checkpoint(original,steps=0,dt=.2,capture_state=True,with_initial=True)
    assert captured.observations==full.observations[2:3]
    assert strip(captured.state_frames)==strip(full.state_frames[2:3])
    job_count=len(list((tmp_path/'data'/'solver_jobs').glob('*.json')))
    with pytest.raises(ValueError,match='原dt'):resume_from_checkpoint(original,steps=1,dt=.1)
    corrupt=deepcopy(original)
    corrupt['solver_checkpoint']['time']=8
    with pytest.raises(ValueError,match='摘要'):resume_from_checkpoint(corrupt,steps=1,dt=.2)
    changed=deepcopy(original)
    changed['source_fingerprint']='outdated'
    changed['checkpoint_sha256']=digest({k:v for k,v in changed.items() if k!='checkpoint_sha256'})
    with pytest.raises(ValueError,match='源码版本'):resume_from_checkpoint(changed,steps=1,dt=.2)
    assert len(list((tmp_path/'data'/'solver_jobs').glob('*.json')))==job_count
