"""Explicit protocol fixtures, not live LLM or scientific validation."""
import json,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_scenario_alignment import scene_definition,REQUEST
from dayan.scene_contract import review_definition

class SceneReviewProtocol(unittest.TestCase):
 def test_bad_reference_is_repaired_on_the_same_actual_definition(self):
  bad={'matched':True,'missing':[],'checks':[{'quote':'37名行人','refs':['type']}]}
  good={'matched':True,'missing':[],'checks':[{'quote':'37名行人','refs':['agents.count','parameters.n.default']}]}
  with patch('dayan.llm_client.complete',side_effect=[json.dumps(bad),json.dumps(good)]) as complete:
   result=review_definition(REQUEST,scene_definition(),[])
   self.assertTrue(result['matched']);self.assertEqual(complete.call_count,2)
   sent=json.loads(complete.call_args_list[0].args[0][1]['content'])
   self.assertIn('agents.count',sent['available_refs']);self.assertNotIn('type',sent['available_refs'])
   self.assertEqual(sent['definition'],scene_definition())
 def test_well_formed_semantic_rejection_is_never_retried_into_approval(self):
  rejected={'matched':False,'missing':['actual requested behavior missing'],'checks':[{'quote':'到达后停下','refs':['agents.update']}]}
  with patch('dayan.llm_client.complete',return_value=json.dumps(rejected)) as complete:
   with self.assertRaisesRegex(ValueError,'actual requested behavior missing'):review_definition(REQUEST,scene_definition(),[])
   self.assertEqual(complete.call_count,1)
 def test_repeated_fabricated_references_fail_closed(self):
  invalid={'matched':True,'missing':[],'checks':[{'quote':'37名行人','refs':['description']}]}
  with patch('dayan.llm_client.complete',return_value=json.dumps(invalid)) as complete:
   with self.assertRaisesRegex(ValueError,'真实可用路径'):review_definition(REQUEST,scene_definition(),[])
   self.assertEqual(complete.call_count,2)

 def test_review_can_cite_explicit_absence_of_bound_inputs(self):
  phrase='使用内生设定。'
  reply={'matched':True,'missing':[],'checks':[{'quote':phrase,'refs':['execution.data_bindings']}]}
  with patch('dayan.llm_client.complete',return_value=json.dumps(reply)) as complete:
   result=review_definition(phrase,{'kind':'stocks'},[],{'data_bindings':[]})
   self.assertTrue(result['matched']);self.assertEqual(complete.call_count,1)

 def test_grid_review_can_reference_actual_implicit_runtime_behaviour(self):
  from test_custom_grid import definition
  from dayan.custom_models import validate_definition
  model=validate_definition(definition())
  phrase="保留周期边界，并能回放逐格状态"
  reply={"matched":True,"missing":[],"checks":[{"quote":phrase,
         "refs":["runtime_contract.grid.boundary","runtime_contract.state_frames"]}]}
  with patch('dayan.llm_client.complete',return_value=json.dumps(reply)) as complete:
   review_definition(phrase,model,[])
   sent=json.loads(complete.call_args.args[0][1]["content"])
   self.assertIn("矩形周期边界",sent["runtime_contract"]["grid"]["boundary"])
   self.assertIn("runtime_contract.grid.history",sent["available_refs"])
   self.assertEqual(sent["definition"],model)
   self.assertEqual(sent["request"],phrase)

 def test_semantic_reviewer_receives_real_full_frame_and_bundle_contract(self):
  from test_custom_grid import definition
  from dayan.custom_models import validate_definition
  from dayan.scaling import scale_intent
  phrase='保留初态和每一步全部92人及当前关系，并交付完整运行包。'
  verdict={'matched':True,'missing':[],'checks':[{'quote':phrase,'refs':[
   'runtime_contract.frame_archive.all_steps_required','runtime_contract.frame_archive.include_initial',
   'runtime_contract.frame_archive.verification','execution.delivery.bundle_url']} ]}
  execution={'scale_requested':scale_intent(phrase),'delivery':{'bundle_url':'/api/runs/{accepted_run_id}/bundle.zip'}}
  with patch('dayan.llm_client.complete',return_value=json.dumps(verdict)) as complete:
   result=review_definition(phrase,validate_definition(definition()),[],execution)
  self.assertTrue(result['matched'])
  sent=json.loads(complete.call_args.args[0][1]['content'])
  policy=sent['runtime_contract']['frame_archive']
  self.assertTrue(policy['include_initial'] and policy['include_final'] and policy['all_steps_required'])
  self.assertIn('运行完成后核验',policy['evidence_phase'])

def test_review_contract_distinguishes_parameter_bindings_from_structured_input_ports():
 from dayan.custom_models import validate_definition
 from test_program_runtime import definition
 phrase='把已准备的参数输入用于连续状态方程。'
 binding={'dataset_id':'DS-controlled-protocol','field':'rate','parameter':'rate','aggregate':'mean',
          'sha256':'controlled protocol source, not a live empirical dataset'}
 execution={'effective_inputs':{'rate':.7},'data_bindings':[binding]}
 verdict={'matched':True,'missing':[],'limitations':['Controlled reviewer fixture only'],
          'checks':[{'quote':phrase,'refs':['runtime_contract.input_pipeline.prepared_parameters','source.advance']}]}
 with patch('dayan.llm_client.complete',return_value=json.dumps(verdict)) as complete:
  review_definition(phrase,validate_definition(definition()),[],execution)
 sent=json.loads(complete.call_args.args[0][1]['content'])
 pipeline=sent['runtime_contract']['input_pipeline']
 assert pipeline['prepared_ports']==[]
 actual,=pipeline['prepared_parameters']
 assert actual['parameter']=='rate' and actual['effective_value']==.7 and actual['channel']=='parameters'
 assert actual['dataset_id']==binding['dataset_id'] and 'inputs可以为空' in pipeline['solver_access']


def test_omitted_or_unavailable_geometry_is_not_required_and_positive_clauses_survive():
 from dayan.scene_contract import scene_requirements
 text='读取办公室匿名接触数据。不虚构这个匿名数据没有提供的房间坐标或人物运动。'
 assert scene_requirements(text)=={'features':[],'spatial':False,'unsupported':[]}
 actual=scene_requirements('不虚构没有提供的房间坐标，但是要模拟真实路口和信号灯。')
 assert set(actual['features'])=={'road','signal'} and actual['spatial']
 assert set(scene_requirements('不要省略房间和出口')['features'])=={'room','exit'}
 assert scene_requirements('不需要多层建筑与三维物理；保留接触网络。')['unsupported']==[]


def test_unprovided_source_geometry_does_not_force_an_invented_spatial_model():
 from dayan.scene_contract import scene_requirements,validate_scene
 from dayan.program_scene import validate_scene as validate_program_scene
 phrase='人口统计没有提供个体位置、地形或行为，不虚构人物动画。'
 assert scene_requirements(phrase)=={'features':[],'spatial':False,'unsupported':[]}
 validate_scene({'kind':'stocks'},phrase)
 validate_program_scene({'kind':'program'},phrase)
 for text in ('数据未提供地形但要构建真实房间和出口。',
              '数据没有给出房间布局不过需要模拟真实路口和信号灯。'):
  actual=scene_requirements(text)
  assert actual['spatial']
 assert set(scene_requirements('数据未提供地形但要构建真实房间和出口。')['features'])=={'room','exit'}
 assert set(scene_requirements('数据没有给出房间布局不过需要模拟真实路口和信号灯。')['features'])=={'road','signal'}


if __name__=='__main__':unittest.main(verbosity=2)
