"""Selected-window reports are recomputed from actual immutable simulations."""
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
OUT=ROOT/'.claude/ui_implementation_20261113/report_tests'
os.environ['DAYAN_REPORTS_DIR']=str(OUT)
from api_client import local_client as TestClient
from docx import Document
from dayan.server import app


class WorkspaceReportTests(unittest.TestCase):
    def test_paired_archive_view_and_rejected_client_overrides(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DAYAN_DATA_DIR':tmp}):
            client=TestClient(app)
            experiment=client.post('/api/experiments',json={'model_id':'NET106','ticks':60,'dt':.1,
                'seeds':[7,13],'rng_domain':'exp0','primary_metric':'flux','baseline_params':{'density':.3,'p':.2},
                'arms':[{'label':'干预组','params':{},'interventions':[{'at_t':2,'params':{'p':.95},'label':'提高慢化概率'}]}]}).json()
            chosen=next(r for r in experiment['runs'] if r['arm']=='干预组' and r['seed']==7)
            request={'model_id':'NET106','run_id':chosen['run_id'],'experiment_id':experiment['experiment_id'],
                     'primary_metric':'flux','analysis_window':{'mode':'post','from':-999,'to':999,'exclusive':False},
                     'sim_t':6,'entity_id':'car_0','entity_metric':'x','distribution_field':'speed','intent':'比较慢化概率提高后的交通通量',
                     'observations':[{'sim_t':0,'fake_metric':99999}],
                     'analysis':{'metric':'fake_metric','baseline':{'mean':99999}},'manifest':{'actual':{'n_steps':99999}}}
            response=client.post('/api/report',json=request)
            self.assertEqual(response.status_code,200,response.text)
            report=response.json();facts=json.loads(Path(report['path']).with_suffix('.json').read_text(encoding='utf-8'))
            view=facts['view_analysis']
            self.assertEqual(view['window'],{'mode':'post','from':2.0,'to':6.0,'exclusive':True})
            self.assertEqual(view['selected_run_id'],chosen['run_id'])
            self.assertEqual(view['frame_time'],6)
            self.assertEqual(view['entity_metric'],'x')
            self.assertEqual(len(view['run_ids']),4)
            expected=[]
            means_by_arm={}
            for group in ['基线','干预组']:
                per_seed=[]
                for rows in experiment['observations_by_arm'][group]:
                    values=[o['flux'] for o in rows if o['sim_t']>2]
                    self.assertEqual(len(values),40)
                    per_seed.append(sum(values)/len(values))
                means_by_arm[group]=per_seed
                expected.append(sum(per_seed)/len(per_seed))
            for actual,wanted in zip(view['groups'],expected):self.assertAlmostEqual(actual['mean'],wanted,places=12)
            self.assertEqual(view['comparisons'][0]['paired_n'],2)
            self.assertAlmostEqual(view['comparisons'][0]['relative'],(expected[1]-expected[0])/expected[0],places=12)
            document=Document(report['path']);text='\n'.join(p.text for p in document.paragraphs)
            self.assertNotIn('fake_metric',text);self.assertNotIn('99999',text)
            self.assertEqual(len(document.inline_shapes),report['figure_count'])
            figures={figure['kind']:figure for figure in view['figures']}
            self.assertEqual(set(figures),{'comparison_time_series','window_comparison','paired_effects',
                'entity_distribution','road_space_time','selected_entity_trace'})
            for field in ('n_cars','density'):
                metric=facts['research_evidence']['metrics'][field]
                self.assertEqual(metric['minimum'],metric['maximum'])
            self.assertTrue(all(figure['evidence']['window']==view['window'] for figure in figures.values()))
            paired=figures['paired_effects']['evidence']['pairs'][0]
            deltas=[arm-base for base,arm in zip(means_by_arm['基线'],means_by_arm['干预组'])]
            self.assertEqual(paired['n'],len(deltas))
            self.assertAlmostEqual(paired['minimum'],min(deltas),places=12)
            self.assertAlmostEqual(paired['maximum'],max(deltas),places=12)
            self.assertAlmostEqual(paired['mean'],sum(deltas)/len(deltas),places=12)
            self.assertTrue(all(Path(f['path']).is_file() for f in view['figures']))
            OUT.mkdir(parents=True,exist_ok=True)
            (OUT/'verification.json').write_text(json.dumps({'report':report,'means':expected,'figure_kinds':[f['kind'] for f in view['figures']],'selected_run_id':chosen['run_id']},ensure_ascii=False,indent=2),encoding='utf-8')
            for changes in [{'analysis_window':{'mode':'custom','from':6.5,'to':7}}, {'entity_id':'does_not_exist'}, {'primary_metric':'fake_metric'}]:
                bad=client.post('/api/report',json={**request,**changes});self.assertEqual(bad.status_code,400,bad.text)

    def test_unarchived_input_cannot_claim_a_research_report(self):
        response=TestClient(app).post('/api/report',json={'model_id':'NET106','observations':[{'sim_t':0,'flux':123}]})
        self.assertEqual(response.status_code,400)


if __name__=='__main__':unittest.main(verbosity=2)
