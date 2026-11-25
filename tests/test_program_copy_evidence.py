"""Ordinary Python copies/kwargs remain traceable; copies/counts do not fake change."""
from dayan.program_evidence import state_dependencies


def model(body):
    return {'kind':'program','populations':[{'id':'people','dynamic':False}],
        'source':'''import copy
def initialize(parameters,inputs,rng):
    return {"x":[0.,1.],"panic":[0.,0.]}
def change(state,amount):
    state["x"] = state["x"] + amount
    state["panic"] = state["panic"] + amount
def advance(state,parameters,inputs,rng,time,dt):
    '''+body+'''
def observe(state,parameters,inputs,time):
    return {"location":sum(state["x"]),"mean_panic":sum(state["panic"]),"count":len(state["x"]),"fake":0*sum(state["x"])}
def frame(state,parameters,inputs,time):
    return {"populations":[{"id":"people","columns":{"x":state["x"]}}]}
'''}


def test_dictionary_copies_comprehensions_and_keyword_helpers_trace_actual_state():
    for expression in ('state.copy()','dict(state)','copy.deepcopy(state)',
        '{key: value.copy() if isinstance(value,list) else value for key,value in state.items()}'):
        d=model('st = '+expression+'\n    change(amount=dt,state=st)\n    return {"state":st,"events":[]}')
        result=state_dependencies(d)
        assert {'x','panic'}<=set(result['updated_fields']),expression
        assert result['observables']['location']==['x'] and result['observables']['mean_panic']==['panic']
        assert not result['observables']['fake']
        assert 'x#count' not in result['updated_fields']
        rendered={**d,'source':d['source'].replace('"x":state["x"]}}]}','"x":state["x"].astype(float).tolist()}}]}')}
        assert rendered['source']!=d['source']
        assert 'x#count' not in state_dependencies(rendered)['updated_fields']


def test_dictionary_update_traces_real_replacement_without_turning_copy_into_change():
    for update in ('st.update({"x":st["x"]+dt,"panic":st["panic"]+dt})',
                   'st.update(x=st["x"]+dt,panic=st["panic"]+dt)'):
        d=model('st = dict(state)\n    '+update+'\n    return {"state":st,"events":[]}')
        result=state_dependencies(d)
        assert {'x','panic'}<=set(result['updated_fields'])
        assert 'x#count' not in result['updated_fields']
    unchanged=model('st = dict(state)\n    st.update(state)\n    return {"state":st,"events":[]}')
    assert not state_dependencies(unchanged)['updated_fields']


def test_copy_only_is_not_a_state_evolution_or_a_population_count_change():
    d=model('st = {key:value.copy() if isinstance(value,list) else value for key,value in state.items()}\n    return {"state":st,"events":[]}')
    result=state_dependencies(d)
    assert not result['updated_fields']
