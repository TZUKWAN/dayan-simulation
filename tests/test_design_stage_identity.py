"""Real checkpoint reuse for equivalent JSON, with meaningful changes isolated."""
from copy import deepcopy
import json,time
from dayan.agent.design_checkpoint import DesignCheckpoint


def messages(execution,request='原始需求逐字保留',**extra):
    return [{'role':'system','content':'固定阶段合同'},
        {'role':'user','content':json.dumps({'original_request':request,'execution':execution,**extra},ensure_ascii=False)}]


def checkpoint(tmp_path):
    return DesignCheckpoint({'llm_calls':[],'stages':[]},tmp_path/'checkpoint.json',[],time.monotonic()+300)


def test_semantically_identical_reordered_execution_reuses_saved_stage(tmp_path):
    cp=checkpoint(tmp_path)
    a=messages({'seed':7,'parameters':{'n':128,'speed':1.2},'seeds':[7,11]})
    b=messages({'seeds':[7,11],'parameters':{'speed':1.2,'n':128},'seed':7})
    original_a,original_b=deepcopy(a),deepcopy(b)
    ident,_,present=cp.cached('concept',a)
    assert not present
    cp.store('concept',ident,{'approach':'已保存的受控缓存测试结果'})
    recovered,value,present=cp.cached('concept',b)
    assert present and recovered==ident and value['approach']=='已保存的受控缓存测试结果'
    assert a==original_a and b==original_b # The actual model messages are untouched.


def test_original_text_clock_array_order_code_and_initializer_order_do_not_alias(tmp_path):
    cp=checkpoint(tmp_path)
    base=messages({'seed':7,'dt':.25,'seeds':[7,11]},definition={'initial_state':{'a':1,'b':'a+1'},'source':'value = 1\n'})
    ident,_,_=cp.cached('plan',base);cp.store('plan',ident,{'verified':'test-only'})
    changed=[]
    for field,value in [('original_request','原始需求逐字保留 '),('execution',{'seed':7,'dt':.5,'seeds':[7,11]}),
            ('execution',{'seed':7,'dt':.25,'seeds':[11,7]}),
            ('definition',{'initial_state':{'b':'a+1','a':1},'source':'value = 1\n'}),
            ('definition',{'initial_state':{'a':1,'b':'a+1'},'source':'value=1\n'})]:
        payload=json.loads(base[1]['content']);payload[field]=value
        candidate=deepcopy(base);candidate[1]['content']=json.dumps(payload,ensure_ascii=False);changed.append(candidate)
    for candidate in changed:assert cp.cached('plan',candidate)[2] is False
    assert cp.cached('review',base)[2] is False


def test_non_machine_messages_keep_exact_identity(tmp_path):
    cp=checkpoint(tmp_path)
    a=[{'role':'user','content':'{"a":1,"b":2}'}]
    b=[{'role':'user','content':'{"b":2,"a":1}'}]
    ident,_,_=cp.cached('concept',a);cp.store('concept',ident,{'verified':'test-only'})
    assert not cp.cached('concept',b)[2]
