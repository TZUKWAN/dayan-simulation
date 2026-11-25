"""Opaque continuation uses real persisted stages and actual mathematical runs.

The semantic provider is controlled; this is not native cloud-model acceptance.
"""
import json

from test_design_continuation import provider,SOURCE,advance
from dayan.agent import model_tools
from dayan.agent.model_continuation import _path,restore
from dayan.run_store import get_store


def test_compact_next_action_restores_the_actual_request_clock_and_archived_result(provider):
    provider.cost=70
    first=advance({})
    assert first['ok'] and first['payload']['status']=='pending'
    initial=first['payload']['next_action']
    assert set(initial['arguments'])=={'design_id','continuation_token'}
    original,source,_=restore(initial['action'],initial['arguments']['continuation_token'],{},SOURCE,'continuation-owner')
    assert source==original['request']==SOURCE
    assert (original['ticks'],original['dt'],original['seed'])==(4,.5,7)
    result=first
    for _ in range(10):
        action=result.get('payload',{}).get('next_action')
        if not action:break
        result=model_tools.call_native_model(action['action'],action['arguments'],SOURCE,'continuation-owner')
        assert result['ok'],result
        if result['payload'].get('run_id'):break
    saved=get_store().load(result['payload']['run_id'])
    assert saved['request_text']==SOURCE
    assert saved['observations'][-1]['stock']==14
    assert saved['manifest']['rng']['seed']==7
    assert [r['purpose'] for r in provider.calls].count('model-design-concept')==1
    assert len(provider.calls)==7


def test_continuation_rejects_different_context_overrides_and_tampering_before_calls(provider):
    provider.cost=70
    first=advance({})['payload'];action=first['next_action'];args=action['arguments']
    count=len(provider.calls)
    for options,source,session,tool in [
        (args,SOURCE+'变化。','continuation-owner',action['action']),
        (args,SOURCE,'another-session',action['action']),
        ({**args,'parameters':{'flow':999}},SOURCE,'continuation-owner',action['action']),
        ({**args,'ticks':99},SOURCE,'continuation-owner',action['action']),
        (args,SOURCE,'continuation-owner','validate_model'),
    ]:
        result=model_tools.call_native_model(tool,options,source,session)
        assert not result['ok'] and '续接' in result['error'],result
    assert len(provider.calls)==count
    path=_path(args['continuation_token'])
    record=json.loads(path.read_text(encoding='utf-8'));record['state']['arguments']['seed']=8
    path.write_text(json.dumps(record,ensure_ascii=False),encoding='utf-8')
    result=advance(args)
    assert not result['ok'] and '校验失败' in result['error']
    assert len(provider.calls)==count
