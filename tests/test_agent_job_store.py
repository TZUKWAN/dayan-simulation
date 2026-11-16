"""Durable job state with real archived results and bounded recovery envelopes."""
import os
from pathlib import Path
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.agent import intent,job_store
from dayan.agent.agent import DayanAgent
from dayan.run_store import get_store,_bytes


class AgentJobStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.env=patch.dict(os.environ,{'DAYAN_DATA_DIR':self.tmp.name});self.env.start()
        self.planner=intent._LLM_PLANNER;intent.set_llm_planner(None)

    def tearDown(self):
        intent.set_llm_planner(self.planner);self.env.stop();self.tmp.cleanup()

    def test_completed_real_result_survives_new_reader(self):
        text='运行NET106，运行2步，种子7';result=DayanAgent().fulfill(text);self.assertTrue(result['ok'],result)
        jid=uuid.uuid4().hex;job_store.save_job(jid,{'status':'done','stages':['实际模型已归档'],'result':result},text)
        recovered=job_store.load_job(jid)
        self.assertEqual(recovered['status'],'done');self.assertEqual(recovered['request_text'],text)
        rid=recovered['result']['executed'][0]['payload']['run_id'];self.assertEqual(len(get_store().load(rid)['state_frames']),3)

    def test_interrupted_job_is_never_reported_as_success(self):
        jid=uuid.uuid4().hex;job_store.save_job(jid,{'status':'running','stages':['生成中'],'result':None},'待处理的请求')
        recovered=job_store.load_job(jid)
        self.assertEqual(recovered['status'],'error');self.assertIsNone(recovered['result']);self.assertIn('中断',recovered['error'])
        with self.assertRaises(ValueError):job_store.load_job('../outside')

    def test_large_real_payload_recovers_by_canonical_artifact(self):
        text='运行NET106，运行2步';result=DayanAgent().fulfill(text);self.assertTrue(result['ok'],result)
        jid=uuid.uuid4().hex;job={'status':'done','stages':[],'result':result}
        # Exercise the size boundary with an actual result, by lowering the test-only limit.
        with patch.object(job_store,'LIMIT',len(_bytes(job))-1):
            job_store.save_job(jid,job,text);recovered=job_store.load_job(jid)
        payload=recovered['result']['executed'][0]['payload']
        self.assertTrue(payload['archive_only']);self.assertNotIn('observations',payload)
        self.assertEqual(len(get_store().load(payload['run_id'])['observations']),3)


if __name__=='__main__':unittest.main(verbosity=2)
