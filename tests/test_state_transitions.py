"""Full-state flow counts, including unsampled agents, identities and missingness."""
from copy import deepcopy

import numpy as np
import pytest

from dayan.population import encode_column
from dayan.population_groups import encode_groups
from dayan.state_transitions import state_history


def dense_frame(count, t=0):
    return {'sim_t': t, 'entities': [{'id': 0, 'type': 'person', 'state': t}],
        'population': {'format': 'dayan-columns-v1', 'count': count, 'type': 'person', 'color_by': 'speed',
            'columns': {'state': encode_column((np.arange(count)+t)%7), 'speed': encode_column(np.ones(count))}}}


def test_million_full_counts_transitions_ignore_biased_display_sample_and_color_alias():
    result = state_history([dense_frame(1_000_000), dense_frame(1_000_000, 1)])
    series, = result['series']
    assert series['scope'] == 'full_population' and result['interpolated'] is False
    assert [s['count'] for s in series['snapshots']] == [1_000_000, 1_000_000]
    counts = {item['state']: item['count'] for item in series['snapshots'][0]['states']}
    assert counts == {0: 142858, **{i: 142857 for i in range(1, 7)}}
    transition, = series['transitions']
    assert transition['matched'] == transition['changed_known'] == 1_000_000
    assert transition['entered'] == transition['exited'] == 0
    assert sum(link['count'] for link in transition['links']) == 1_000_000
    assert all(link['to']['state'] == (link['from']['state']+1)%7 for link in transition['links'])
    missing = dense_frame(20)
    missing['population']['columns'].pop('state')
    assert state_history([missing])['series'] == []
    preview = deepcopy(missing)
    preview['population'].pop('columns')
    with pytest.raises(ValueError, match='显示样本'):
        state_history([preview])


def grouped(t, ids, states, extra=True):
    groups = [{'id': 'people', 'type': 'person', 'columns': {'state': states}, 'ids': ids, 'units': {'state': 'category'}}]
    if extra:
        groups.append({'id': 'other', 'type': 'person', 'columns': {'state': ['S']}, 'ids': ['A'], 'units': {'state': 'category'}})
    return {'sim_t': t, 'population': encode_groups(groups), 'entities': []}


def test_dynamic_ids_reordering_entry_exit_and_missing_are_separate_from_real_states():
    frames = [grouped(0, ['A', 'B', 'C'], ['S', None, 'I']),
              grouped(1, ['C', 'A', 'D'], ['R', None, 'I'], False)]
    result = state_history(frames)
    people = next(row for row in result['series'] if row['group'] == 'people')
    flow, = people['transitions']
    assert (flow['matched'], flow['entered'], flow['exited'], flow['changed_known']) == (2, 1, 1, 1)
    pairs = {(r['from']['present'], r['from']['state'], r['to']['present'], r['to']['state']): r['count'] for r in flow['links']}
    assert pairs == {(True, 'I', True, 'R'): 1, (True, 'S', True, None): 1,
                     (True, None, False, None): 1, (False, None, True, 'I'): 1}
    other = next(row for row in result['series'] if row['group'] == 'other')
    assert other['transitions'][0]['exited'] == 1
    assert other['snapshots'][1]['count'] == 0
    assert sum(r['count'] for r in other['transitions'][0]['links']) == 1


def test_legacy_archived_entities_do_not_claim_full_model_population_and_sparse_times_do_not_interpolate():
    frames = [{'sim_t': 0, 'entities': [{'id': 'a', 'type': 'person', 'state': 'waiting'}]},
              {'sim_t': 5, 'entities': [{'id': 'a', 'type': 'person', 'state': 'walking'}, {'id': 'b', 'type': 'person'}]}]
    history = state_history(frames)
    series, = history['series']
    assert series['scope'] == 'archived_entities'
    assert history['times'] == [0, 5] and not history['interpolated']
    assert series['transitions'][0]['entered'] == 1
    assert series['transitions'][0]['changed_known'] == 1
    with pytest.raises(ValueError, match='严格递增'):
        state_history([frames[0], frames[0]])
    history = state_history([dense_frame(65)])
    assert history['series']
    continuum = dense_frame(65)
    continuum['population']['columns']['state'] = encode_column(np.arange(65)*.2)
    # Chart grouping cannot become a limit on archived states or exported counts.
    actual = state_history([continuum])['series'][0]['snapshots'][0]
    assert len(actual['states']) == 65 and sum(row['count'] for row in actual['states']) == 65


def test_actual_array_run_api_reads_all_states_and_window_from_complete_archive(tmp_path, monkeypatch):
    from api_client import local_client
    from dayan.server import app
    from dayan.agent.model_tools import build_model
    from dayan.run_store import get_store
    from test_population_queries import moving_definition
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR', str(tmp_path/'reports'))
    from dayan import report_gen
    monkeypatch.setattr(report_gen, 'REPORTS_DIR', tmp_path/'reports')
    definition = moving_definition()
    definition['agents']['initial']['state'] = 'id % 7'
    definition['agents']['update']['state'] = '(state + 1) % 7'
    result = build_model(definition=definition, ticks=3, dt=1, seed=7)
    assert result['ok'], result
    rid = result['payload']['run_id']
    record = get_store().load(rid)
    assert {e['state'] for e in record['state_frames'][0]['entities']} == {0}
    client = local_client(app)
    response = client.get(f'/api/runs/{rid}/state-transitions')
    assert response.status_code == 200, response.text
    full = response.json()
    assert full == {'run_id': rid, **state_history(record['state_frames'])}
    assert [item['count'] for item in full['series'][0]['snapshots']] == [4096]*4
    assert [item['matched'] for item in full['series'][0]['transitions']] == [4096]*3
    assert [item['changed_known'] for item in full['series'][0]['transitions']] == [4096]*3
    window = client.get(f'/api/runs/{rid}/state-transitions?start=1&end=3&exclusive=true')
    assert window.status_code == 200
    assert window.json()['times'] == [2, 3]
    assert window.json()['series'][0]['transitions'][0]['from'] == 2
    assert client.get(f'/api/runs/{rid}/state-transitions?start=3&end=1').status_code == 400
    report = client.post('/api/report', json={'model_id': record['model_id'], 'run_id': rid, 'sim_t': 2,
                                             'primary_metric': 'mean_speed'})
    assert report.status_code == 200, report.text
    import json
    from pathlib import Path
    facts = json.loads(Path(report.json()['path']).with_suffix('.json').read_text(encoding='utf-8'))
    figure = next(fig for fig in facts['view_analysis']['figures'] if fig['kind'] == 'state_transitions')
    assert figure['evidence']['snapshots'] == full['series'][0]['snapshots']
    assert figure['evidence']['transition'] == full['series'][0]['transitions'][1]
    assert figure['evidence']['scope'] == 'full_population'
