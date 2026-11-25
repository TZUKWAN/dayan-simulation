"""Requested parameters bind once, drive construction, and never silently change seed."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.runtime import run_model_full
from dayan.agent.tools import tool_run
from api_client import local_client as TestClient
from dayan.server import app


def run_tests():
    params = {'cells': 100, 'density': .3, 'p': .2}
    expected = run_model_full('NET106', parameters=params, ticks=60, seed=7)
    nested = run_model_full('NET106', parameters={**params, 'seed': 7}, ticks=60)
    assert nested.observations == expected.observations
    assert nested.manifest['rng']['seed'] == 7
    print('[PASS] nested seed=7 matches the actual explicit-seed trajectory')
    try:
        run_model_full('NET106', parameters={**params, 'seed': 7}, ticks=60, seed=8)
    except ValueError:
        print('[PASS] conflicting seeds are rejected instead of silently choosing one')
    else:
        raise AssertionError('conflicting seeds accepted')
    defaulted = run_model_full('NET106', parameters={'density': .3, 'p': None}, ticks=20, seed=7)
    explicit = run_model_full('NET106', parameters={'density': .3, 'p': .2}, ticks=20, seed=7)
    assert defaulted.observations == explicit.observations
    print('[PASS] nullable braking defaults stay independent of initial density')
    peds = run_model_full('NET113', parameters={'n_agents': 37}, ticks=2, seed=7, capture_state=True)
    assert len(peds.state_frames[0]['entities']) == 37
    road = run_model_full('NET106', parameters={'cells': 120, 'density': .3}, ticks=2, capture_state=True)
    assert road.state_frames[0]['facilities'][0]['length'] == 120
    assert road.observations[0]['n_cars'] == 36
    print('[PASS] population and road dimensions change the actual initialized arrays')
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DAYAN_DATA_DIR': folder}):
        result = tool_run('NET106', parameters={**params, 'seed': 7}, ticks=60)
        assert result['ok'], result
        assert result['payload']['observations'] == expected.observations
        assert not result['payload'].get('ignored_params')
        response = TestClient(app).post('/api/run', json={'model_id': 'NET106',
                  'parameters': {**params, 'seed': 7}, 'ticks': 60})
        assert response.status_code == 200, response.text
        assert response.json()['observations'] == expected.observations
        print('[PASS] Agent and HTTP honor the same seed and numeric trajectory')
    try:
        run_model_full('NET106', parameters={'density': float('nan')}, ticks=2)
    except ValueError:
        print('[PASS] non-finite model parameters fail before construction')
    else:
        raise AssertionError('NaN parameter accepted')


if __name__ == '__main__':
    run_tests()
