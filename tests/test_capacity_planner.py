"""Actual measured solver resources; controlled semantics for reviewed entry."""
import pytest
from test_design_continuation import provider,SOURCE
from test_model_study_entry import setup_study
from test_solver_sandbox import LIVE
from dayan.research.capacity_planner import plan,measure,predict


def test_reviewed_capacity_protocol_resumes_without_changing_fixed_baseline(provider,monkeypatch):
    from dayan.run_store import get_store
    from dayan.agent.tools import call_tool
    from dayan.research.integration_events import append_event
    from dayan.research.native_contract import protect
    rid,_=setup_study(provider,monkeypatch,with_input=True)
    store=get_store();original=store.load(rid)
    append_event('study-entry-protocol','build_model',{'ok':True,'payload':{'run_id':rid}})
    args=protect('plan_capacity',{'baseline_run_id':rid,'scale_parameter':'ticks','probe_values':[1,2]},SOURCE,'study-entry-protocol')
    first=call_tool('plan_capacity',**args)
    assert first['ok'] and first['payload']['completed_probes']==1,first
    cid=first['payload']['capacity_id']
    done=call_tool('plan_capacity',capacity_id=cid,max_probes=2)
    assert done['ok'],done
    p=done['payload'];assert p['status']=='completed' and len(p['measurements'])==3
    assert p['verified_target_feasible'] and p['recommendation']['ticks']==original['manifest']['actual']['n_steps']
    assert p['recommendation']['parameters']==original['manifest']['actual']['effective_parameters']
    assert not p['recommendation']['applied_to_baseline']
    assert all(m['wall_seconds']>0 and m['archive_bytes']>0 and m['observations']==m['steps']+1 for m in p['measurements'])
    assert 'wall_seconds' in p['relative_error']
    assert store.load(rid)['files']==original['files']
    assert plan(capacity_id=cid)==p


def test_mid_probe_solver_checkpoint_returns_continuation_and_preserves_original_run(provider,monkeypatch):
    from dayan.run_progress import RunProgress
    from dayan.access import data_root
    from dayan.collection.storage import read_json
    rid,_=setup_study(provider,monkeypatch,with_input=True)
    actual=RunProgress.should_pause;paused=[]
    def once(self):
        if self.record and not self.record.get('finished') and not paused:
            paused.append(True);return True
        return actual(self)
    monkeypatch.setattr(RunProgress,'should_pause',once)
    first=plan(query=SOURCE,baseline_run_id=rid,scale_parameter='ticks',probe_values=[2,4])
    assert first['status']=='pending' and first['completed_probes']==0
    checkpoint=read_json(data_root()/'capacity_plans'/first['capacity_id']/'evaluations/0/progress.json')['record']
    assert checkpoint['state']['current_checkpoint']['t']<1.
    done=plan(capacity_id=first['capacity_id'],max_probes=3)
    from dayan.run_store import get_store
    assert done['status']=='completed'
    assert get_store().load(done['measurements'][0]['run_id'])['manifest']['execution_recovery']['resumed']


@LIVE
def test_actual_container_resource_probes_and_target_have_trusted_cpu_rss_and_prediction_error(monkeypatch,tmp_path):
    from test_program_runtime import definition
    from dayan.custom_models import register
    from dayan.runtime import run_model_full
    from dayan.run_store import get_store
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    mid=register(definition())['model_id']
    baseline=run_model_full(mid,parameters={'n':20,'rate':.7},ticks=4,dt=.2,seed=7,capture_state=True)
    rid=get_store().save_run(baseline,source='capacity_numerical_fixture',request_text='数值容量基准，非原生/经验验收')
    context={'proof':{'run_id':rid,'model_id':mid},'options':{'ticks':4,'dt':.2}}
    probes=[]
    for n,steps in ((20,2),(40,2),(80,4)):
        actual=measure(context,{'n':n,'rate':.7},steps,7,'真实容器容量数值基准')
        assert actual['resource_source']=='trusted_container_worker'
        assert actual['peak_worker_rss_bytes']>0 and actual['cpu_seconds']>0 and actual['wire_bytes']>0
        assert actual['entities']==n+2 and actual['observations']==steps+1
        probes.append({**actual,'axis_value':n})
    estimated=predict(probes[:2],80,4,'n')
    assert estimated['wall_seconds']>0 and estimated['peak_worker_rss_bytes']>0
    assert abs(probes[2]['archive_bytes']/estimated['archive_bytes']-1)<.6
