"""Real isolated execution: archive cadence never reduces dynamics or full state."""
import time

import pytest

from dayan.custom_models import register, validate_definition
from dayan.program_models import validate_definition as validate_program
from dayan.run_progress import RunPaused, RunProgress
from dayan.runtime import run_model_full
from test_program_runtime import definition
from test_solver_sandbox import LIVE


def test_archive_interval_is_explicit_validated_and_not_inserted_into_legacy_models():
    original = definition()
    assert 'state_every' not in validate_program(original)
    for invalid in (0, -1, True, 1.5, 'interval_frame'):
        with pytest.raises(ValueError, match='state_every'):
            validate_definition({**original, 'state_every': invalid})
    assert validate_program({**original, 'state_every': 3})['state_every'] == 3


@LIVE
def test_real_archive_cadence_recovery_and_all_step_override_preserve_identical_dynamics(tmp_path, monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path / 'data'))
    model = register({**definition(), 'state_every': 3})['model_id']
    arguments = dict(ticks=7, dt=.2, seed=19, capture_state=True)
    every_step = run_model_full(model, **arguments, full_frames=True)
    sampled = run_model_full(model, **arguments)
    assert sampled.observations == every_step.observations
    assert sampled.events == every_step.events
    assert sampled.checkpoint == every_step.checkpoint
    assert len(sampled.observations) == 8
    assert [frame['sim_t'] for frame in sampled.state_frames] == pytest.approx([0, .6, 1.2, 1.4])
    assert len(every_step.state_frames) == 8
    assert sampled.manifest['frame_retention']['actual_state_every'] == 3
    assert every_step.manifest['frame_retention']['actual_state_every'] == 1
    for actual, expected in zip(sampled.state_frames, [every_step.state_frames[i] for i in (0, 3, 6, 7)]):
        assert {k: v for k, v in actual.items() if k != 'run_id'} == {k: v for k, v in expected.items() if k != 'run_id'}
    class PauseAfterSegment(RunProgress):
        def should_pause(self):
            return self.record is not None
    progress = PauseAfterSegment(tmp_path / 'progress', time.monotonic() + 600)
    with pytest.raises(RunPaused):
        run_model_full(model, **arguments, _progress=progress)
    restored = run_model_full(model, **arguments, _progress=RunProgress(tmp_path / 'progress', time.monotonic() + 600))
    assert restored.observations == sampled.observations
    assert restored.events == sampled.events
    assert restored.checkpoint == sampled.checkpoint
    assert restored.manifest['state_every'] == 3
    assert [frame['sim_t'] for frame in restored.state_frames] == pytest.approx([0, .6, 1.2, 1.4])
