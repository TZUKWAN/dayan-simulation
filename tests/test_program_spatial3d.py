"""Real 3D route integration, terrain/floor frame validation and same-run report."""
from copy import deepcopy
import json
from pathlib import Path
import numpy as np
import pytest
from test_solver_sandbox import LIVE

SPACE={'bounds':[-2.,-2.,8.,2.],'vertical_bounds':[0.,5.],'unit':'m',
    'terrain':{'id':'slope','label':'真实数值坡面','origin':[0.,-1.],'spacing':[1.,1.],
               'heights':[[0.,.2,.4],[0.,.2,.4],[0.,.2,.4]]},
    'floors':[{'id':'lower','label':'下层平台','elevation':0.,'bounds':[-2.,-1.,0.,1.]},
              {'id':'upper','label':'上层平台','elevation':3.,'bounds':[4.,-1.,8.,1.]}],
    'connectors':[{'id':'ramp','label':'跨层坡道','kind':'ramp','from':'slope','to':'upper',
                   'polyline':[[2.,0.,.4],[4.,0.,3.]],'width':1.2}]}
ROUTE=[[-1.,0.,0.],[0.,0.,0.],[2.,0.,.4],[4.,0.,3.],[6.,0.,3.]]


def definition():
    source='''import numpy as np

def locate(state, distance):
    nodes=state["route"]
    for j in range(len(nodes)-1):
        delta=nodes[j+1]-nodes[j]
        length=float(np.linalg.norm(delta))
        if distance<=length:
            return nodes[j]+delta*(distance/length),["lower","slope","ramp","upper"][j]
        distance-=length
    return nodes[-1].copy(),"upper"

def initialize(parameters, inputs, rng):
    return {"route":np.array(ROUTE,dtype=float),"space":SPACE,"distance":np.zeros(2)}

def advance(state, parameters, inputs, rng, time, dt):
    total=float(np.linalg.norm(np.diff(state["route"],axis=0),axis=1).sum())
    state["distance"]=np.minimum(total,state["distance"]+parameters["speed"]*np.array([1.,.8])*dt)
    return {"state":state,"events":[]}

def observe(state, parameters, inputs, time):
    points=[locate(state,float(d))[0] for d in state["distance"]]
    return {"mean_height":float(np.mean([p[2] for p in points])),"total_distance":float(state["distance"].sum())}

def frame(state, parameters, inputs, time):
    located=[locate(state,float(d)) for d in state["distance"]]
    positions=np.array([p for p,f in located])
    return {"space":state["space"],"populations":[{"id":"people","type":"person","ids":["a","b"],
        "columns":{"x":positions[:,0],"y":positions[:,1],"z":positions[:,2],"floor_id":[f for p,f in located],"action":["walking","walking"]},
        "units":{"x":"m","y":"m","z":"m","floor_id":"1","action":"1"}}]}

def validate(state, parameters, inputs, time):
    assert len(state["distance"])==2 and np.isfinite(state["distance"]).all()
'''.replace('ROUTE',repr(ROUTE)).replace('SPACE',repr(SPACE))
    return {'kind':'program','name':'跨层地形人物数值验证','description':'三维路径弧长推进及真实支撑面/楼层转换，非经验预测',
        'time_unit':'s','source':source,'parameters':{'speed':{'type':'float','default':1.,'minimum':.1,'maximum':2.,'unit':'m/s'}},
        'populations':[{'id':'people','label':'数值基准人员','type':'person','count':2,'dynamic':False,
            'attributes':{**{k:{'kind':'numeric','unit':'m'} for k in ('x','y','z')},
                          'floor_id':{'kind':'categorical','unit':'1'},'action':{'kind':'categorical','unit':'1'}}}],
        'observables':{'mean_height':{'label':'平均实际高度','unit':'m','equation':'mean(z_i)'},
                       'total_distance':{'label':'三维路程合计','unit':'m','equation':'sum(s_i)'}},
        'equations':[{'id':'path','expression':'s_i(t+dt)=min(L,s_i+v_i*dt); r_i=piecewise_linear_3D_path(s_i)',
                      'function':'advance','meaning':'三维弧长含真实高差；floor_id从相应路段给出'}],
        'solver':{'method':'piecewise exact arc-length integration','description':'真实三维路段长度和端点饱和'},
        'mechanisms':['三维路径弧长、地形坡面与跨层连接共同约束坐标'],
        'assumptions':['明确假定几何及恒定速度用于独立数值验算'],'limitations':['未校准真实行走或事故风险'],
        'scenario':{'title':'地形与跨层路径','setting':'明确数学几何','agent_label':'人员','source_request':'跨楼层人物沿地形坡面和坡道移动。',
            'facilities':[],'requirements':[{'quote':'跨楼层人物沿地形坡面和坡道移动','model_refs':['source.advance'],'visual_refs':['source.frame']}]}}


def oracle(distance):
    nodes=np.asarray(ROUTE);lengths=np.sqrt(((nodes[1:]-nodes[:-1])**2).sum(axis=1));cumulative=np.r_[0,np.cumsum(lengths)]
    distance=min(distance,cumulative[-1]);j=min(int(np.searchsorted(cumulative,distance,side='left'))-1,len(lengths)-1);j=max(0,j)
    return nodes[j]+(nodes[j+1]-nodes[j])*((distance-cumulative[j])/lengths[j])


@LIVE
def test_actual_spatial_solver_and_word_match_independent_3d_arc_length(monkeypatch,tmp_path):
    from dayan.custom_models import register
    from dayan.runtime import run_model_full
    from dayan.run_store import get_store,state_stream
    from dayan.population_group_analysis import movement_between
    from dayan.agent.scenario_tools import report_run
    from dayan.spatial_contract import validate_space,validate_population
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    mid=register(definition())['model_id']
    rr=run_model_full(mid,ticks=20,dt=.5,seed=7,capture_state=True,full_frames=True)
    assert len(rr.state_frames)==21
    for frame in rr.state_frames:
        for i,e in enumerate(frame['entities']):
            np.testing.assert_allclose([e['x'],e['y'],e['z']],oracle(frame['sim_t']*[1.,.8][i]),rtol=0,atol=1e-10)
        assert frame['aggregates']['mean_height']==pytest.approx(np.mean([e['z'] for e in frame['entities']]))
    assert {e['floor_id'] for f in rr.state_frames for e in f['entities']}=={'lower','slope','ramp','upper'}
    # z must contribute to the movement statistic, not merely the display.
    movement=movement_between(rr.state_frames[7],rr.state_frames[6])
    independent=np.mean([np.linalg.norm(oracle(3.5*v)-oracle(3*v)) for v in (1.,.8)])
    assert movement['meanDistance']==pytest.approx(independent)
    bad=deepcopy(SPACE);bad['connectors'][0]['polyline'][-1][2]=2.
    with pytest.raises(ValueError,match='端点高度'):validate_space(bad)
    rid=get_store().save_run(rr,source='three_dimensional_numerical_verification',request_text='三维数学验算，非原生建模或现实预测')
    report=report_run(rid)
    assert report['ok'],report
    facts=json.loads(Path(report['payload']['path']).with_suffix('.json').read_text(encoding='utf-8'))
    figures=facts['view_analysis']['figures']
    assert {'vertical_trajectories','spatial_3d_paths','floor_occupancy'}<={f['kind'] for f in figures}
    counts=next(f['evidence']['full_counts'] for f in figures if f['kind']=='floor_occupancy')
    assert all(sum(c.values())==2 for c in counts) and counts[-1]=={'upper':2}
    assert state_stream(get_store().load(rid))['frames'][-1]['space']['floors']==SPACE['floors']
