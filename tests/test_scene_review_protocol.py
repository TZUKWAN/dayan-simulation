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

if __name__=='__main__':unittest.main(verbosity=2)
