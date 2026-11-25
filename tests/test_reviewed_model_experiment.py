"""Actual paired mathematical runs; controlled semantics, not a cloud policy study."""
from copy import deepcopy
import json
from pathlib import Path

import pytest

from test_design_continuation import provider,SOURCE
from test_model_study_entry import setup_study
from dayan.agent.tools import call_tool
from dayan.research.integration_events import append_event
from dayan.research.native_contract import protect
from dayan.run_store import get_store


@pytest.mark.parametrize('nested',[False,True])
def test_reviewed_baseline_can_drive_paired_counterfactuals_and_the_same_group_report(provider,monkeypatch,nested):
    if nested:
        from dayan import datasets
        from dayan.agent import model_tools
        actual_ingest=datasets.ingest;actual_native=model_tools.call_native_model
        def ingest(raw,**kwargs):
            if kwargs.get('source')=='test-initial-condition':
                raw=json.dumps({'records':[{'initial':10,'region':'A','time':0},
                                          {'initial':99,'region':'B','time':1}]}).encode()
            return actual_ingest(raw,**kwargs)
        def mapped(tool,arguments,*args,**kwargs):
            arguments=deepcopy(arguments)
            for binding in arguments.get('data_bindings') or []:
                binding.update(path='records',filters={'region':'A'},aggregate='last',order_by='time',
                               source_scope='mathematical-group-A',target_scope='mathematical-group-A')
            return actual_native(tool,arguments,*args,**kwargs)
        monkeypatch.setattr(datasets,'ingest',ingest)
        monkeypatch.setattr(model_tools,'call_native_model',mapped)
    baseline,_=setup_study(provider,monkeypatch,with_input=True)
    store=get_store();saved=store.load(baseline)
    # A controlled native receipt for an actually built/accepted mathematical
    # baseline. This fixture does not claim an installed DSH or cloud call.
    append_event('study-entry-protocol','build_model',{'ok':True,'payload':{'run_id':baseline}})
    arguments={'baseline_run_id':baseline,'query':'不得替换原文的草稿',
               'seeds':[7,11],'metric':'stock','arms':[{'label':'减小流入','params':{'flow':1.}}]}
    guarded=protect('experiment',arguments,SOURCE,'study-entry-protocol')
    assert guarded['query']==SOURCE
    result=call_tool('experiment',**guarded)
    assert result['ok'],result
    group=result['payload'];assert group['n_runs']==4
    assert {r['seed'] for r in group['runs']}=={7,11}
    means={}
    for label,series in group['observations_by_arm'].items():
        means[label]=sum(sum(r['stock'] for r in rows)/len(rows) for rows in series)/len(series)
    assert means=={'基线':12.,'减小流入':11.}
    for member in group['runs']:
        record=store.load(member['run_id'])
        assert record['observations'][0]['stock']==10.
        assert record['manifest']['data_bindings']==saved['manifest']['data_bindings']
        assert record['manifest']['experiment_context']['baseline_run_id']==baseline
        assert record['manifest']['experiment_context']['analysis_question']==SOURCE
        assert record['manifest']['experiment_context']['parameter_changes']==({} if member['arm']=='基线' else {'flow':1.})
    append_event('study-entry-protocol','experiment',result)
    args=protect('report_run',{'run_id':group['run_id'],'experiment_id':group['experiment_id']},SOURCE,'study-entry-protocol')
    report=call_tool('report_run',**args)
    assert report['ok'],report
    facts=json.loads(Path(report['payload']['path']).with_suffix('.json').read_text(encoding='utf-8'))
    assert set(facts['view_analysis']['run_ids'])=={r['run_id'] for r in group['runs']}
    assert facts['research_evidence']['design']['id']==saved['manifest']['scenario_review']['model_design']['design_id']
    assert len(provider.calls)==7  # No extra model design or fabricated effect approval.
    with pytest.raises(ValueError,match='本次原生会话'):
        protect('experiment',arguments,SOURCE,'unrelated-session')
    with pytest.raises(ValueError,match='原文'):
        protect('experiment',arguments,'','study-entry-protocol')
    rejected=call_tool('experiment',**{**guarded,'arms':[{'label':'伪覆盖真实输入','params':{'initial':99.}}]})
    assert not rejected['ok'] and '真实输入' in rejected['error']
