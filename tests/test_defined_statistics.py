"""Undefined initial statistics stay null; no NaN, zero padding or fake estimates."""
import json
import sys
from pathlib import Path
import unittest
import warnings
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.runtime import run_model_full
from dayan.models.eco_flagship_lite import KirmanModel,SantaFeLiteModel


class DefinedStatistics(unittest.TestCase):
    def test_initial_samples_do_not_produce_nonfinite_statistics(self):
        cases={'BEH007':'mean_attendance','BEH008':'mean_ones_share',
            **{mid:'coop_rate' for mid in ('BEH069','BEH070','BEH071','BEH072','BEH073')},
            'BEH078':'mean_vengeance','BEH079':'mean_vengeance',
            'ECO046':'vol_ratio','ECO048':'excess_kurtosis','ECO049':'mean_share'}
        with warnings.catch_warnings():
            warnings.simplefilter('error',RuntimeWarning)
            for mid,metric in cases.items():
                run=run_model_full(mid,ticks=5,seed=0)
                self.assertIsNone(run.observations[0][metric],mid)
                json.dumps(run.observations,allow_nan=False)
                self.assertIsNotNone(run.observations[-1][metric],mid)

    def test_symmetric_kirman_transition_has_no_directional_recruitment_bias(self):
        a,b=KirmanModel(),KirmanModel()
        a.initialize(None,{},None,None,np.random.default_rng(7));b.initialize(None,{},None,None,np.random.default_rng(7))
        a.opinions[:]=0;b.opinions[:]=1
        for i in range(50):
            a.step(i,1);b.step(i,1)
            np.testing.assert_array_equal(a.opinions,1-b.opinions)
        self.assertEqual(a.observe()['theory_mean'],.5)
        self.assertAlmostEqual(a.observe()['mean_share']+b.observe()['mean_share'],1.)

    def test_each_stock_market_trader_count_changes_real_demand(self):
        def price(**parameters):
            model=SantaFeLiteModel(**parameters)
            model.initialize(None,{},None,None,np.random.default_rng(7))
            for i in range(30):model.step(i,.1)
            return model.p
        baseline=price()
        for parameters in ({'n_f':90},{'n_t':90},{'n_n':0}):
            self.assertNotEqual(price(**parameters),baseline,parameters)


if __name__=='__main__':unittest.main(verbosity=2)
