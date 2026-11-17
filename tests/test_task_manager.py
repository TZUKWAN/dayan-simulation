"""Real worker processes exercise queueing, cancellation and resource refusal."""
import json
import os
import sys
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.task_manager import TaskManager,QueueFull
from dayan.limits import Limits,BudgetExceeded


def wait(manager,jid,predicate,timeout=15):
    end=time.monotonic()+timeout
    while time.monotonic()<end:
        row=manager.get(jid)
        if predicate(row):return row
        time.sleep(.02)
    raise AssertionError('Actual job did not reach expected state')


class Tasks(unittest.TestCase):
    def test_real_model_process_and_durable_result(self):
        with tempfile.TemporaryDirectory() as td:
            m=TaskManager(td)
            try:
                jid=m.submit('api_run',{'req':{'model_id':'NET052','ticks':3,'seed':7}})
                row=wait(m,jid,lambda r:r['status'] in ('done','error'))
                self.assertEqual(row['status'],'done',row)
                self.assertNotEqual(row['pid'],os.getpid())
                self.assertEqual(row['result']['n'],4)
                self.assertTrue(row['result']['run_id'])
                data=json.loads((Path(td)/'tasks'/jid/'result.json').read_text(encoding='utf-8'))
                self.assertTrue(data['success'])
            finally:m.close()

    def test_oversized_experiment_rejected_before_worker(self):
        with tempfile.TemporaryDirectory() as td:
            m=TaskManager(td)
            try:
                with self.assertRaises(BudgetExceeded):m.submit('api_experiment',{'body':{'ticks':10001}})
                with self.assertRaises(BudgetExceeded):m.submit('api_experiment',{'body':{'ticks':10000,'seeds':list(range(10)),'arms':[{'label':'x'}]}})
                self.assertFalse(m.active);self.assertFalse(m.queue)
                self.assertEqual(list((Path(td)/'tasks').glob('*/request.json')),[])
            finally:m.close()

    def test_queue_bound_and_real_cancel(self):
        with tempfile.TemporaryDirectory() as td:
            m=TaskManager(td,replace(Limits(),concurrent=1,queued=1))
            try:
                first=m.submit('api_run',{'req':{'model_id':'NET106','ticks':10000}})
                second=m.submit('api_run',{'req':{'model_id':'NET106','ticks':10000}})
                with self.assertRaises(QueueFull):m.submit('api_run',{'req':{'model_id':'NET106','ticks':1}})
                m.cancel(second)
                wait(m,first,lambda r:r['status']=='running')
                row=m.cancel(first)
                self.assertEqual(row['terminal_reason'],'cancelled')
                self.assertFalse(m.active);self.assertFalse(m.queue)
            finally:m.close()

    def test_actual_worker_wall_and_memory_limits(self):
        for settings,reason in [({'wall_seconds':.01},'wall_timeout'),({'memory_bytes':1},'memory_bytes'),
                                ({'cpu_seconds':.0001},'cpu_seconds')]:
            with self.subTest(reason=reason),tempfile.TemporaryDirectory() as td:
                m=TaskManager(td,replace(Limits(),**settings))
                try:
                    jid=m.submit('api_run',{'req':{'model_id':'NET106','ticks':10000}})
                    row=wait(m,jid,lambda r:r['status']=='error')
                    self.assertEqual(row['terminal_reason'],reason)
                    self.assertFalse(m.active)
                finally:m.close()

    def test_disk_quota_rejects_without_deleting_research(self):
        with tempfile.TemporaryDirectory() as td:
            evidence=Path(td)/'existing-research.txt';evidence.write_text('preserve',encoding='utf-8')
            m=TaskManager(td,replace(Limits(),data_bytes=1))
            try:
                with self.assertRaisesRegex(QueueFull,'磁盘配额'):
                    m.submit('api_run',{'req':{'model_id':'NET052','ticks':1}})
                self.assertEqual(evidence.read_text(encoding='utf-8'),'preserve')
                self.assertFalse(m.active)
            finally:m.close()


if __name__=='__main__':unittest.main(verbosity=2)
