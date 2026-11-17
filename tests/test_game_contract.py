"""Prompt/parser fixtures test boundaries; these are not live LLM tests."""
import sys
import unittest
from pathlib import Path
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.core import RngStreams
from dayan.engines.games import MatrixGame, llm_game_action, prisoners_dilemma_matrix


class ParserFixture:
    def __init__(self, text):
        self.text, self.messages = text, []

    def chat(self, messages, **kwargs):
        self.messages = messages
        return self.text


class Games(unittest.TestCase):
    def test_masking_and_player_orientation(self):
        g = prisoners_dilemma_matrix()
        c = ParserFixture('{"action": 0}')
        llm_game_action(c, g, 0, masked=True)
        masked = '\n'.join(m['content'] for m in c.messages)
        self.assertNotIn(g.name, masked)
        self.assertNotIn('Coop', masked)
        llm_game_action(c, g, 0, masked=False)
        self.assertIn(g.name, c.messages[-1]['content'])
        self.assertIn('Coop', c.messages[-1]['content'])
        asym = MatrixGame([[1, 2, 3], [4, 5, 6]], [[7, 8, 9], [10, 11, 12]])
        llm_game_action(c, asym, 1, history=[(1, 2)], masked=False)
        self.assertIn('你得12', str(c.messages))
        self.assertIn('列玩家', str(c.messages))

    def test_fallback_consumes_platform_stream_and_is_disclosed(self):
        c, g = ParserFixture('invalid JSON'), prisoners_dilemma_matrix()
        def sequence(seed):
            stream = RngStreams(seed).stream('game', 'player0')
            records = []
            actions = [llm_game_action(c, g, 0, rng=stream, audit=records) for _ in range(32)]
            self.assertTrue(all(r['source'] == 'rng-fallback' for r in records))
            return actions
        self.assertEqual(sequence(7), sequence(7))
        self.assertNotEqual(sequence(7), sequence(8))
        self.assertEqual(len(set(sequence(7))), 2)
        with self.assertRaisesRegex(ValueError, '派生rng'):
            llm_game_action(c, g, 0)

    def test_asymmetric_mixed_equilibrium_indifference(self):
        g = MatrixGame([[3, 0], [0, 1]], [[1, 0], [0, 4]])
        p, q = g.mixed_nash_2x2()
        np.testing.assert_allclose(p, [.8, .2])
        np.testing.assert_allclose(q, [.25, .75])
        self.assertAlmostEqual(*(g.A @ q))
        self.assertAlmostEqual(*(p @ g.B))
        with self.assertRaises(ValueError):
            MatrixGame([[np.nan]], [[1]])


if __name__ == '__main__':
    unittest.main(verbosity=2)
