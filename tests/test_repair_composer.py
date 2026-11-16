"""Combinators preserve actual baseline configuration and retain complete run provenance."""
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.agent.tools import call_tool
from dayan.runtime import run_model_full
from dayan.run_store import get_store


def run_tests():
    with tempfile.TemporaryDirectory() as folder, patch.dict(os.environ, {'DAYAN_DATA_DIR': folder}):
        result = call_tool('sweep', model_id='NET106', param='density', values=[.3, .5],
                          parameters={'cells': 120, 'p': .2}, ticks=60, seed=7, field='flux')
        assert result['ok'], result
        payload = result['payload']
        assert payload['primary_metric'] == 'flux'
        group = get_store().load(payload['analysis_id'])
        assert group['analysis']['baseline_parameters'] == {'cells': 120, 'p': .2}
        for run in payload['runs']:
            manifest = run['manifest']
            assert manifest['rng']['seed'] == 7
            assert manifest['actual']['parameters'] == {'cells': 120, 'p': .2, 'density': run['value']}
            expected = run_model_full('NET106', parameters=manifest['actual']['parameters'], ticks=60, seed=7)
            assert run['observations'] == expected.observations
            assert len(get_store().load(run['run_id'])['observations']) == 61
        print('[PASS] sweep preserves cells/p/seed, honors requested flux, and archives complete trajectories')
        comp = call_tool('compare', mid_a='NET110', mid_b='NET111', ticks=10)
        assert comp['ok'] and comp['payload']['table'] and len(comp['payload']['runs']) == 2
        assert all(get_store().load(r['run_id'])['complete'] for r in comp['payload']['runs'])
        print('[PASS] comparison returns both actual series and full numerical table')
        ensemble = call_tool('ensemble', model_id='NET106', seeds=[7, 8], ticks=10)
        assert ensemble['ok'] and ensemble['payload']['seeds'] == [7, 8]
        assert len(ensemble['payload']['runs']) == 2
        chain = call_tool('compose', steps=[['ECO015', {}], ['ECO017', {}]], handoff={'k': 'k0'}, ticks=300)
        assert chain['ok'], chain
        assert len(chain['payload']['stages'][0]['observations']) == 301
        assert chain['payload']['stages'][1]['params']['k0'] == chain['payload']['stages'][0]['final']['k']
        print('[PASS] ensemble and compose preserve every execution and do not truncate observations')
        assert not call_tool('run', model_id='NET106', ticks=-3)['ok']
        assert not call_tool('ensemble', model_id='NET106', seeds=[7.5])['ok']
        from dayan.agent.tools import _coerce_seeds
        assert _coerce_seeds([2**64-1]) == (2**64-1,)
        print('[PASS] Agent rejects negative length and fractional seeds instead of silently coercing them')


if __name__ == '__main__':
    run_tests()
