"""User clauses -> executable behavior -> exported facilities, without mock LLM results."""
import copy
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.custom_models import register,validate_definition
from dayan.scene_contract import validate_scene,scene_requirements
from dayan.runtime import run_model_full

REQUEST='37名行人在40×30米的大厅里向右侧出口移动，出口坐标(38,15)，到达后停下，颜色标记是否到达。'


def scene_definition():
    params={name:{'default':value,'type':'int' if name=='n' else 'float','mutable':name=='exit_x'}
            for name,value in {'n':37,'width':40,'depth':30,'exit_x':38,'exit_y':15,'speed':2}.items()}
    distance='sqrt((exit_x-x)**2+(exit_y-y)**2)'
    return {'name':'大厅出口移动模型','description':'按目标方向移动并在出口停下；假设空间，非校准疏散预测。',
            'kind':'agents','time_unit':'s','parameters':params,'initial_state':{},'rates':{},
            'agents':{'count':'n','type':'pedestrian','color_by':'arrived',
                      'initial':{'x':'uniform(1,10)','y':'uniform(1,depth-1)','arrived':0},
                      'update':{'x':f'clip(x+speed*dt*(exit_x-x)/max({distance},speed*dt),0,width)',
                                'y':f'clip(y+speed*dt*(exit_y-y)/max({distance},speed*dt),0,depth)',
                                'arrived':f'1 if {distance}<=speed*dt else 0'}},
            'space':{'width':'width','height':'depth','unit':'m'},
            'observables':{'arrived':'sum_arrived','moving':'n_agents-sum_arrived'},
            'visualization':{'glyph':'person','color_by':'arrived','label':'是否到达'},
            'scenario':{'title':'大厅右侧出口','setting':'40×30米假设大厅；不含拥挤与碰撞机制',
                        'agent_label':'行人','source_request':REQUEST,
                        'facilities':[{'id':'hall','kind':'room','label':'大厅边界','x':'width/2','y':'depth/2',
                                       'width':'width','depth':'depth','role':'context'},
                                      {'id':'gate','kind':'exit','label':'右侧出口','x':'exit_x','y':'exit_y',
                                       'width':1,'depth':3,'role':'modeled','behavior_parameters':['exit_x','exit_y']}],
                        'requirements':[{'quote':'37名行人','model_refs':['agents.count','parameters.n'],'visual_refs':['agents.count']},
                                        {'quote':'40×30米的大厅','model_refs':['space'],'visual_refs':['scenario.facilities.hall']},
                                        {'quote':'右侧出口','model_refs':['agents.update.x','agents.update.y'],'visual_refs':['scenario.facilities.gate']},
                                        {'quote':'到达后停下','model_refs':['agents.update.x','agents.update.arrived'],'visual_refs':['agents.update.arrived']},
                                        {'quote':'颜色标记是否到达','model_refs':['agents.update.arrived'],'visual_refs':['visualization.color_by']}]},
            'mechanisms':[],'assumptions':['目标驱动，无碰撞'],'limitations':['不预测真实疏散容量']}


class ScenarioAlignmentTests(unittest.TestCase):
    def test_real_behavior_and_dynamic_facilities_share_parameters(self):
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'DAYAN_DATA_DIR':tmp}):
            d=scene_definition();validate_scene(d,REQUEST);registered=register(d,REQUEST)
            result=run_model_full(registered['model_id'],ticks=40,dt=1,seed=7,capture_state=True)
            self.assertEqual(len(result.state_frames[0]['entities']),37)
            self.assertEqual(result.observations[-1]['arrived'],37)
            for e in result.state_frames[-1]['entities']:
                self.assertAlmostEqual(e['x'],38);self.assertAlmostEqual(e['y'],15)
            self.assertEqual([(f['kind'],f['x'],f['y']) for f in result.state_frames[-1]['facilities']],
                             [('room',20,15),('exit',38,15)])
            moved=run_model_full(registered['model_id'],ticks=40,dt=1,seed=7,capture_state=True,
                                 interventions=[{'at_t':5,'params':{'exit_x':30}}])
            self.assertEqual(moved.state_frames[-1]['facilities'][1]['x'],30)
            self.assertAlmostEqual(moved.state_frames[-1]['entities'][0]['x'],30)

    def test_fabricated_coverage_and_decorative_behavior_are_rejected(self):
        for change in ['quote','ref','unused_binding','fake_obstacle','missing_exit','code']:
            with self.subTest(change=change):
                d=scene_definition()
                if change=='quote':d['scenario']['requirements'][0]['quote']='用户没说的场景'
                if change=='ref':d['scenario']['requirements'][0]['model_refs']=['agents.update.fake']
                if change=='unused_binding':d['scenario']['facilities'][1]['behavior_parameters']=['n']
                if change=='fake_obstacle':d['scenario']['facilities'][0]['kind']='obstacle'
                if change=='missing_exit':d['scenario']['facilities'][1]['kind']='zone'
                if change=='code':d['scenario']['facilities'][1]['x']='__import__("os")'
                with self.assertRaises(ValueError):
                    validate_definition(d);validate_scene(d,REQUEST)

    def test_specific_scene_needs_contract_and_unsupported_capabilities_are_explicit(self):
        d=scene_definition();d.pop('scenario')
        with self.assertRaises(ValueError):validate_scene(d,REQUEST)
        d=scene_definition()
        with self.assertRaises(ValueError):validate_scene(d,'另一个用户需求')
        needs=scene_requirements('三维物理的多层教学楼中烟气扩散，所有人通过楼梯疏散')
        self.assertIn('building',needs['features']);self.assertEqual(len(needs['unsupported']),2)
        self.assertNotIn('obstacle',scene_requirements('不用障碍物，只有大厅和出口')['features'])


if __name__=='__main__':unittest.main(verbosity=2)
