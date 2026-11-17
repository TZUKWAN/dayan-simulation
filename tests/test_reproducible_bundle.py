"""Execute archived code in a child interpreter and compare actual trajectories."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.runtime import run_model_full
from dayan.run_store import get_store
from dayan.replay import replay,extract_checked
from dayan import datasets


class ReproducibleBundle(unittest.TestCase):
    def test_complete_source_environment_input_and_real_archived_execution(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':td}):
            ds=datasets.ingest(b'density\n20\n40\n',name='synthetic unit fixture',format='csv',source='unit fixture',
                metadata={'unit':'%','scope':'unit ring lane'})
            binding={'dataset_id':ds['dataset_id'],'field':'density','parameter':'density','aggregate':'mean','scale':.01,
                'source_unit':'%','target_unit':'fraction','source_scope':'unit ring lane','target_scope':'unit ring lane'}
            run=run_model_full('NET106',parameters={'cells':40},data_bindings=[binding],ticks=8,dt=1,seed=7,capture_state=True)
            store=get_store();rid=store.save_run(run);bundle=store.prepare_bundle(rid)
            saved=store.load(rid)
            self.assertIn('numpy',saved['manifest']['environment']['packages'])
            self.assertEqual(saved['manifest']['data_bindings'][0]['compatibility_status'],'units_verified')
            with zipfile.ZipFile(store.directory/'code_versions'/(saved['manifest']['code_version']+'.zip')) as z:
                names=z.namelist()
                self.assertTrue({'SOURCE_MANIFEST.json','src/kernel/registry.py','experiments/run_mvp.py',
                    'requirements.txt','dayan/config.example.json','site/console/viz3d.js','data/model_semantics.json'}<=set(names))
                self.assertNotIn('dayan/config.json',names)
            result=replay(bundle,Path(td)/'actual_offline_replay',execute=True)
            self.assertEqual(len(result['executed']),1)
            self.assertTrue(result['executed'][0]['observations_equal'])
            self.assertTrue(result['executed'][0]['state_frames_equal'])

    def test_intervention_replays_and_changed_source_is_never_mislabeled(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':td}):
            run=run_model_full('NET052',parameters={'beta':.4},ticks=10,dt=.1,seed=8,
                interventions=[{'at_t':.5,'params':{'beta':'*0.5'}}],capture_state=True)
            store=get_store();rid=store.save_run(run)
            self.assertTrue(replay(store.prepare_bundle(rid),Path(td)/'intervention_replay',True)['executed'][0]['observations_equal'])
            with patch('dayan.runtime.source_fingerprint',return_value='unit deliberately changed source'):
                with self.assertRaisesRegex(ValueError,'源码'):run_model_full('NET052',ticks=1,seed=7)
            run.manifest['source_fingerprint']='unit mismatch'
            with self.assertRaisesRegex(ValueError,'不一致'):store.save_run(run)

    def test_wrong_units_scope_and_archive_paths_are_rejected(self):
        with tempfile.TemporaryDirectory() as td,patch.dict(os.environ,{'DAYAN_DATA_DIR':td}):
            ds=datasets.ingest(b'density\n30\n',name='unit',format='csv',source='unit fixture',metadata={'unit':'%','scope':'A'})
            base={'dataset_id':ds['dataset_id'],'field':'density','parameter':'density','source_unit':'%','target_unit':'fraction'}
            with self.assertRaisesRegex(ValueError,'单位'):datasets.bind_parameters([base],'NET106')
            with self.assertRaisesRegex(ValueError,'范围'):
                datasets.bind_parameters([{**base,'scale':.01,'source_scope':'A','target_scope':'B'}],'NET106')
            with self.assertRaisesRegex(ValueError,'范围'):
                datasets.bind_parameters([{**base,'scale':.01,'source_scope':'B','target_scope':'B'}],'NET106')
            path=Path(td)/'unit-malicious.zip'
            with zipfile.ZipFile(path,'w') as z:z.writestr('../escape.txt','deliberately unsafe unit fixture')
            with self.assertRaisesRegex(ValueError,'路径'):extract_checked(path,Path(td)/'extract')


if __name__=='__main__':unittest.main(verbosity=2)
