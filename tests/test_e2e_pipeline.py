"""Offline data -> actual model -> paired experiment -> calibration/archive checks.
Inputs are explicitly generated unit fixtures, never claimed as empirical evidence.
The live collection/research/report chain is in test_online_sources.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan import datasets
from dayan.runtime import run_model_full
from dayan.run_store import get_store
from dayan.research.specs import ExperimentSpec
from dayan.research.experiment import run_experiment
from dayan.research.quality import check_quality,check_role_leakage
from dayan.research.calibration import grid_search_calibrate,time_split

class OfflinePipeline(unittest.TestCase):
    def test_fixture_data_drives_model_paired_experiment_and_archive(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':td}):
            source=b'density\n0.2\n0.4\n'
            ds=datasets.ingest(source,name='synthetic density fixture',format='csv',source='unit-fixture; not empirical')
            binding={'dataset_id':ds['dataset_id'],'field':'density','aggregate':'mean','parameter':'density'}
            ref=run_model_full('NET106',parameters={'cells':100,'density':.3},ticks=12,dt=1,seed=7,capture_state=True)
            actual=run_model_full('NET106',parameters={'cells':100},data_bindings=[binding],ticks=12,dt=1,seed=7,capture_state=True)
            self.assertEqual(actual.observations,ref.observations)
            self.assertEqual(actual.manifest['data_bindings'][0]['sha256'],ds['sha256'])
            get_store().save_run(actual,'run','offline unit fixture')
            saved=get_store().load(actual.manifest['run_id'])
            self.assertEqual(saved['observations'],actual.observations)
            self.assertEqual(saved['state_frames'],actual.state_frames)
            spec=ExperimentSpec(model_id='NET106',ticks=12,dt=1,seeds=[7,8],primary_metric='flux',
                baseline_params={'cells':100},data_bindings=[binding],
                arms=[{'label':'slowdown','params':{'p':.8}}]).finalize()
            result=run_experiment(spec)
            self.assertTrue(result.ok,result.analysis)
            self.assertEqual(len(result.runs),4)
            for run in result.runs:
                self.assertAlmostEqual(run['manifest']['actual']['effective_parameters']['density'],.3,places=14)
    def test_actual_model_output_calibration_and_disjoint_holdout(self):
        ref=run_model_full('NET052',parameters={'beta':.4},ticks=8,dt=1,seed=7)
        rows=[{'date':int(r['sim_t']),'value':r['I'],'unit':'model_population'} for r in ref.observations]
        quality=check_quality(rows,variable_name='I',unit='model_population',frequency='model_step')
        self.assertEqual(quality['status'],'pass')
        train,hold=time_split(rows,holdout_years=2)
        leak=check_role_leakage(['fixture'],['fixture'],train,hold)
        self.assertTrue(leak['verified']);self.assertFalse(leak['has_leakage'])
        def predict(p,dates):
            run=run_model_full('NET052',parameters=p,ticks=int(max(dates)),dt=1,seed=7)
            by_time={int(r['sim_t']):r['I'] for r in run.observations}
            return [by_time[int(t)] for t in dates]
        fitted=grid_search_calibrate(model_fn=predict,param_grid={'beta':[.2,.4,.6]},
            observations=train,holdout_observations=hold,tolerance=1e-10)
        self.assertEqual(fitted['status'],'pass')
        self.assertEqual(fitted['best_params'],{'beta':.4})
        self.assertEqual(fitted['holdout']['dates'],[7.,8.])
        self.assertEqual(len(fitted['evaluations']),3)

if __name__=='__main__':unittest.main(verbosity=2)
