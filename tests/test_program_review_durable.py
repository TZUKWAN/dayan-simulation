"""Separate real workers must reuse the same reviewed input across Python hash seeds.

Only the LLM provider reply is a controlled protocol fixture, never native-Agent proof.
"""
import json
import os
from pathlib import Path
import subprocess
import sys

from test_program_runtime import definition


def test_review_identity_is_stable_across_processes_and_dictionary_order_but_not_changed_code(tmp_path):
    root=Path(__file__).resolve().parents[1]
    source=tmp_path/'definition.json'
    source.write_text(json.dumps(definition()),encoding='utf-8')
    child=r'''
import json,sys,time,hashlib
from pathlib import Path
from dayan.scene_contract import review_definition
from dayan.custom_models import validate_definition
from dayan.agent.design_checkpoint import DesignCheckpoint
from dayan.collection.storage import read_json
import dayan.llm_client
folder=Path(sys.argv[1])
definition=validate_definition(json.loads((folder/'definition.json').read_text(encoding='utf-8')))
if sys.argv[2]=='reverse':
    def reverse(value):
        if isinstance(value,dict):return {k:reverse(v) for k,v in reversed(list(value.items()))}
        if isinstance(value,list):return [reverse(v) for v in value]
        return value
    definition=reverse(definition)
path=folder/'checkpoint.json'
record=read_json(path) if path.exists() else {'stages':[]}
calls=[]
def provider(messages,**kwargs):
    ident='controlled-'+str(len(record.get('llm_calls',[]))+1)
    with (folder/'calls.jsonl').open('a',encoding='utf-8') as f:
        f.write(json.dumps({'id':ident,'request':hashlib.sha256(json.dumps(messages).encode()).hexdigest()})+'\n')
    kwargs['audit'].append({'call_id':ident,'purpose':kwargs['purpose'],'ok':True})
    return json.dumps({'matched':True,'missing':[],'checks':[{'quote':'同一数值模型','refs':['source.advance']}],'limitations':[]})
dayan.llm_client.complete=provider
checkpoint=DesignCheckpoint(record,path,calls,time.monotonic()+300)
result=review_definition('同一数值模型',definition,calls,{'dt':.2,'ticks':5},checkpoint=checkpoint)
assert result['matched']
print(json.dumps({'stages':len(record['stages']),'calls':len(record['llm_calls'])}))
'''
    for seed,order in (('1','normal'),('2','normal'),('3','reverse')):
        result=subprocess.run([sys.executable,'-c',child,str(tmp_path),order],cwd=root,
            env={**os.environ,'PYTHONHASHSEED':seed,'DAYAN_DATA_DIR':str(tmp_path/'data'),'PYTHONIOENCODING':'utf-8'},
            capture_output=True,text=True,encoding='utf-8',timeout=30)
        assert result.returncode==0,result.stderr
        assert json.loads(result.stdout)=={'stages':1,'calls':1}
    changed=definition()
    changed['source']=changed['source'].replace('rng.normal(0., .25','rng.normal(0., .5')
    source.write_text(json.dumps(changed),encoding='utf-8')
    result=subprocess.run([sys.executable,'-c',child,str(tmp_path),'normal'],cwd=root,
        env={**os.environ,'PYTHONHASHSEED':'4','DAYAN_DATA_DIR':str(tmp_path/'data'),'PYTHONIOENCODING':'utf-8'},
        capture_output=True,text=True,encoding='utf-8',timeout=30)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'stages':2,'calls':2}
