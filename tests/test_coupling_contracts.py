"""Actual equation, clock, port, and checkpoint verification; no empirical claims."""
import json
import sys
from pathlib import Path
from unittest.mock import patch
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.coupled import CoupledSimulation,GoodwinSDCore,MicroABMSector
from dayan.agent.composer import compose,sweep,ensemble
from dayan.runtime import run_model_full


class CouplingContracts(unittest.TestCase):
    def test_reference_matches_uncoupled_core_and_common_end_time(self):
        sim=CoupledSimulation('reference',seed=7,T=1.05,dt=.1)
        core=GoodwinSDCore();abm=MicroABMSector(seed=7)
        result=sim.run()
        for i in range(11):
            h=.1 if i<10 else .05
            core.step(h);abm.step(h)
        np.testing.assert_allclose(sim.sd.x,core.x,rtol=0,atol=1e-14)
        np.testing.assert_array_equal(sim.abm.employed,abm.employed)
        self.assertEqual(sim.history[0]['t'],0)
        self.assertEqual(sim.history[-1]['t'],1.05)
        self.assertEqual(result['n_steps'],11)
        self.assertEqual(sim.history[-1]['employment_sd'],sim.sd.x[1])
        self.assertEqual(sim.port_trace[-1]['source_t'],1.)

    def test_snapshot_is_frozen_and_reproduces_remaining_random_stream(self):
        original=CoupledSimulation('cyclic',seed=8,T=4.05,dt=.1)
        for _ in range(7):original.step()
        checkpoint=original.snapshot();frozen=json.dumps(checkpoint,sort_keys=True)
        expected=original.run()
        self.assertEqual(json.dumps(checkpoint,sort_keys=True),frozen)
        restored=CoupledSimulation();restored.restore(checkpoint)
        self.assertEqual(restored.run(),expected)
        self.assertEqual(restored.history,original.history)
        self.assertEqual(restored.port_trace,original.port_trace)

    def test_catalog_uses_the_same_equations_and_elapsed_time_without_clipping(self):
        core=GoodwinSDCore();start=core.invariant()
        for _ in range(100):core.step(.01)
        result=run_model_full('ECO019',ticks=10,dt=.1,seed=7)
        final=result.observations[-1]
        np.testing.assert_allclose([final['wage_share'],final['employment']],core.x,atol=1e-11,rtol=0)
        self.assertAlmostEqual(start,core.invariant(),places=12)
        # Classical positive equations may leave the economic fraction domain.
        outside=GoodwinSDCore(x0=(1.2,.8));outside.step(.01)
        self.assertGreater(outside.x[0],1.)

    def test_declared_ports_pass_real_terminal_value_to_initial_parameter(self):
        result=compose([['ECO015',{}],['ECO017',{}]],{'k':'k0'},ticks=4,seed=7,dt=.1)
        a,b=result['stages']
        self.assertEqual(b['params']['k0'],a['final']['k'])
        self.assertEqual(b['mapping_trace'][0]['unit'],'capital/worker')
        self.assertEqual(b['mapping_trace'][0]['target_phase'],'initialization (independent stage clock)')
        with self.assertRaisesRegex(ValueError,'单位|端口'):
            compose([['NET052',{}],['ECO017',{}]],{'I':'k0'},ticks=2,seed=7,dt=.1)

    def test_total_budget_and_invalid_tick_rejection_precede_any_run(self):
        with patch('dayan.agent.composer._execute',side_effect=AssertionError('must not run')) as execute:
            with self.assertRaises(ValueError):sweep('NET106','density',list(range(30)),ticks=100)
            with self.assertRaises(ValueError):ensemble('NET106',list(range(30)),ticks=100)
            with self.assertRaises(ValueError):compose([['ECO015',{'ticks':1.5}]],dt=.1,seed=7)
            execute.assert_not_called()


if __name__=='__main__':unittest.main(verbosity=2)
