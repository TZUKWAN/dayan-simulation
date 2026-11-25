"""Explicit offline probe acceptance; never runs as a side effect of opening UI.

Finite outputs are execution evidence only. They do not prove mechanisms or
empirical validity. External-service models are explicitly excluded and recorded.
"""
import json
import os
import platform
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from dayan.fidelity import probe_batch,models_source_fingerprint
from dayan.model_index import ALL_INDEX


class AllModelProbes(unittest.TestCase):
    def test_all_builtin_entry_points_in_isolated_workers(self):
        mids=sorted(m for m in ALL_INDEX if not m.startswith('USR'))
        result=probe_batch(mids,ticks=5)
        failed={m:r for m,r in result.items() if not r.get('ok') and not r.get('skipped')}
        output=Path(os.environ.get('DAYAN_DATA_DIR',Path(__file__).resolve().parents[1]/'.claude/probe_acceptance'))
        output.mkdir(parents=True,exist_ok=True)
        evidence={'version':1,'source_fingerprint':models_source_fingerprint(),
            'python':platform.python_version(),'probe_ticks':5,'seed':0,'results':result,
            'scope':'离线参考运行，不是现实数据、机制忠实度、校准或留出有效性的证明'}
        (output/'output_contract_evidence.json').write_text(json.dumps(evidence,ensure_ascii=False,indent=1),encoding='utf-8')
        self.assertEqual(set(result),set(mids))
        self.assertFalse(failed,json.dumps(failed,ensure_ascii=False))
        self.assertTrue(all(r.get('requires_external') for r in result.values() if r.get('skipped')))
        print('Actual probes passed=%s; external not executed=%s'%(sum(bool(r.get('ok')) for r in result.values()),sum(bool(r.get('skipped')) for r in result.values())))


if __name__=='__main__':unittest.main(verbosity=2)
