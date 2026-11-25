"""Actual container CA numerics with independent scalar reference, not policy evidence."""
import math

import numpy as np
import pytest

from dayan.custom_models import register
from dayan.engine_capabilities import program_blockers
from dayan.population_groups import decode_attribute
from dayan.research.requirements import extract_request
from dayan.run_store import get_store
from dayan.runtime import resume_from_checkpoint, run_model_full
from test_solver_sandbox import LIVE


SOURCE = '''import numpy as np

def neighbors(values, degree, boundary):
    rows, columns = values.shape
    offsets = [(-1,0),(1,0),(0,-1),(0,1)]
    if degree == 8:
        offsets += [(-1,-1),(-1,1),(1,-1),(1,1)]
    if boundary == "periodic":
        return sum(np.roll(values, (-dy,-dx), axis=(0,1)) for dy,dx in offsets)
    padded = np.pad(values, 1, mode="edge" if boundary == "reflecting" else "constant")
    return sum(padded[1+dy:1+dy+rows,1+dx:1+dx+columns] for dy,dx in offsets)

def initialize(parameters, inputs, rng):
    indices = np.arange(parameters["rows"]*parameters["columns"]).reshape(parameters["rows"],parameters["columns"])
    return {"a":(indices%3==0).astype(np.int64),"b":(indices%5<2).astype(np.int64),
            "c":((indices+2*(indices//parameters["columns"]))%4<2).astype(np.int64)}

def advance(state, parameters, inputs, rng, time, dt):
    if dt != 1:
        raise ValueError("This declared CA has synchronous unit steps")
    keys = ["a","b","c"]
    randoms = rng.random((3,parameters["rows"],parameters["columns"]))
    changed = {}
    for index,key in enumerate(keys):
        local = neighbors(state[key],parameters["degree"],parameters["boundary"])/parameters["degree"]
        score = local-0.5+0.35*state[keys[(index+1)%3]]-0.2*state[keys[(index+2)%3]]
        probability = 1/(1+np.exp(-2*score))
        changed[key] = (randoms[index]<probability).astype(np.int64)
    return {"state":changed,"events":[]}

def observe(state, parameters, inputs, time):
    return {"share_a":float(np.mean(state["a"])),"share_b":float(np.mean(state["b"])),
            "share_c":float(np.mean(state["c"]))}

def frame(state, parameters, inputs, time):
    rows,columns = parameters["rows"],parameters["columns"]
    return {"populations":[{"id":key,"type":"cell", "columns":{
        "x":np.tile(np.arange(columns,dtype=float),rows),
        "y":np.repeat(np.arange(rows,dtype=float),columns),"strategy":state[key].ravel()},
        "units":{"x":"cell","y":"cell","strategy":"1"},"color_by":"strategy"}
        for key in ["a","b","c"]],"space":{"bounds":[0.,0.,float(columns),float(rows)],"unit":"cell"}}

def validate(state, parameters, inputs, time):
    if parameters["boundary"] not in ["periodic","reflecting","absorbing"] or parameters["degree"] not in [4,8]:
        raise ValueError("Invalid declared neighborhood")
    for key in ["a","b","c"]:
        if state[key].shape != (parameters["rows"],parameters["columns"]) or not np.all((state[key]==0)|(state[key]==1)):
            raise ValueError("Actual lattice state is invalid")
'''


def definition():
    return {'kind': 'program', 'name': '三层概率CA执行数值基准',
            'description': '明确构造的局部更新数学夹具，不是实际政策模型或原生Agent模型',
            'time_unit': 'step', 'source': SOURCE,
            'parameters': {**{key: {'type': 'int', 'default': value, 'minimum': 3, 'maximum': 128, 'unit': '1'}
                              for key, value in [('rows', 7), ('columns', 8), ('degree', 4)]},
                           'boundary': {'type': 'str', 'default': 'periodic', 'unit': '1'}},
            'populations': [{'id': key, 'type': 'cell', 'label': label, 'count': 'rows*columns', 'dynamic': False,
                             'attributes': {name: {'kind': 'numeric', 'unit': unit}
                                            for name, unit in [('x', 'cell'), ('y', 'cell'), ('strategy', '1')]}}
                            for key, label in [('a', '甲层'), ('b', '乙层'), ('c', '丙层')]],
            'observables': {'share_' + key: {'label': label, 'unit': '1', 'equation': 'mean(' + key + ')'}
                            for key, label in [('a', '甲层占比'), ('b', '乙层占比'), ('c', '丙层占比')]},
            'solver': {'method': 'synchronous local probabilistic CA',
                       'description': '先读三层旧状态，再以同一随机流更新；边界为周期/格面反射/域外零值'},
            'equations': [{'id': 'transition', 'expression':
                           'Pr(s_l(i,t+1)=1)=sigmoid(2*(mean_neighbor(s_l)-0.5+0.35*s_next-0.2*s_other))',
                           'function': 'advance', 'meaning': '四或八邻局部均值和同格跨层耦合'}],
            'mechanisms': ['局部CA', '独立角色人口', '同步跨层反馈'],
            'assumptions': ['人为规定的数学概率规则和初态'], 'limitations': ['不作经验校准或政策结论']}


def reference(degree, boundary, *, global_mean=False):
    """Scalar indexing and math.exp, independent of vectorized source above."""
    rows, columns = 7, 8
    state = np.empty((3, rows, columns), dtype=np.int64)
    for y in range(rows):
        for x in range(columns):
            i = y * columns + x
            state[:, y, x] = [i % 3 == 0, i % 5 < 2, (i + 2*y) % 4 < 2]
    rng = np.random.default_rng(19)
    frames = [state.copy()]
    for _ in range(4):
        draws = rng.random((3, rows, columns))
        changed = np.empty_like(state)
        for layer in range(3):
            for y in range(rows):
                for x in range(columns):
                    values = []
                    for dy in range(-1, 2):
                        for dx in range(-1, 2):
                            if not (dy or dx) or degree == 4 and abs(dx) + abs(dy) != 1:
                                continue
                            yy, xx = y + dy, x + dx
                            if boundary == 'periodic':
                                value = state[layer, yy % rows, xx % columns]
                            elif boundary == 'reflecting':
                                value = state[layer, min(max(yy, 0), rows-1), min(max(xx, 0), columns-1)]
                            else:
                                value = state[layer, yy, xx] if 0 <= yy < rows and 0 <= xx < columns else 0
                            values.append(value)
                    local = float(state[layer].mean()) if global_mean else sum(values) / degree
                    score = local - .5 + .35*state[(layer+1) % 3, y, x] - .2*state[(layer+2) % 3, y, x]
                    probability = 1 / (1 + math.exp(-2 * score))
                    changed[layer, y, x] = draws[layer, y, x] < probability
        state = changed
        frames.append(state.copy())
    return frames


def test_program_ca_is_not_rejected_by_a_blanket_method_label():
    parsed = extract_request('自主构建三方演化博弈，元胞自动机CA局部邻域与异类ABM结合，按实际算法计算。')
    assert '网格局部交互' in parsed['mechanisms']
    assert not program_blockers(parsed)
    from dayan.program_models import validate_definition
    from dayan.program_evidence import check_plan
    model=validate_definition(definition())
    plan={'rule_refs':[{'mechanism':'三层局部CA','paths':['source.advance','source.neighbors']}],
          'criteria':[{'id':'V1','fields':['share_a','share_b','share_c']}],
          'coverage':[{'quote':'局部CA的真实状态演化','role':'mechanism','criteria':['V1']}]}
    evidence=check_plan(plan,model)
    assert {'a','b','c'}<=set(evidence['updated_fields'])
    carried={**model,'source':model['source'].replace('changed[key] = (randoms[index]<probability).astype(np.int64)',
                                                   'changed[key] = state[key]')}
    with pytest.raises(ValueError,match='实际演化'):
        check_plan(plan,carried)


def test_program_ca_accepts_descriptive_mechanism_names_and_still_requires_semantic_review(monkeypatch,tmp_path):
    from dayan.agent import model_tools
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    question='自建元胞自动机，保留真实局部相互作用和三类格点角色的完整空间状态。'
    model=definition()
    model['mechanisms']=['按实际邻接计算概率的局部CA同步演化','同格三层反馈']
    model['scenario']={'title':'三层CA数学场景','setting':'完整格点坐标来自实际数组',
        'agent_label':'格点','source_request':question,'facilities':[],
        'requirements':[{'quote':'真实局部相互作用','model_refs':['source.advance','source.neighbors'],
                         'visual_refs':['source.frame']}]}
    result=model_tools.call_native_model('validate_model',{'definition':model,'ticks':4,'dt':1.,'seed':19},
                                         question,'descriptive-ca-owner')
    assert result['ok'],result
    assert result['payload']['semantic_review_pending'] and not result['payload']['executed']


@LIVE
@pytest.mark.parametrize('degree', [4, 8])
@pytest.mark.parametrize('boundary', ['periodic', 'reflecting', 'absorbing'])
def test_actual_program_ca_full_states_match_scalar_local_reference_and_resume(monkeypatch, tmp_path, degree, boundary):
    monkeypatch.setenv('DAYAN_DATA_DIR', str(tmp_path / 'data'))
    model = register(definition())
    actual = run_model_full(model['model_id'], parameters={'degree': degree, 'boundary': boundary},
                            ticks=4, dt=1., seed=19, capture_state=True, full_frames=True,
                            checkpoint_at=2 if degree == 8 and boundary == 'periodic' else None)
    expected = reference(degree, boundary)
    global_replacement = reference(degree, boundary, global_mean=True)
    assert any(not np.array_equal(a, b) for a, b in zip(expected, global_replacement))
    assert len(actual.state_frames) == len(actual.observations) == 5
    assert actual.manifest['execution_environment']['system'] == 'Linux'
    for index, (frame, row) in enumerate(zip(actual.state_frames, actual.observations)):
        assert frame['sim_t'] == row['sim_t'] == index
        assert frame['population']['count'] == 3 * 7 * 8
        groups = {g['id']: g for g in frame['population']['groups']}
        for layer, key in enumerate(['a', 'b', 'c']):
            group = groups[key]
            values = decode_attribute(group['columns']['strategy'], group['count']).reshape(7, 8)
            assert np.array_equal(values, expected[index][layer]), (index, key, degree, boundary)
            assert row['share_' + key] == float(expected[index][layer].mean())
    if degree == 8 and boundary == 'periodic':
        continued = resume_from_checkpoint(actual.checkpoint, steps=2, dt=1., capture_state=True, with_initial=True)
        assert continued.observations == actual.observations[2:]
        strip = lambda frames: [{k: v for k, v in f.items() if k != 'run_id'} for f in frames]
        assert strip(continued.state_frames) == strip(actual.state_frames[2:])
        run_id = get_store().save_run(actual, source='actual_container_numerical_fixture',
                                      request_text='维护数值验证，不是现实政策或原生Agent建模')
        saved = get_store().load(run_id)
        assert saved['state_frames'] == actual.state_frames
