"""Policy changes act on explicitly declared mechanisms, never arbitrary structural fields."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.runtime import run_model_full, param_contract


def run_tests():
    contract = param_contract('NET106')
    assert contract['params']['cells']['mutable_at_runtime'] is False
    assert contract['params']['p']['mutable_at_runtime'] is True
    assert {c['param'] for c in contract['policies']} == {'p', 'vmax'}
    print('[PASS] structural cells and dynamic p/vmax are explicitly distinguished')
    for params in ({'cells': '*1.2'}, {'p': 2.0}, {'p': -1.0}):
        try:
            run_model_full('NET106', ticks=30, interventions=[{'at_t': 1, 'params': params}])
        except ValueError:
            pass
        else:
            raise AssertionError(f'Invalid intervention accepted: {params}')
    print('[PASS] invalid structural/range interventions fail clearly before a broadcast error')
    low = run_model_full('NET106', ticks=60, seed=7,
             interventions=[{'at_t': 2., 'params': {'p': .2}}])
    high = run_model_full('NET106', ticks=60, seed=7,
             interventions=[{'at_t': 2., 'params': {'p': .95}}])
    assert low.observations[:21] == high.observations[:21]
    assert low.observations[-1]['flux'] != high.observations[-1]['flux']
    assert high.manifest['interventions'][0]['params']['p'] == .95
    print('[PASS] two actual policy values preserve the paired baseline and change post-intervention traffic')
    try:
        run_model_full('NET052', ticks=5, interventions=[{'at_t': 2., 'params': {'beta': '*0.5'}}])
    except ValueError:
        print('[PASS] interventions beyond the requested horizon are rejected')
    else:
        raise AssertionError('Out-of-range intervention reported successful')


if __name__ == '__main__':
    run_tests()
