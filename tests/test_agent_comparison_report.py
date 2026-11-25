"""Agent report tool uses the existing full experiment report, not one seed only."""
import json
from pathlib import Path

import pytest
from fastapi import HTTPException

from api_client import local_client
from dayan.agent.model_delivery import delivery_contract
from dayan.agent.scenario_tools import report_run
from dayan.agent.tools import TOOL_SPECS
from dayan.server import app


def test_agent_can_report_all_actual_paired_runs_through_the_native_tool(monkeypatch,tmp_path):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR',str(tmp_path/'reports'))
    with local_client(app) as client:
        response=client.post('/api/experiments',json={
            'model_id':'NET106','ticks':25,'dt':.1,'seeds':[7,13],
            'primary_metric':'flux','baseline_params':{'density':.3,'p':.2},
            'arms':[{'label':'干预组','params':{},'interventions':[{
                'at_t':1.,'params':{'p':.95},'label':'提高慢化概率'}]}]})
        assert response.status_code==200,response.text
        experiment=response.json()
        selected=next(r for r in experiment['runs'] if r['arm']=='干预组' and r['seed']==7)
        report=report_run(selected['run_id'],primary_metric='flux',experiment_id=experiment['experiment_id'])
        assert report['ok'],report
        facts=json.loads(Path(report['payload']['path']).with_suffix('.json').read_text(encoding='utf-8'))
        view=facts['view_analysis']
        assert set(view['run_ids'])=={r['run_id'] for r in experiment['runs']}
        assert view['comparisons'][0]['paired_n']==2
        expected={}
        for arm,series in experiment['observations_by_arm'].items():
            expected[arm]=sum(sum(row['flux'] for row in rows)/len(rows) for rows in series)/len(series)
        for group in view['groups']:
            assert group['mean']==pytest.approx(expected[group['name']],abs=1e-12)
        assert len(view['run_ids'])==4 and report['payload']['figure_count']>=3
        with pytest.raises(HTTPException):
            report_run(selected['run_id'],experiment_id=experiment['experiment_id'],analysis_id='not-both')
    spec=next(s for s in TOOL_SPECS if s['name']=='report_run')
    assert {'experiment_id','analysis_id'}<=spec['parameters']['properties'].keys()
    contract=delivery_contract()['comparisons']
    assert contract['report_arguments']['experiment_id']=='returned experiment_id'
