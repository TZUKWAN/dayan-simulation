"""BEH005 mechanism tests; no claim of calibration to a real civil conflict."""
import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.models.beh_abm import EpsteinViolenceModel
from dayan.runtime import run_model_full, resume_from_checkpoint


def model(seed=7, **kwargs):
    m = EpsteinViolenceModel(**kwargs)
    m.initialize({}, {}, None, None, np.random.default_rng(seed))
    return m


class CivilViolence(unittest.TestCase):
    def test_officers_move_and_unique_toroidal_occupancy(self):
        m = model()
        before = m.pos_c.copy()
        for step in range(10):
            m.step(step, 1)
            self.assertEqual(m.validate_state(), [])
        self.assertFalse(np.array_equal(before, m.pos_c))
        self.assertTrue(np.all((m.pos_c >= 0) & (m.pos_c < m.size)))
        m.pos_c[:] = [m.size-1, 0]
        self.assertTrue(m._near(m.pos_c, np.array([0, 0])).all())

    def test_arrest_risk_depends_on_local_cops_and_actives(self):
        m = model(n_agents=4, n_cops=2, size=12, vision=2)
        m.pos_a[:] = [[0, 0], [0, 1], [1, 0], [1, 1]]
        m.pos_c[:] = [[11, 0], [6, 6]]
        m.active[:] = False
        one = m.arrest_probability(0)
        self.assertAlmostEqual(one, 1-np.exp(-2.3))
        m.pos_c[1] = [0, 11]
        self.assertGreater(m.arrest_probability(0), one)
        m.active[1:] = True
        self.assertLess(m.arrest_probability(0), one)
        m.pos_c[:] = [6, 6]
        self.assertEqual(m.arrest_probability(0), 0)

    def test_grievance_arrests_jail_and_release(self):
        m = model(n_agents=5, n_cops=1, size=6, vision=5, legitimacy=0, max_jail_term=3)
        m.hardship[:] = 1; m.risk_av[:] = 0
        m.step(0, 1)
        self.assertEqual(m.arrests, 1)
        self.assertEqual(m.jailed.shape, (5,))
        self.assertTrue(np.all(~m.active[m.jailed > 0]))
        self.assertTrue(np.allclose(m.grievance, m.hardship))
        m.legitimacy = 1
        for step in range(5):
            m.step(step+1, 1)
            self.assertEqual(m.validate_state(), [])
        self.assertFalse(m.active.any())
        self.assertFalse(m.jailed.any())
        self.assertTrue(np.all(m.grievance == 0))

    def test_legitimacy_direction_across_fixed_seeds(self):
        for seed in [7, 8, 9]:
            low, high = model(seed, n_cops=0, legitimacy=0), model(seed, n_cops=0, legitimacy=1)
            low.step(0, 1); high.step(0, 1)
            self.assertGreater(low.active.sum(), high.active.sum())

    def test_actual_frames_and_checkpoint_reproduce(self):
        first = run_model_full('BEH005', ticks=5, dt=1, seed=7, capture_state=True)
        resumed = resume_from_checkpoint(first.checkpoint, steps=3, dt=1, capture_state=True)
        full = run_model_full('BEH005', ticks=8, dt=1, seed=7, capture_state=True)
        self.assertEqual(resumed.observations[-1], full.observations[-1])
        self.assertEqual(resumed.state_frames[-1]['entities'], full.state_frames[-1]['entities'])
        self.assertTrue(any(e['id'].startswith('cop_') for e in first.state_frames[0]['entities']))


if __name__ == '__main__':
    unittest.main(verbosity=2)
