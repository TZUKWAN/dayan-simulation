"""Real HTTP/storage integration, with temporary storage only; no fake simulation results."""
import csv
import io
import json
import os
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fastapi.testclient import TestClient
from dayan import server
from dayan.run_store import get_store, RunStore
from dayan.research.specs import ExperimentSpec
from dayan.research.experiment import run_experiment
from dayan.agent.tools import tool_run


def run_tests():
    with tempfile.TemporaryDirectory() as folder, \
            patch.dict(os.environ, {'DAYAN_DATA_DIR': folder}), \
            patch.object(server, 'HIST_PATH', Path(folder) / 'legacy.jsonl'):
        client = TestClient(server.app)  # No startup, no cloud, no real user history writes.
        response = client.post('/api/run', json={'model_id': 'NET106', 'ticks': 400,
                               'parameters': {'density': .3, 'p': .2}, 'seed': 7})
        assert response.status_code == 200, response.text
        live = response.json()
        stream = client.post('/api/state_stream', json={'run_id': live['run_id'], 'sample_every': 1}).json()
        assert stream['run_id'] == live['run_id']
        assert stream['observations'] == live['observations'] and live['n'] == 401
        assert len(stream['frames']) == 401
        for obs, frame in zip(live['observations'], stream['frames']):
            assert obs['sim_t'] == frame['sim_t'] and obs['flux'] == frame['aggregates']['flux']
        assert len(get_store().history()) == 1, 'Reading state must not create a second run'
        assert len(client.get('/api/history').json()['entries'][0]['observations']) == 401
        fresh = RunStore(get_store().directory).load(live['run_id'])
        assert fresh['observations'] == live['observations']
        print('[PASS] one saved execution supplies identical 401 observations/frames/history after reload')

        raw = client.get(live['data_url']).content.decode('utf-8-sig')
        assert len(list(csv.DictReader(io.StringIO(raw)))) == 401
        archive = client.get(f"/api/runs/{live['run_id']}/bundle.zip").content
        with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
            assert any(n.startswith('code_versions/') for n in bundle.namelist())
        print('[PASS] full CSV and research ZIP contain all observations and exact source version')

        iv = client.post('/api/run', json={'model_id': 'NET052', 'ticks': 40, 'seed': 7,
              'interventions': [{'at_t': 2., 'params': {'beta': '*0.5'}}]}).json()
        st = client.get(f"/api/runs/{iv['run_id']}/state").json()
        assert st['observations'] == iv['observations']
        assert st['manifest']['interventions'][0]['actual_t'] == 2.
        assert any(e['etype'] == 'intervention' for e in st['events'])
        print('[PASS] saved state retains the exact intervention and its domain event')

        agent = tool_run('NET106', ticks=12, seed=7)
        assert agent['ok'], agent
        assert len(get_store().load(agent['payload']['run_id'])['state_frames']) == 13
        print('[PASS] Agent execution uses the same complete artifact store')

        spec = ExperimentSpec(model_id='NET052', primary_metric='I', ticks=40, seeds=[7, 8],
                  arms=[{'label': 'half', 'interventions': [{'at_t': 2., 'params': {'beta': '*0.5'}}]}]).finalize()
        experiment = run_experiment(spec, persist=True)
        eid = get_store().save_experiment(experiment)
        restored = get_store().load(eid)
        assert len(restored['runs']) == 4
        assert restored['experiment_spec'] == spec.to_dict() and restored['analysis'] == experiment.analysis
        assert len(restored['observations']['half']) == 2
        rerun = run_experiment(ExperimentSpec.from_dict(restored['experiment_spec']))
        assert rerun.observations == restored['observations']
        for run in restored['runs']:
            assert len(get_store().load(run['run_id'])['state_frames']) == 41
        with zipfile.ZipFile(io.BytesIO(get_store().bundle(eid))) as bundle:
            assert sum(n.endswith('/observations.json') for n in bundle.namelist()) == 5
        print('[PASS] experiment archive holds every arm/seed/spec/analysis and reruns identical trajectories')

        get_store().clear_history()
        assert not get_store().history()
        assert get_store().load(live['run_id'])['complete']
        print('[PASS] clearing visible history preserves immutable research artifacts')

        path = get_store().directory / live['run_id'] / 'observations.json'
        path.write_text('[]', encoding='utf-8')
        rejected = client.get(f"/api/runs/{live['run_id']}")
        assert rejected.status_code == 400
        print('[PASS] modified artifacts fail their stored content hash rather than appearing valid')


if __name__ == '__main__':
    run_tests()
