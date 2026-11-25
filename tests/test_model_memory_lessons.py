"""Actual failure receipts and user-bound corrections, advisory after conception."""
import json
import pytest
from test_design_continuation import provider,SOURCE
from test_design_revision import bad_mapping
from dayan.agent.model_design import load_design
from dayan.research import model_memory as memory


def test_real_implementation_failure_is_indexed_and_correction_quote_cannot_be_rewritten(provider,monkeypatch):
    from dayan.research.native_contract import protect
    from dayan.agent.tools import call_tool
    from dayan.server import app
    from api_client import local_client
    from dayan.agent import model_tools
    parent,_=bad_mapping(provider,monkeypatch)
    design=load_design(parent);scope=design['memory_scope']
    cards=memory.lessons(scope)
    assert len(cards)==1 and cards[0]['kind']=='failure'
    assert cards[0]['reference']['design_id']==parent and 'capacity' in json.dumps(cards[0]['content'])
    # This genuine prior failure can be recalled for critique, without altering concept.
    concept={'approach':'库存流入','mechanisms':['库存增长']}
    refs=memory.advisory(scope,'continuation-owner',SOURCE,concept)
    assert any(r.get('kind')=='failure' for r in refs)
    assert memory.lessons('project-'+'f'*64)==[]
    quote='以后不要用一个常数容量冒充库存增长，必须核对真实流量和库存的联系。'
    args=protect('memory_feedback',{'design_id':parent,'correction':'Agent擅自改成我的偏好'},quote,'continuation-owner')
    assert args['correction']==quote
    with local_client(app) as client:
        response=client.post('/api/tools/memory_feedback',json={'origin':'dsh','session_id':'continuation-owner',
            'original_text':quote,'arguments':args})
        value=response.json()
    assert value['ok'],value
    assert value['payload']['original_quote']==quote
    latest=memory.lessons(scope)
    assert any(r['kind']=='user_correction' and r['content']['user_quote']==quote for r in latest)
    with pytest.raises(ValueError,match='记忆作用域'):
        memory.remember_correction('project-'+'e'*64,'continuation-owner',quote,design_id=parent)


def test_semantic_selection_uses_real_candidate_ids_and_does_not_accept_fabricated_memory(monkeypatch):
    # Controlled ranking only; no claim of a cloud call in this protocol test.
    candidate={'memory_id':'L-real','kind':'failure','source_request':'以前研究传染扩散',
        'reference':{'design_id':'MD-existing'},'content':{'error':'hazard was used as probability'}}
    monkeypatch.setattr(memory,'references',lambda *args,**kwargs:[])
    monkeypatch.setattr(memory,'lessons',lambda scope:[candidate])
    concept={'approach':'hazard integration','mechanisms':['cumulative survival']}
    result=memory.advisory(memory.WORKBENCH_SCOPE,None,'time-dependent transition intensity',concept,
        rank=lambda candidates:[{'memory_id':candidates[0]['memory_id'],'reason':'将速率直接作概率会破坏连续时钟；当前应积分强度'}])
    assert result[0]['retrieval']['method']=='llm_semantic_mechanism_comparison'
    with pytest.raises(ValueError,match='捏造'):
        memory.advisory(memory.WORKBENCH_SCOPE,None,'time-dependent transition intensity',concept,
            rank=lambda candidates:[{'memory_id':'L-fiction','reason':'invented'}])
