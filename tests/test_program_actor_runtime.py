"""Real containers and action consumption; provider controlled for protocol tests."""
import json
import time

import numpy as np
import pytest

from dayan.custom_models import register
from dayan.runtime import run_model_full, resume_from_checkpoint
from dayan.run_progress import RunProgress, RunPaused
from dayan.solvers.codec import decode
from test_solver_sandbox import LIVE


def definition():
    return {'kind':'program','name':'外部主体决策数值基准','description':'验证真实决策输入、状态与可复现记录，不是经验政策模型',
        'time_unit':'s','parameters':{},'populations':[{'id':'people','label':'数值基准主体','type':'person','count':2,
            'dynamic':False,'attributes':{'x':{'kind':'numeric','unit':'m'},'y':{'kind':'numeric','unit':'m'}}}],
        'observables':{'total_x':{'label':'位移合计','unit':'m','equation':'sum(x_i)'},
                       'turns':{'label':'完成宏步','unit':'step','equation':'completed_steps'}},
        'equations':[{'id':'move','expression':'x_i(t+dt)=x_i(t)+LLM_delta_i*dt','function':'advance',
                      'meaning':'使用实际外部响应决定本步速度'}],
        'solver':{'method':'exact step integration of returned velocity','description':'每个宏步边界读取同一状态提出的真实动作'},
        'mechanisms':['外部大模型对各主体当前位置作决策并影响实际位移'],
        'assumptions':['两个独立主体用于接口数值验证'],'limitations':['不具有现实行为预测含义'],
        'decision_policy':{'instruction':'这是明确标注的数值接口验证。根据主体当前位置，为每人选择0.2到0.8 m/s的前进速度delta，目标位置3m。',
            'action_schema':{'type':'object','properties':{'delta':{'type':'number','minimum':.2,'maximum':.8}},
                             'required':['delta'],'additionalProperties':False}},
        'source':'''import numpy as np
import json
def initialize(parameters, inputs, rng):
    return {"x": np.zeros(2), "turns": 0}
def decision_requests(state, parameters, inputs, time):
    return [{"id":"people", "actor_ids":["people:0","people:1"],
             "prompt":json.dumps({"current_x":state["x"].tolist(),"target_x":3,"sim_t":time})}]
def advance(state, parameters, inputs, rng, time, dt, decisions):
    for row in decisions["people"]["actions"]:
        index = int(row["actor_id"].split(":")[1])
        state["x"][index] += row["action"]["delta"] * dt
    state["turns"] += 1
    return {"state": state, "events": [{"type":"movement","time":time+dt}]}
def observe(state, parameters, inputs, time):
    return {"total_x":float(state["x"].sum()),"turns":state["turns"]}
def frame(state, parameters, inputs, time):
    return {"populations":[{"id":"people","type":"person","ids":[0,1],
        "columns":{"x":state["x"],"y":np.zeros(2)},"units":{"x":"m","y":"m"}}]}
def validate(state, parameters, inputs, time):
    assert len(state["x"]) == 2 and np.isfinite(state["x"]).all()
'''}


def expected_from_actual_records(records, dt):
    expected=np.zeros(2)
    for record in records:
        for batch in record['receipts']:
            for row in batch['actions']:
                expected[int(row['actor_id'].split(':')[1])]+=row['action']['delta']*dt
    return expected


@LIVE
def test_real_program_decisions_advance_state_and_recorded_replay_avoids_new_calls(monkeypatch,tmp_path):
    import dayan.llm_client
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    calls=[]
    def controlled(messages,*,audit,**options):
        calls.append(messages)
        audit.append({'call_id':'controlled-runtime-'+str(len(calls)),'ok':True,'purpose':options['purpose']})
        return json.dumps({'actions':[{'actor_id':'people:0','action':{'delta':.3}},
                                      {'actor_id':'people:1','action':{'delta':.6}}]})
    monkeypatch.setattr(dayan.llm_client,'complete',controlled)
    declared=definition()
    declared['source']=declared['source'].replace('dt, decisions):','dt, decisions=None):')
    mid=register(declared)['model_id']
    result=run_model_full(mid,ticks=2,dt=.5,seed=7,capture_state=True,full_frames=True,checkpoint_at=0)
    audit=result.manifest['actor_decisions']
    assert result.observations[0]['turns']==0 and audit['records'][0]['descriptor']['time']==0
    assert result.state_frames[0]['decision_phase']=='before_next_macro_decision'
    assert result.state_frames[-1]['decision_phase']=='final_after_advance'
    assert len(calls)==audit['real_call_count']==2 and audit['action_count']==4
    np.testing.assert_allclose([entity['x'] for entity in result.state_frames[-1]['entities']],expected_from_actual_records(audit['records'],.5))
    assert result.observations[-1]['total_x']==pytest.approx(expected_from_actual_records(audit['records'],.5).sum())
    assert [row['sim_t'] for row in result.events]==sorted(row['sim_t'] for row in result.events)
    fork=resume_from_checkpoint(result.checkpoint,steps=2,dt=.5,capture_state=True,with_initial=True)
    assert fork.observations==result.observations and len(calls)==2
    assert fork.manifest['actor_decisions']['real_call_count']==0 and fork.manifest['actor_decisions']['replay_boundaries']==2
    assert not fork.manifest['llm_calls']


@LIVE
def test_accepted_decision_survives_interruption_before_advance_without_repaying(monkeypatch,tmp_path):
    import dayan.llm_client,dayan.program_runtime
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    calls=[]
    def controlled(messages,*,audit,**options):
        calls.append(messages)
        audit.append({'call_id':'controlled-interruption-'+str(len(calls)),'ok':True,'purpose':options['purpose']})
        return json.dumps({'actions':[{'actor_id':'people:0','action':{'delta':.4}},
                                      {'actor_id':'people:1','action':{'delta':.5}}]})
    monkeypatch.setattr(dayan.llm_client,'complete',controlled)
    actual=dayan.program_runtime.run_segment
    interrupted=[]
    def interrupt(*args,**kwargs):
        if kwargs.get('decision_bundle') is not None and not interrupted:
            interrupted.append(True)
            raise RunPaused('controlled host interruption after accepted response')
        return actual(*args,**kwargs)
    monkeypatch.setattr(dayan.program_runtime,'run_segment',interrupt)
    mid=register(definition())['model_id']
    options=dict(ticks=2,dt=.5,seed=7,capture_state=True,full_frames=True)
    progress=RunProgress(tmp_path/'progress',time.monotonic()+600)
    with pytest.raises(RunPaused):run_model_full(mid,**options,_progress=progress)
    assert len(calls)==1 and progress.record['state']['solver_checkpoint']['step']==0
    restored=run_model_full(mid,**options,_progress=RunProgress(tmp_path/'progress',time.monotonic()+600))
    assert len(calls)==2 and restored.observations[-1]['turns']==2
    assert restored.manifest['execution_recovery']['resumed']
    expected=expected_from_actual_records(restored.manifest['actor_decisions']['records'],.5)
    np.testing.assert_allclose(decode(restored.checkpoint['solver_checkpoint']['state'])['x'],expected)
