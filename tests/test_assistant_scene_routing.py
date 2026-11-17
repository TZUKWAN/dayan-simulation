"""Assistant orchestration checks use real models and archives, never generated mock replies."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.agent.agent import DayanAgent
from dayan.agent import intent
from dayan.agent.intent import plan_rule_based
from dayan.run_store import get_store
from dayan.runtime import run_model_full


class AssistantSceneRoutingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DAYAN_DATA_DIR':self.tmp.name,'DAYAN_API_KEY':''});self.env.start()
        self.planner=intent._LLM_PLANNER;intent.set_llm_planner(None)

    def tearDown(self):
        intent.set_llm_planner(self.planner);self.env.stop();self.tmp.cleanup()

    def test_concrete_scene_not_swallowed_by_first_mechanism(self):
        for text in ['37名行人在大厅向右侧出口疏散','模拟十字路口红绿灯下的车流','模拟医院挂号窗口排队']:
            p=plan_rule_based(text)
            self.assertEqual([a['tool'] for a in p['plan']],['build_model'],p)
            self.assertEqual(p['plan'][0]['args']['request'],text)
        p=plan_rule_based('运行NET106，运行2步，种子7')
        self.assertEqual(p['plan'][0]['args']['model_id'],'NET106')
        natural=plan_rule_based('模拟SIR疫情传播，运行3步')
        # The explicit SIR compartment contract selects SIR, never the first SIS family entry.
        self.assertEqual(natural['plan'][0]['args']['model_id'],'NET053')
        self.assertEqual(plan_rule_based('模拟疫情传播，运行3步')['plan'],[])

    def test_question_does_not_run_and_capabilities_use_true_context(self):
        p=plan_rule_based('为什么刚才的车流会停下来？',last_run={'model_id':'NET106'})
        self.assertEqual(p['plan'][0]['tool'],'explain')
        first=DayanAgent().fulfill('运行NET106，运行2步，种子7')
        rid=first['executed'][0]['payload']['run_id'];count=len(get_store().history())
        result=DayanAgent().fulfill('你能做什么',last_run={'run_id':rid,'model_id':'NET052','params':{'fake':99}})
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['executed'][0]['payload']['source_run_id'],rid)
        self.assertEqual(len(get_store().history()),count)

    def test_unrelated_ring_and_unsupported_3d_are_not_success(self):
        wrong=DayanAgent().fulfill('运行NET106模拟十字路口，运行2步')
        self.assertFalse(wrong['ok']);self.assertIn('环形',wrong['executed'][0]['error'])
        self.assertEqual(wrong['executed'][0]['payload']['scene_alignment']['status'],'mismatch')
        unsupported=DayanAgent().fulfill('模拟多层教学楼的三维物理烟气扩散与楼梯疏散')
        self.assertFalse(unsupported['ok']);self.assertEqual(unsupported['executed'],[])
        self.assertIn('尚未实现',''.join(unsupported['errors']))

    def test_native_pedestrian_exports_actual_room_and_exit(self):
        rr=run_model_full('NET113',parameters={'n':7},ticks=2,seed=7,capture_state=True)
        fr=rr.state_frames[0]
        self.assertEqual(fr['space']['bounds'],[0,0,12,12])
        room=next(f for f in fr['facilities'] if f['kind']=='room');gate=next(f for f in fr['facilities'] if f['kind']=='exit')
        self.assertEqual((room['width'],room['depth'],gate['x'],gate['y'],gate['width']),(12,12,6,12,3))
        get_store().save_run(rr,'run','原生场景验收')
        result=DayanAgent().fulfill('运行NET113，在房间向出口疏散，n=7，运行2步')
        self.assertTrue(result['ok'],result)
        self.assertEqual(result['executed'][0]['payload']['scene_alignment']['actual_entities'],7)

    def test_comparison_retains_requested_actor_count_on_both_models(self):
        result=DayanAgent().fulfill('比较NET113和NET114，n=7，运行2步，种子7')
        self.assertTrue(result['ok'],result)
        p=result['executed'][0]['payload']
        self.assertEqual(len(p['runs']),2)
        for run in p['runs']:
            saved=get_store().load(run['run_id'])
            self.assertEqual(len(saved['state_frames'][0]['entities']),7)

    def test_chinese_followup_changes_actual_parameter_and_preserves_scene(self):
        from test_scenario_alignment import scene_definition
        from dayan.agent.model_tools import build_model
        first=build_model(definition=scene_definition(),ticks=2,dt=1,seed=7)
        self.assertTrue(first['ok'],first);rid=first['payload']['run_id']
        changed=DayanAgent().fulfill('把速度改成1，运行2步',last_run={'run_id':rid,'model_id':'NET052','params':{'speed':99}})
        self.assertTrue(changed['ok'],changed)
        p=changed['executed'][0]['payload'];saved=get_store().load(p['run_id'])
        self.assertEqual(p['model_id'],first['payload']['model_id'])
        self.assertEqual(p['manifest']['actual']['effective_parameters']['speed'],1)
        self.assertEqual(len(saved['state_frames'][0]['entities']),37)
        self.assertEqual(saved['state_frames'][1]['parameters']['speed'],1)
        self.assertEqual(saved['state_frames'][0]['facilities'][1]['x'],38)
        half=plan_rule_based('沿用刚才模型，把速度减半',last_run={'model_id':p['model_id'],'params':{'speed':2,'n':37}})
        self.assertEqual(half['plan'][0]['args']['parameters']['speed'],1)
        unknown=DayanAgent().fulfill('沿用刚才，把不存在的字段改成10',last_run={'run_id':rid})
        self.assertFalse(unknown['ok']);self.assertEqual(unknown['executed'],[])
        partial=DayanAgent().fulfill('沿用刚才，把速度改成1，同时把不存在的字段改成10',last_run={'run_id':rid})
        self.assertFalse(partial['ok']);self.assertEqual(partial['executed'],[])
        event=plan_rule_based('沿用刚才，第1秒把速度改成1，运行2步',last_run={'run_id':rid,'model_id':p['model_id'],'params':{'speed':2,'n':37},'dt':1})
        self.assertEqual(event['requirements']['interventions'][0]['params']['speed'],1)

    def test_continue_uses_checkpoint_instead_of_restarting(self):
        original=DayanAgent().fulfill('运行NET106，运行5步，种子7')
        self.assertTrue(original['ok'],original);prior=original['executed'][0]['payload']
        continued=DayanAgent().fulfill('继续运行3步',last_run={'run_id':prior['run_id']})
        self.assertTrue(continued['ok'],continued);entry=continued['executed'][0]
        self.assertEqual(entry['tool'],'resume');p=entry['payload']
        self.assertEqual(p['manifest']['parent_run_id'],prior['run_id'])
        saved=get_store().load(p['run_id']);parent=get_store().load(prior['run_id'])
        self.assertEqual(saved['state_frames'][0]['entities'],parent['state_frames'][-1]['entities'])
        self.assertAlmostEqual(saved['state_frames'][0]['sim_t'],.5)
        self.assertAlmostEqual(saved['state_frames'][-1]['sim_t'],.8)
        reference=run_model_full('NET106',ticks=8,seed=7,capture_state=True)
        self.assertEqual(saved['state_frames'][-1]['entities'],reference.state_frames[-1]['entities'])
        unsupported=DayanAgent().fulfill('继续运行3步，把p改成0.5',last_run={'run_id':prior['run_id']})
        self.assertFalse(unsupported['ok']);self.assertEqual(unsupported['executed'],[])

    def test_model_search_uses_actual_implementation_names(self):
        from dayan.agent.metadata import search_capabilities
        matches=search_capabilities('SIR 疫情传播 仓室 S I R')
        ids=[c['model_id'] for c in matches]
        self.assertIn('NET053',ids)
        exact=next(c for c in matches if c['model_id']=='NET053')
        self.assertEqual(exact['implementation_name'],'SIRModel')
        self.assertIn('SIR',exact['name']);self.assertNotIn('observable_samples',exact)
        self.assertTrue(search_capabilities('搜索SIR'))
        from dayan.agent.tools import tool_search_models
        multiple=tool_search_models('SIR',has_param='beta,gamma',observable=['S','I','R'])['payload']
        self.assertIn('NET053',[c['model_id'] for c in multiple['matches']])
        mistaken=tool_search_models('SIR',has_param='S,I,R')['payload']
        self.assertEqual(mistaken['count'],0)
        self.assertIn('NET053',[c['model_id'] for c in mistaken['candidates']])
        diagnostic=next(c for c in mistaken['filter_diagnostics'] if c['model_id']=='NET053')
        self.assertEqual(diagnostic['missing_parameters'],['I','R','S'])


if __name__=='__main__':unittest.main(verbosity=2)
