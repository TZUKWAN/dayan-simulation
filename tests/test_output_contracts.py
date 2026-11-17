"""Source output contracts checked against actual built-in model executions."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dayan.output_contract import output_contract
from dayan.agent.metadata import search_capabilities
from dayan.research.compiler import compile_research
from dayan.runtime import run_model_full


class OutputContracts(unittest.TestCase):
    def test_sir_joint_search_and_actual_fields(self):
        found = search_capabilities('SIR', has_param=['beta', 'gamma'], observable=['S', 'I', 'R'])
        self.assertIn('NET053', [c['model_id'] for c in found])
        schema = output_contract('NET053')
        self.assertEqual({schema['fields'][k]['type'] for k in ('S', 'I', 'R')}, {'number'})
        rr = run_model_full('NET053', ticks=3, seed=7)
        self.assertTrue({'S', 'I', 'R'} <= rr.observations[-1].keys())
        self.assertEqual(rr.manifest['output_contract'], schema)
        self.assertFalse(schema['runtime_verified'])

    def test_cache_not_a_measurement_or_source_of_fields(self):
        schema = output_contract('NET052')
        self.assertIn('I', schema['fields'])
        self.assertTrue(schema['evidence'])
        self.assertNotIn('observable_samples', schema)

    def test_ambiguous_and_invalid_metrics_require_choice(self):
        ambiguous = compile_research('ECO015 对照实验')
        self.assertIsNone(ambiguous.experiment_spec)
        self.assertTrue(any('主要结局指标' in w for w in ambiguous.warnings))
        invalid = compile_research('NET052 对照实验', metric='invented_metric')
        self.assertIsNone(invalid.experiment_spec)
        self.assertIn('未声明指标', invalid.warnings[0])


if __name__ == '__main__':
    unittest.main(verbosity=2)
