"""Regression for H12: invalid execution requests cannot be reported as successful runs."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.runtime import run_model_full


def run_tests():
    for kwargs in ({'ticks': -3}, {'ticks': 1.5}, {'ticks': True},
                   {'dt': 0}, {'dt': float('nan')}, {'dt': float('inf')},
                   {'seed': -1}, {'seed': 1.2}, {'seed': True}):
        try:
            run_model_full('NET106', **kwargs)
        except ValueError:
            print('[PASS] rejected', kwargs)
        else:
            raise AssertionError(f'Invalid execution accepted: {kwargs}')
    result = run_model_full('NET106', ticks=3, seed=7)
    assert len(result.observations) == 4
    assert result.manifest['actual']['n_steps'] == 3
    print('[PASS] valid execution still computes three steps')
    from fastapi.testclient import TestClient
    from dayan.server import app
    # No lifespan/startup: no cloud calls, cache rewrites, or valid-run history writes.
    client = TestClient(app)
    for kwargs in ({'ticks': -3}, {'ticks': True}, {'ticks': 2.5},
                   {'seed': -1}, {'dt': 0}, {'ticks': 10001}):
        response = client.post('/api/run', json={'model_id': 'NET106', **kwargs})
        assert response.status_code in (400, 422), response.text
        print('[PASS] HTTP rejects', kwargs)


if __name__ == '__main__':
    run_tests()
