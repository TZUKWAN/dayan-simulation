"""Review-stage delivery facts verified against an actual archived solver run."""
import json

from dayan.agent import model_tools
from dayan.agent.model_delivery import delivery_contract
from test_design_continuation import provider,advance,SOURCE


def test_all_design_stages_receive_replay_endpoints_that_read_the_actual_run(provider):
    from dayan.server import app
    from api_client import local_client
    designed=advance({})
    assert designed['ok'] and designed['payload']['status']=='approved',designed
    expected=delivery_contract()
    for call in provider.calls:
        if call['purpose'].startswith('model-design-'):
            sent=json.loads(call['messages'][1]['content'])
            assert sent['execution']['delivery']==expected
            assert 'execution.delivery' in call['messages'][0]['content']
    action=designed['payload']['next_action']
    result=model_tools.call_native_model(action['action'],action['arguments'],SOURCE,'continuation-owner')
    assert result['ok'],result
    rid=result['payload']['run_id']
    client=local_client(app)
    replay=expected['replay']
    state=client.get(replay['state_url'].replace('{display_run_id}',rid))
    archive=client.get(replay['run_url'].replace('{display_run_id}',rid))
    assert state.status_code==200 and archive.status_code==200
    assert state.json()['run_id']==rid and archive.json()['run_id']==rid
    assert state.json()['observations']==archive.json()['observations']
    assert state.json()['observations'][-1]['stock']==14.
    assert client.get(replay['workbench_url'].replace('{display_run_id}',rid)).status_code==200
    assert client.get(expected['bundle_url'].replace('{display_run_id}',rid)).status_code==200


def test_research_delivery_requires_actual_selected_run_and_same_study_report():
    contract=delivery_contract({'research_intent_id':'MI-explicit-test-marker'})
    assert contract['report_tool']=='research_report'
    assert 'research_finalize' in contract['report_input']
    assert 'research_finalize' in contract['replay']['display_run_id']
    assert 'not the default-parameter baseline' in contract['replay']['display_run_id']
    assert contract['replay']['state_url']==delivery_contract()['replay']['state_url']


def test_semantic_review_can_reference_real_replay_interfaces(monkeypatch):
    from dayan.scene_contract import review_definition
    import dayan.llm_client
    question='回放该模型的真实状态并生成Word。'
    refs=['execution.delivery.replay.state_url','execution.delivery.replay.workbench_url',
          'execution.delivery.report_tool']
    calls=[]
    def complete(messages,**kwargs):
        sent=json.loads(messages[1]['content'])
        assert set(refs)<=set(sent['available_refs'])
        assert sent['execution']['delivery']==delivery_contract()
        calls.append(kwargs['purpose'])
        return json.dumps({'matched':True,'missing':[],
            'checks':[{'quote':question,'refs':refs}],'limitations':[]},ensure_ascii=False)
    monkeypatch.setattr(dayan.llm_client,'complete',complete)
    actual=review_definition(question,{'kind':'stocks'},[],{'delivery':delivery_contract()})
    assert actual['matched'] and calls==['scene-semantic-review']
