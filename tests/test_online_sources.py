"""Opt-in REAL World Bank collection -> study -> actual run -> report.

Unavailable services are reported as skipped with their actual error, never green
empirical validation. A failed holdout is a valid pipeline result and stays failed.
"""
import hashlib
import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


@unittest.skipUnless(os.environ.get('DAYAN_TEST_ONLINE')=='1','真实公开数据源未显式启用，未执行')
class OnlineResearch(unittest.TestCase):
    def test_worldbank_research_chain_and_exact_source_hash(self):
        from dayan.collection import engine
        from dayan.research import studies
        from dayan.research.study_reports import generate_report
        from dayan.run_store import get_store
        question='德国2010:2015失业率线性趋势，留出2年，阈值1，参数initial=7.043，slope=-0.75'
        task=engine.run_collection('worldbank',{'country':'DEU','indicator':'SL.UEM.TOTL.ZS',
            'date':'2010:2015','per_page':100},page_budget=1,name='Actual public source acceptance')
        if task['status']!='done' or not task.get('n_records'):
            self.skipTest('真实World Bank不可用：'+str(task.get('error') or task['status']))
        for page in task['pages']:
            self.assertEqual(hashlib.sha256((engine.BASE/page['raw']).read_bytes()).hexdigest(),page['sha256'])
        prepared=studies.create_study(question,task['collection_id'],'linear',{'initial':[7.043],'slope':[-.75]},1,2,5)
        fitted=studies.calibrate_study(prepared['study_id'])
        self.assertTrue(fitted['run_id'])
        saved=get_store().load(fitted['run_id'])
        self.assertTrue(saved['observations'])
        self.assertEqual(saved['manifest']['data_bindings'][0]['dataset_id'],prepared['training_dataset']['dataset_id'])
        report=generate_report(fitted['study_id'],'academic')
        self.assertTrue(any(name.endswith('.facts.json') for name in report['files']))
        self.assertEqual(report['validation_status'],fitted['calibration']['status'])
        self.assertTrue(report['bundle_url'])


if __name__=='__main__':unittest.main(verbosity=2)
