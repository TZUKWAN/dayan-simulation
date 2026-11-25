"""Real event logs are distinct from sampled states and remain auditable in Word."""
from copy import deepcopy
from zipfile import ZipFile

import pytest

from dayan.agent.verification import criteria_for_plan, evaluate_criteria
from test_solver_sandbox import LIVE


def criteria():
    return criteria_for_plan([
        {'id':'V1','check':'end','fields':['balance'],'target':7.517073481042953,'atol':1e-9,
         'reason':'B(1)=10-5 exp(-0.7)，独立解析解'},
        {'id':'V2','check':'event_count','event':'relationship_update','target':5,'reason':'每个宏步一次'},
        {'id':'V3','check':'event_time','event':'relationship_update','occurrence':2,'target':.3,
         'reason':'第二宏步中点，不是宏步末0.4'},
        {'id':'V4','check':'event_value','event':'relationship_update','occurrence':2,'field':'payload.edge_count',
         'target':2,'atol':0,'reason':'实际图的两条边'},
    ], ['balance'])


def test_events_use_actual_chronological_time_and_payload_and_reject_missing_wrong_duplicate():
    checks=criteria()
    assert criteria_for_plan(checks,['balance'])==checks
    rows=[{'sim_t':0.,'balance':5.},{'sim_t':1.,'balance':7.517073481042953}]
    events=[{'etype':'relationship_update','sim_t':t,'payload':{'edge_count':2}}
            for t in (.9,.1,.7,.3,.5)]
    assert all(row['passed'] for row in evaluate_criteria(checks,rows,events))
    wrong=deepcopy(events)
    wrong[3]['sim_t']=.4
    assert not evaluate_criteria(checks,rows,wrong)[2]['passed']
    wrong=deepcopy(events)
    wrong[3]['payload']['edge_count']=3
    assert not evaluate_criteria(checks,rows,wrong)[3]['passed']
    assert not evaluate_criteria(checks,rows,events+events[:1])[1]['passed']
    assert not any(row['passed'] for row in evaluate_criteria(checks,rows,[])[1:])
    wrong=deepcopy(events)
    wrong[0]['sim_t']=float('nan')
    assert not any(row['passed'] for row in evaluate_criteria(checks,rows,wrong)[1:])
    same_time=[{'type':'relationship_update','time':.3,'payload':{'edge_count':n}} for n in (1,2)]
    assert evaluate_criteria(checks,rows,same_time)[3]['passed']
    for delta in ({'target':True},{'target':1.5},{'atol':.01},{'fields':['balance']}):
        bad=deepcopy(checks)
        bad[1].update(delta)
        with pytest.raises(ValueError):criteria_for_plan(bad,['balance'])


def test_constant_balance_conflicts_with_any_actual_time_or_step_including_split_initial_terms():
    for point in ({'check':'start'},{'check':'end'},{'check':'at_step','step':0},
                  {'check':'at_time','time':0},{'check':'at_time','time':.4}):
        with pytest.raises(ValueError,match='冲突'):
            criteria_for_plan([
                {'id':'V1','check':'balance','fields':['a'],'target':3,'reason':'全程常量'},
                {'id':'V2',**point,'fields':['a'],'target':4,'reason':'指定时点'},
            ],['a'])
    with pytest.raises(ValueError,match='冲突'):
        criteria_for_plan([
            {'id':'V1','check':'balance','fields':['a','b'],'target':5,'reason':'错误守恒'},
            {'id':'V2','check':'at_time','time':0,'fields':['a'],'target':2,'reason':'初态'},
            {'id':'V3','check':'at_step','step':0,'fields':['b'],'target':4,'reason':'初态'},
        ],['a','b'])


@LIVE
def test_actual_program_events_are_verified_archived_and_reported_without_fake_sample(tmp_path,monkeypatch):
    from dayan.agent.tools import _archive_run
    from dayan.agent.scenario_tools import report_run
    from dayan.custom_models import register
    from dayan.run_store import get_store
    from test_program_runtime import definition

    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR',str(tmp_path/'reports'))
    from dayan import report_gen
    monkeypatch.setattr(report_gen,'REPORTS_DIR',tmp_path/'reports')
    d=definition()
    d['source']=d['source'].replace('"type": "relationship_update"',
        '"type": "relationship_update", "payload": {"edge_count": len(state["edges"])}')
    mid=register(d)['model_id']
    acceptance={'criteria':criteria(),'observables':['balance'],'events':{},'spatial':True,
                'execution':{'ticks':5,'dt':.2,'seed':19,'parameters':{}}}
    result=_archive_run(mid,{},5,19,.2,None,None,review={},acceptance=acceptance)
    assert result['ok'],result
    record=get_store().load(result['payload']['run_id'])
    assert [row['sim_t'] for row in record['observations']]==[k*.2 for k in range(6)]
    verified=record['manifest']['scenario_review']['runtime_checks']['verification']
    assert verified['status']=='passed'
    assert verified['criteria'][2]['measured']['actual']==pytest.approx(.3)
    assert verified['criteria'][3]['measured']['actual']==2
    report=report_run(record['run_id'],'balance')
    assert report['ok'],report
    path,=(tmp_path/'reports').glob('*.docx')
    with ZipFile(path) as z:
        xml=z.read('word/document.xml').decode()
    assert '事件时刻（第 2 次）' in xml and 'relationship_update · payload.edge_count' in xml
    assert '发生时刻 0.3' in xml and '共 5 次' in xml
