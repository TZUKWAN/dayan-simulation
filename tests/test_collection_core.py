"""Offline collection state machine; synthetic transport pages are labelled fixtures.
Real public-source availability is checked separately by test_online_sources.
"""
import hashlib
import importlib
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))

class CollectionCore(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DAYAN_DATA_DIR':self.temp.name});self.env.start()
        from dayan.collection import engine,registry,connectors
        self.engine,self.registry,self.connectors=engine,registry,connectors
        importlib.reload(engine);importlib.reload(registry)
        self.old=dict(connectors.CONNECTORS);self.old_source=dict(connectors.CONNECTOR_SOURCE)
    def tearDown(self):
        self.connectors.CONNECTORS.clear();self.connectors.CONNECTORS.update(self.old)
        self.connectors.CONNECTOR_SOURCE.clear();self.connectors.CONNECTOR_SOURCE.update(self.old_source)
        self.env.stop();importlib.reload(self.engine);importlib.reload(self.registry);self.temp.cleanup()
    def test_fresh_matrix_presets_and_no_phantom_live_evidence(self):
        from dayan.collection import presets
        from dayan.agent.data_tools import search_sources
        rows=self.registry.matrix()
        self.assertGreaterEqual(len(rows),30)
        self.assertEqual({r['cat'] for r in rows},set(self.registry.CATS))
        self.assertTrue(all(r['state']=='candidate' for r in rows))
        self.assertEqual(self.engine.list_tasks(),[])
        with self.assertRaises(ValueError):self.registry.set_state('__test__','super_live')
        self.assertGreaterEqual(len(presets.list_presets()),6)
        pr=presets.get_preset('pop_employment_wb')
        with self.assertRaises(ValueError):presets.resolve_params(pr,{})
        params=presets.resolve_params(pr,{'indicator':'SP.POP.TOTL','country':'中国','year_from':2019,'year_to':2024})
        self.assertEqual(params['country'],'CHN')
        self.assertGreaterEqual(search_sources('就业')['payload']['n_sources'],3)
    def test_partial_resume_hashes_idempotency_and_no_recollection_claim(self):
        calls=[]
        def fixture(params,budget):
            start=(params.get('_cursor') or {}).get('page',0)
            for i in range(start,min(start+budget,2)):
                calls.append(i);raw=json.dumps({'fixture':True,'page':i}).encode()
                yield self.connectors.Page('fixture://unit/'+str(i),raw,[{'value':i,'fixture':True}],
                     {'has_more':i<1,'cursor':{'page':i+1},'fixture':True})
        self.connectors.CONNECTORS['unit_fixture']=fixture
        self.connectors.CONNECTOR_SOURCE['unit_fixture']='wb_indicators'
        first=self.engine.run_collection('unit_fixture',{},page_budget=1,purpose='unit-fixture')
        self.assertEqual(first['status'],'partial');self.assertEqual(first['n_records'],1)
        final=self.engine.run_collection('unit_fixture',{},page_budget=1,collection_id=first['collection_id'])
        self.assertEqual(final['status'],'done');self.assertEqual(calls,[0,1])
        self.assertIsNone(final.get('incomplete_reason'))
        self.assertIn('预算',first['incomplete_reason'])
        same=self.engine.run_collection('unit_fixture',{},collection_id=first['collection_id'])
        self.assertTrue(same['reused']);self.assertEqual(calls,[0,1])
        for page in final['pages']:
            self.assertEqual(hashlib.sha256((self.engine.BASE/page['raw']).read_bytes()).hexdigest(),page['sha256'])
        self.assertEqual(len(self.engine.records_preview(final['collection_id'],10)),2)
        with self.assertRaises(ValueError):self.engine.run_collection('unit_fixture',{'changed':1},collection_id=first['collection_id'])

if __name__=='__main__':unittest.main(verbosity=2)
