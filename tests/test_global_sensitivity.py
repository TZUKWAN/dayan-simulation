"""Independent analytic interaction oracle and actual reviewed DSL evaluations."""
import json
from pathlib import Path
import numpy as np
import pytest
from docx import Document
from test_design_continuation import provider,SOURCE
from test_model_study_entry import setup_study
from dayan.research.global_sensitivity import sample,calculate,run


def test_pick_freeze_interaction_matches_independent_variance_decomposition():
    distributions={key:{'kind':'uniform','low':-1.,'high':1.} for key in ('u','v')}
    points=sample(distributions,4096,19)
    values=[p['parameters']['u']+p['parameters']['v']+p['parameters']['u']*p['parameters']['v'] for p in points]
    result=calculate(values,4096,list(distributions),seed=19)
    # Var(u)=Var(v)=1/3, Var(uv)=1/9: S=3/7, ST=4/7.
    np.testing.assert_allclose([r['first_order'] for r in result['indices']],[3/7,3/7],atol=.012)
    np.testing.assert_allclose([r['total_order'] for r in result['indices']],[4/7,4/7],atol=.012)
    constant=calculate([3.]*(4096*4),4096,list(distributions))
    assert constant['status']=='undefined_constant_output' and constant['indices'][0]['first_order'] is None


def test_actual_baseline_samples_resume_keep_real_input_and_generate_same_group_word(provider,monkeypatch):
    from dayan.agent.tools import call_tool,TOOL_SPECS
    from dayan.research.native_contract import protect
    from dayan.research.integration_events import append_event
    from dayan.run_store import get_store
    baseline,_=setup_study(provider,monkeypatch,with_input=True)
    store=get_store();original=store.load(baseline)
    append_event('study-entry-protocol','build_model',{'ok':True,'payload':{'run_id':baseline}})
    args=protect('global_sensitivity',{'baseline_run_id':baseline,'metric':'stock','n':16,'seeds':[7,11],
        'distributions':{'flow':{'kind':'uniform','low':.1,'high':3.9}},'max_evaluations':2},SOURCE,'study-entry-protocol')
    first=call_tool('global_sensitivity',**args)
    assert first['ok'] and first['payload']['completed_runs']==2,first
    aid=first['payload']['analysis_id']
    assert any(s['name']=='global_sensitivity' and 'oneOf' in s['parameters'] for s in TOOL_SPECS)
    rest=protect('global_sensitivity',{'analysis_id':aid,'max_evaluations':200},SOURCE,'study-entry-protocol')
    result=call_tool('global_sensitivity',**rest)
    assert result['ok'],result
    payload=result['payload'];assert payload['status']=='completed' and len(payload['runs'])==96
    for ref in payload['runs']:
        saved=store.load(ref['run_id'])
        assert saved['observations'][0]['stock']==10
        assert saved['observations'][-1]['stock']==pytest.approx(10+2*ref['parameters']['flow'])
        assert ref['value']==saved['observations'][-1]['stock']
        assert saved['manifest']['data_bindings']==original['manifest']['data_bindings']
    assert len({r['run_id'] for r in payload['runs']})==96
    assert run(analysis_id=aid,max_evaluations=1)==payload
    row=payload['analysis']['indices'][0]
    assert row['first_order']==pytest.approx(1,abs=.12) and row['total_order']==pytest.approx(1,abs=.12)
    append_event('study-entry-protocol','global_sensitivity',result)
    report=call_tool('report_run',run_id=payload['run_id'],analysis_id=aid)
    assert report['ok'],report
    path=Path(report['payload']['path']);facts=json.loads(path.with_suffix('.json').read_text(encoding='utf-8'))
    assert len(facts['view_analysis']['run_ids'])==96
    assert facts['analysis']==payload['analysis']
    assert {'sobol_indices','sobol_samples'}<={f['kind'] for f in facts['view_analysis']['figures']}
    assert '全局敏感性实验与数学口径' in '\n'.join(p.text for p in Document(path).paragraphs)
    assert store.load(baseline)['files']==original['files']
    denied=call_tool('global_sensitivity',**{**args,'distributions':{'initial':{'kind':'uniform','low':0,'high':20}}})
    assert not denied['ok'] and '真实数据固定' in denied['error']
    with pytest.raises(ValueError,match='本次原生会话'):
        protect('global_sensitivity',{'baseline_run_id':baseline},SOURCE,'different-session')


def test_mid_sample_solver_checkpoint_resumes_same_run_in_global_workflow(provider,monkeypatch):
    from dayan.run_progress import RunProgress
    from dayan.research.global_sensitivity import folder
    from dayan.collection.storage import read_json
    rid,_=setup_study(provider,monkeypatch,with_input=True)
    actual=RunProgress.should_pause;paused=[]
    def once(self):
        if self.record and not self.record.get('finished') and not paused:
            paused.append(True);return True
        return actual(self)
    monkeypatch.setattr(RunProgress,'should_pause',once)
    first=run(query=SOURCE,baseline_run_id=rid,distributions={'flow':{'kind':'uniform','low':.2,'high':3.8}},metric='stock',n=8,seeds=[7])
    assert first['status']=='pending' and first['completed_runs']==0 and first['solver_progress']['checkpoint_saved']
    progress=read_json(folder(first['analysis_id'])/'evaluations/0/progress.json')['record']
    assert progress['state']['current_checkpoint']['t']<2.
    done=run(analysis_id=first['analysis_id'],max_evaluations=100)
    assert done['status']=='completed' and len(done['runs'])==24
    from dayan.run_store import get_store
    restored=get_store().load(done['runs'][0]['run_id'])
    assert restored['manifest']['execution_recovery']['resumed']
    assert restored['observations'][0]['stock']==10
