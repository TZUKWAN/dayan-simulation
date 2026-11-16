"""Use genuine traffic and SIS models to prove observations, frames, and checkpoint agree."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.runtime import run_model_full, resume_from_checkpoint


def run_tests():
    rr = run_model_full('NET106', parameters={'density': .3, 'p': .2},
                        ticks=60, seed=7, capture_state=True, checkpoint_at=20)
    assert len(rr.observations) == len(rr.state_frames) == 61
    identities = {e['id'] for e in rr.state_frames[0]['entities']}
    for obs, frame in zip(rr.observations, rr.state_frames):
        assert frame['sim_t'] == obs['sim_t']
        assert frame['run_id'] == rr.manifest['run_id']
        assert frame['aggregates'] == {k: v for k, v in obs.items() if k != 'sim_t'}
        assert {e['id'] for e in frame['entities']} == identities
    print('[PASS] traffic frames and metrics are identical at all 61 actual times')
    print('[PASS] vehicle identities survive movement across all frames')
    assert rr.checkpoint['t'] == 2.0 and rr.checkpoint['model_snapshot']['step_count'] == 20
    continued = resume_from_checkpoint(rr.checkpoint, 40, .1)
    assert continued.observations == rr.observations[21:]
    print('[PASS] intermediate checkpoint is the state at tick 20 and resumes the exact random trajectory')

    iv = [{'at_t': 1.05, 'params': {'beta': '*0.5'}, 'label': 'halve transmission'}]
    sis = run_model_full('NET052', ticks=40, seed=7, interventions=iv, capture_state=True)
    assert sis.manifest['interventions'][0]['actual_t'] == 1.05
    assert len(sis.state_frames) == len(sis.observations)
    for obs, frame in zip(sis.observations, sis.state_frames):
        assert frame['sim_t'] == obs['sim_t']
        assert frame['aggregates']['I'] == obs['I']
    assert any(e['etype'] == 'intervention' for e in sis.events)
    plain = run_model_full('NET052', ticks=40, seed=7)
    assert sis.observations[-1]['I'] < plain.observations[-1]['I']
    print('[PASS] non-grid intervention is applied exactly at 1.05 and is preserved in frames/events')
    try:
        run_model_full('NET106', ticks=2, on_step=lambda *args: (_ for _ in ()).throw(ValueError('capture failed')))
    except ValueError as exc:
        assert 'capture failed' in str(exc)
    else:
        raise AssertionError('failed observer silently reported a successful run')
    print('[PASS] failed state observer cannot silently produce success')
    other = run_model_full('NET106', ticks=60, seed=7)
    assert other.manifest['run_id'] != rr.manifest['run_id']
    print('[PASS] independent requests receive distinct run identifiers')


if __name__ == '__main__':
    run_tests()
