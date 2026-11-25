"""Full-state queries must work independently of visual sampling."""
from pathlib import Path

import numpy as np
import pytest

from api_client import local_client
from dayan.agent.model_tools import build_model
from dayan.population import entity_at, encode_column
from dayan.population_analysis import distribution, spatial_density, movement_between
from dayan.run_store import get_store, state_stream
from dayan.server import app
from dayan.view_analysis import analyze_view


def moving_definition(count=4096):
    return {'name':'全量个体查询回归', 'description':'可逐步手算的移动规则，验证完整归档与显示样本分离',
            'kind':'agents', 'time_unit':'s', 'space':{'width':64, 'height':64, 'unit':'m'},
            'agents':{'count':count, 'backend':'array', 'initial':{'x':'id % 64', 'y':'(id - id % 64) / 64',
                       'speed':'1 + id % 7', 'state':0}, 'update':{'x':'(x + speed * dt) % 64'}, 'type':'person',
                       'color_by':'speed'}, 'observables':{'population':'n_agents', 'mean_speed':'mean_speed'}}


def test_measured_small_playback_keeps_all_real_frames_and_requested_stride(tmp_path,monkeypatch):
    from dayan.runtime import run_model_full
    from dayan.custom_models import register
    from dayan.run_store import _bytes
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    result=run_model_full(register(moving_definition(92))['model_id'],ticks=142,dt=1,seed=7,capture_state=True,
                          full_frames=True)
    rid=get_store().save_run(result,source='actual_numerical_playback_fixture')
    record=get_store().load(rid)
    view=state_stream(record)
    assert view['n_entities_max']==92 and view['total_frames']==view['n_frames']==143
    assert view['sample_every']==1 and view['frame_sampling']['budget_satisfied']
    assert view['frame_sampling']['measured_frame_bytes']==len(_bytes(view['frames']))
    selected=state_stream(record,sample_every=5)
    assert [f['sim_t'] for f in selected['frames']]==[*range(0,143,5),142]
    assert selected['frames'][1]['statistics']['movement']==movement_between(record['state_frames'][5],record['state_frames'][0])
    assert len(record['state_frames'])==143  # display sampling did not mutate archival evidence
    client=local_client(app)
    response=client.get(f'/api/runs/{rid}/state')
    assert response.status_code==200,response.text
    assert response.json()['n_frames']==143


def test_measured_large_playback_bounds_actual_payload_and_recomputes_display_intervals(tmp_path,monkeypatch):
    from dayan.runtime import run_model_full
    from dayan.custom_models import register
    from dayan.run_store import _bytes
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    # The measured 151-frame fixture was only 7,747,872 bytes and correctly
    # stayed unsampled. Use an actual 201-frame run to exercise the budget branch.
    result=run_model_full(register(moving_definition(4096))['model_id'],ticks=200,dt=1,seed=7,
                          capture_state=True,full_frames=True)
    rid=get_store().save_run(result,source='actual_numerical_large_playback_fixture')
    record=get_store().load(rid)
    view=state_stream(record)
    assert view['sample_every']>1 and view['n_frames']<view['total_frames']==201
    assert view['n_entities_max']==4096 and view['frame_sampling']['budget_satisfied']
    assert view['frame_sampling']['measured_frame_bytes']==len(_bytes(view['frames']))<=8*1024*1024
    assert view['frames'][0]['sim_t']==0 and view['frames'][-1]['sim_t']==200
    second=view['sample_every']
    assert view['frames'][1]['statistics']['movement']==movement_between(record['state_frames'][second],record['state_frames'][0])
    assert len(record['state_frames'])==201


def test_unsampled_entity_is_queryable_in_api_and_report(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR', str(tmp_path / 'reports'))
    result = build_model(definition=moving_definition(), ticks=3, dt=1, seed=7)
    assert result['ok'], result
    rid = result['payload']['run_id']
    record = get_store().load(rid)
    assert all(entity['id'] != 1 for entity in record['state_frames'][0]['entities'])
    # A real state column cannot be replaced by the presentation color field.
    assert record['state_frames'][0]['entities'][1]['state'] == 0
    assert entity_at(record['state_frames'][0], '1')['state'] == 0
    assert entity_at(record['state_frames'][0], '-1') is None
    assert entity_at(record['state_frames'][0], '4096') is None
    view = analyze_view([record], rid, entity_id='1', entity_metric='x')
    assert [row['x'] for row in view['entity_trace']] == [1, 3, 5, 7]
    assert view['entity_count'] == 4096
    stream = state_stream(record)
    frame = stream['frames'][0]
    assert len(frame['entities']) < 4096
    # The deterministic display sample aliases the repeating seven-speed groups.
    # The analysis must use the full population even when every displayed speed is 1.
    assert {e['speed'] for e in frame['entities']} == {1}
    full = frame['statistics']['distributions']['speed']
    assert full['n'] == 4096
    assert full['counts'] == {'1':586, **{str(i):585 for i in range(2,8)}}
    assert full['mean'] == pytest.approx((586 + sum(range(2,8)) * 585) / 4096)
    assert full['cdf'][0] == [1,586/4096]
    assert full['cdf'][-1] == [7,1]
    assert sum(map(sum, frame['statistics']['density']['counts'])) == 4096
    assert view['distribution'] == full
    assert stream['frames'][1]['statistics']['movement']['comparable'] == 4096
    assert stream['frames'][1]['statistics']['movement']['moved'] == 4096
    client = local_client(app)
    response = client.get(f'/api/runs/{rid}/entities/1?field=x')
    assert response.status_code == 200, response.text
    assert response.json()['state_source'] == 'full_archive'
    assert [row['x'] for row in response.json()['trace']] == [1, 3, 5, 7]
    invalid = client.get(f'/api/runs/{rid}/entities/4096?field=x')
    assert invalid.status_code == 400
    region = [0,0,8,8]
    expected = [1 + (row*64+col)%7 for row in range(8) for col in range(8)]
    selected = client.post(f'/api/runs/{rid}/population', json={'sim_t':0, 'field':'speed', 'region':region})
    assert selected.status_code == 200, selected.text
    assert selected.json()['distribution']['n'] == 64
    assert selected.json()['distribution']['mean'] == pytest.approx(sum(expected)/64)
    region_view = analyze_view([record], rid, sim_t=0, distribution_field='speed', distribution_region=region)
    assert region_view['distribution'] == selected.json()['distribution']
    bad = client.post(f'/api/runs/{rid}/population', json={'sim_t':100, 'field':'speed'})
    assert bad.status_code == 400
    report = client.post('/api/report', json={'model_id':record['model_id'], 'run_id':rid,
                          'entity_id':'1', 'entity_metric':'x', 'primary_metric':'mean_speed'})
    assert report.status_code == 200, report.text
    assert Path(report.json()['path']).is_file()
    import json
    facts = json.loads(Path(report.json()['path']).with_suffix('.json').read_text(encoding='utf-8'))
    trace_figure = next(item for item in facts['view_analysis']['figures'] if item['kind']=='selected_entity_trace')
    assert trace_figure['evidence']['entity_id'] == '1'
    assert [row['x'] for row in facts['view_analysis']['entity_trace']] == [1, 3, 5, 7]
    distribution_figure = next(item for item in facts['view_analysis']['figures'] if item['kind']=='entity_distribution')
    assert distribution_figure['evidence']['distribution'] == full
    quantiles = next(item for item in facts['view_analysis']['figures'] if item['kind']=='speed_quantiles')
    assert quantiles['evidence']['quantiles'] == [[t,2,4,6] for t in range(4)]
    density = next(item for item in facts['view_analysis']['figures'] if item['kind']=='population_density')
    assert density['evidence']['histogram_total'] == 4096
    spatial_time = next(item for item in facts['view_analysis']['figures'] if item['kind']=='spatial_time_occupancy')
    assert spatial_time['evidence']['population_per_frame'] == [4096]*4
    region_report = client.post('/api/report', json={'model_id':record['model_id'], 'run_id':rid, 'sim_t':0,
                               'distribution_region':region, 'distribution_field':'speed'})
    assert region_report.status_code == 200, region_report.text
    region_facts = json.loads(Path(region_report.json()['path']).with_suffix('.json').read_text(encoding='utf-8'))
    figure = next(item for item in region_facts['view_analysis']['figures'] if item['kind']=='entity_distribution')
    assert figure['evidence']['distribution'] == selected.json()['distribution']


def test_full_statistics_quantiles_density_and_regions():
    # A controlled numerical fixture checks exact quantiles, axis orientation,
    # outer-boundary inclusion and explicit out-of-bounds counts.
    raw = np.array([0.,1.,1.,2.,3.,4.,8.,100.])
    frame = {'sim_t':0, 'space':{'bounds':[0,0,2,2]}, 'population':{
        'count':8, 'type':'person', 'color_by':'value', 'columns':{
            'value':encode_column(raw), 'x':encode_column(np.array([0,0,1,1,2,2,-1,3.])),
            'y':encode_column(np.array([0,1,0,1,1,2,0,0.]))}}}
    summary = distribution(frame, 'value')
    assert list(summary['quantiles'].values()) == pytest.approx(np.quantile(raw,[0,.05,.25,.5,.75,.95,1]))
    density = spatial_density(frame, (2,2))
    assert density['counts'] == [[1,1],[1,3]]
    assert density['count_in_bounds'] == 6 and density['outside_bounds'] == 2
    assert distribution(frame, 'value', [0,0,1,2])['n'] == 2
    assert distribution(frame, 'value', [1,0,2,2])['n'] == 4
    with pytest.raises(ValueError, match='边界'):
        distribution(frame, 'value', [1,0,0,2])
    import copy
    previous = copy.deepcopy(frame)
    previous['sim_t'] = -1
    previous['population']['columns']['x'] = encode_column(np.array([0,0,1,1,2,2,-1,-5.]))
    movement = movement_between(frame, previous)
    assert movement['comparable'] == 8 and movement['moved'] == 1 and movement['meanDistance'] == 1


def test_small_scalar_scene_keeps_real_state_separate_from_color(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    model=moving_definition(49)
    model['agents']['backend']='scalar'
    result=build_model(definition=model,ticks=1,seed=7)
    assert result['ok'],result
    frame=get_store().load(result['payload']['run_id'])['state_frames'][-1]
    assert all(e['state']==0 for e in frame['entities'])
    assert {e['speed'] for e in frame['entities']}==set(range(1,8))
