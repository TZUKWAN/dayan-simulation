"""Presentation hints are validated data and survive a real generated-model execution."""
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.custom_models import validate_definition
from dayan.agent.model_tools import build_model, DSL_CONTRACT
from dayan.run_store import get_store, state_stream


def definition():
    return {'name':'主体场景合同验收','description':'有界空间中37个主体的能量分布；本地机制验收。',
            'kind':'agents','time_unit':'模型时间','parameters':{},'initial_state':{},'rates':{},
            'agents':{'count':37,'type':'agent','initial':{'x':'uniform(0,40)','y':'uniform(0,30)','energy':'uniform(0,1)'},
                      'update':{'x':'(x+dt)%40'},'color_by':'energy'},
            'space':{'width':40,'height':30,'unit':'模型单位'},'observables':{'energy_mean':'mean_energy'},
            'mechanisms':[],'assumptions':['周期空间'],'limitations':['非现实人口']}


class SceneContractTests(unittest.TestCase):
    def test_old_definition_remains_identical(self):
        old=definition();before=json.dumps(old,sort_keys=True)
        self.assertEqual(validate_definition(old),old)
        self.assertEqual(json.dumps(validate_definition(old),sort_keys=True),before)
        self.assertNotIn('visualization',old)

    def test_illegal_scene_hints_are_rejected(self):
        for visual in [{'glyph':'execute-js'},{'script':'alert(1)'},{'color_by':'not_computed'},
                       {'label':'x'*33},{'glyph':['person']},{'color_by':['energy']},
                       {'glyph':'person','action_by':'missing','action_poses':{'0':'idle'}},
                       {'glyph':'person','action_by':'energy','action_poses':{'0':'script'}},
                       {'glyph':'person','action_by':'energy','action_poses':{'00':'idle'}}]:
            with self.subTest(visual=visual):
                d=definition();d['visualization']=visual
                with self.assertRaises(ValueError):validate_definition(d)
        d={'name':'汇总','description':'常量存量','kind':'stocks','time_unit':'t','parameters':{},
           'initial_state':{'amount':1},'rates':{'amount':0},'observables':{'amount': 'amount'},
           'visualization':{'glyph':'person'}}
        with self.assertRaises(ValueError):validate_definition(d)

    def test_real_execution_and_archive_keep_visual_contract(self):
        d=definition()
        d["agents"]["initial"]["activity"]=0
        d["agents"]["update"]["activity"]="1 if t >= 0.15 else 0"
        d['visualization']={'glyph':'person','color_by':'energy','label':'能量',
                            'action_by':'activity','action_poses':{'0':'idle','1':'walk'}}
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DAYAN_DATA_DIR':tmp}):
            result=build_model(definition=d,ticks=4,dt=.1,seed=7)
            self.assertTrue(result['ok'],result)
            self.assertEqual(result['llm_calls'] if 'llm_calls' in result else result['payload']['llm_calls'],[])
            payload=result['payload'];record=get_store().load(payload['run_id']);stream=state_stream(record)
            self.assertEqual(stream['manifest']['model_definition']['visualization'],d['visualization'])
            self.assertEqual(stream['provenance'],'entity')
            self.assertEqual(len(stream['frames']),5)
            self.assertEqual(len(stream['frames'][0]['entities']),37)
            self.assertEqual(stream['frames'][0]['presentation']['visualization'],d['visualization'])
            self.assertEqual(stream['frames'][0]['entities'][0]['activity'],0)
            self.assertEqual(stream['frames'][-1]['entities'][0]['activity'],1)
            self.assertNotEqual(stream['frames'][0]['entities'][0]['x'],stream['frames'][-1]['entities'][0]['x'])
            self.assertIn('visualization={glyph:',DSL_CONTRACT)

    def test_new_model_multiple_seeds_are_actually_executed(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DAYAN_DATA_DIR':tmp}):
            result=build_model(definition=definition(),ticks=2,dt=.1,seeds=[7,8])
            self.assertTrue(result['ok'],result);p=result['payload']
            self.assertEqual(p['result_kind'],'ensemble');self.assertEqual(len(p['runs']),2)
            streams=[state_stream(get_store().load(r['run_id'])) for r in p['runs']]
            self.assertEqual([s['manifest']['rng']['seed'] for s in streams],[7,8])
            self.assertTrue(all(len(s['frames'])==3 and len(s['frames'][0]['entities'])==37 for s in streams))
            self.assertNotEqual(streams[0]['frames'][0]['entities'][0]['x'],streams[1]['frames'][0]['entities'][0]['x'])


if __name__=='__main__':unittest.main(verbosity=2)
