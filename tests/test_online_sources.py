"""Opt-in REAL World Bank collection -> study -> actual run -> report.

Unavailable services are reported as skipped with their actual error, never green
empirical validation. A failed holdout is a valid pipeline result and stays failed.
"""
import hashlib
import os
import sys
import unittest
from pathlib import Path
from urllib.error import HTTPError, URLError
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(os.environ.get('DAYAN_TEST_ONLINE')=='1','真实公开数据源未显式启用，未执行')
class OnlineResearch(unittest.TestCase):
    def test_worldbank_research_chain_and_exact_source_hash(self):
        from dayan.collection import engine
        from dayan.research import studies
        from dayan.research.study_reports import generate_report
        from dayan.run_store import get_store
        question='德国2010:2015失业率线性趋势，末尾2年留出，事前RMSE阈值1，slope=[-0.75,-0.5,0]，初值取首年真实观测'
        task=engine.run_collection('worldbank_data360',{'country':'DEU','indicator':'SL.UEM.TOTL.ZS',
            'date':'2010:2015'},page_budget=1,name='Actual public source acceptance')
        if task['status']!='done' or not task.get('n_records'):
            error=str(task.get('error') or task['status'])
            if error.startswith(('URLError:','TimeoutError:','ConnectionError:')):
                self.skipTest('真实World Bank网络不可用：'+error)
            self.fail('真实采集失败（程序/协议错误不能当作未执行）：'+error)
        for page in task['pages']:
            self.assertEqual(hashlib.sha256((engine.BASE/page['raw']).read_bytes()).hexdigest(),page['sha256'])
        prepared=studies.create_study(question,task['collection_id'],'linear',{'slope':[-.75,-.5,0]},1,2,5)
        fitted=studies.calibrate_study(prepared['study_id'])
        self.assertTrue(fitted['run_id'])
        saved=get_store().load(fitted['run_id'])
        self.assertTrue(saved['observations'])
        self.assertEqual(saved['manifest']['data_bindings'][0]['dataset_id'],prepared['training_dataset']['dataset_id'])
        report=generate_report(fitted['study_id'],'academic')
        self.assertTrue(any(name.endswith('.facts.json') for name in report['files']))
        self.assertEqual(report['validation_status'],fitted['calibration']['status'])
        self.assertTrue(report['bundle_url'])

    def test_tigerweb_snapshots_are_used_as_model_inputs(self):
        from dayan.collection.spatial import collect_census_scene
        from dayan.datasets import load
        from dayan.runtime import run_model_full
        try:
            scene=collect_census_scene([-80.063,40.490,-80.052,40.497],['local'])
        except ValueError as error:
            cause=error.__cause__
            if isinstance(cause,(URLError,TimeoutError)) and (not isinstance(cause,HTTPError) or cause.code in (429,502,503,504)):
                self.skipTest('真实 TIGERweb 请求不可用：'+str(error))
            raise
        roads,population=scene['roads'],scene['population']
        self.assertGreater(roads['n_records'],0)
        self.assertGreater(population['metadata']['population'],0)
        for dataset in (roads,population):
            for parent in dataset['metadata']['derived_from']:
                self.assertEqual(load(parent['dataset_id'])['sha256'],parent['sha256'])
        run=run_model_full('CPL001',{'roads_dataset_id':roads['dataset_id'],
            'population_dataset_id':population['dataset_id'],'n':120,'bus_capacity':80},
            ticks=4,dt=.25,seed=7,strict=True)
        self.assertEqual(run.observations[0]['represented_population'],population['metadata']['population'])
        self.assertEqual({item['sha256'] for item in run.manifest['data_bindings']},{roads['sha256'],population['sha256']})


if __name__=='__main__':unittest.main(verbosity=2)
