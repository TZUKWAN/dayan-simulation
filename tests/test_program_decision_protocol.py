"""Real solver and ledger; controlled LLM here is explicitly a protocol fixture."""
from copy import deepcopy
import json

import pytest

from dayan import decision_broker
from dayan.collection.storage import read_json, atomic_json
from dayan.solvers.codec import decode
from dayan.solvers.sandbox import run_segment, SolverError
from test_solver_sandbox import LIVE, MINIMAL

POLICY = {'instruction': 'Controlled protocol fixture, not an empirical actor.',
    'action_schema': {'type': 'object', 'properties': {'delta': {'type': 'number', 'minimum': -5, 'maximum': 5}},
                      'required': ['delta'], 'additionalProperties': False}}
SOURCE = MINIMAL.replace('state["v"] + 1', 'state["v"] + sum(row["action"]["delta"] for row in decisions["agents"]["actions"])')
SOURCE = SOURCE.replace('rng, time, dt):', 'rng, time, dt, decisions):')
SOURCE += '''
def decision_requests(state, parameters, inputs, time):
    return [{"id":"agents","actor_ids":["people:a","people:b"],"prompt":"Actual state value="+str(state["v"])}]
'''


def test_policy_validates_standard_action_schema_and_disallows_network_references():
    assert decision_broker.validate_policy(POLICY) == POLICY
    with pytest.raises(ValueError, match='本地'):
        decision_broker.validate_policy({**POLICY, 'action_schema': {'$ref': 'https://example.org/schema'}})
    with pytest.raises(ValueError, match='有效JSON Schema'):
        decision_broker.validate_policy({**POLICY, 'action_schema': {'type': 'invented'}})


@LIVE
def test_actual_solver_requests_host_decisions_binds_state_and_advances_with_actual_returned_actions(monkeypatch, tmp_path):
    import dayan.llm_client
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    initial = run_segment(SOURCE, ticks=2, dt=.5, seed=7, segment_steps=0, decision_policy=POLICY)
    descriptor = initial['next_decisions']
    assert descriptor['step'] == 0 and descriptor['requests'][0]['actor_ids'] == ['people:a', 'people:b']
    assert decode(initial['checkpoint']['state']) == {'v': 1}
    calls = []
    def controlled_complete(messages, *, audit, **kwargs):
        calls.append(messages)
        audit.append({'call_id': 'controlled-protocol-call', 'purpose': kwargs['purpose'], 'ok': True})
        return json.dumps({'actions': [{'actor_id': 'people:a', 'action': {'delta': 1.25}},
                                      {'actor_id': 'people:b', 'action': {'delta': -2.}}]})
    monkeypatch.setattr(dayan.llm_client, 'complete', controlled_complete)
    bundle, receipts, audit = decision_broker.resolve(POLICY, descriptor, 'controlled-run', timeout=30)
    cached = decision_broker.resolve(POLICY, descriptor, 'controlled-run', timeout=30)
    assert bundle == cached[0] and len(calls) == 1
    assert receipts[0]['response_sha256'] and audit[0]['purpose'] == 'program-actor-decision'
    result = run_segment(SOURCE, ticks=2, dt=.5, seed=7, segment_steps=1,
        checkpoint=initial['checkpoint'], decision_policy=POLICY, decision_bundle=bundle)
    assert result['records'][0]['observations']['value'] == .25
    assert result['next_decisions']['step'] == 1 and result['next_decisions']['key'] != descriptor['key']
    with pytest.raises(SolverError, match='身份不一致'):
        run_segment(SOURCE, ticks=2, dt=.5, seed=7, segment_steps=1,
            checkpoint=result['checkpoint'], decision_policy=POLICY, decision_bundle=bundle)
    path = tmp_path / 'actor_decisions' / (receipts[0]['decision_id'] + '.json')
    row = read_json(path)
    row['response']['actions'][0]['action']['delta'] = 4
    atomic_json(path, row)
    with pytest.raises(ValueError, match='摘要校验'):
        decision_broker.resolve(POLICY, descriptor, 'controlled-run', timeout=30)
    assert len(calls) == 1


@LIVE
def test_actual_decision_request_cannot_mutate_solver_state(monkeypatch, tmp_path):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path))
    source = SOURCE.replace('def decision_requests(state, parameters, inputs, time):',
                           'def decision_requests(state, parameters, inputs, time):\n    state["v"] += 100')
    with pytest.raises(SolverError, match='修改了状态'):
        run_segment(source, ticks=1, dt=.5, seed=7, segment_steps=0, decision_policy=POLICY)


@LIVE
def test_empty_decision_boundaries_batch_until_next_actual_request_without_skipping_steps(monkeypatch,tmp_path):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    source=SOURCE.replace('def decision_requests(state, parameters, inputs, time):',
        'def decision_requests(state, parameters, inputs, time):\n    if time not in (0., 1.5): return []')
    source=source.replace('decisions["agents"]["actions"]','decisions.get("agents", {"actions":[]})["actions"]')
    initial=run_segment(source,ticks=5,dt=.5,seed=7,segment_steps=0,decision_policy=POLICY)
    descriptor=initial['next_decisions']
    bundle={'key':descriptor['key'],'results':{row['id']:{'actions':[]} for row in descriptor['requests']}}
    # Worker deliberately treats decision values as user-program values; schema
    # validation belongs to the separately tested host broker.
    batch_id=descriptor['requests'][0]['id']
    bundle['results'][batch_id]={'actions':[{'actor_id':ident,'action':{'delta':1.}} for ident in descriptor['requests'][0]['actor_ids']]}
    result=run_segment(source,ticks=5,dt=.5,seed=7,segment_steps=5,decision_policy=POLICY,
        checkpoint=initial['checkpoint'],decision_bundle=bundle)
    assert result['to_step']==3 and [r['step'] for r in result['records']]==[1,2,3]
    assert result['next_decisions']['requests']
