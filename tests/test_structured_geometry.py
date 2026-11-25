"""Constructed geometry fixtures, explicitly not surveyed/empirical locations."""
from copy import deepcopy
import json

import pytest

from dayan.datasets import ingest
from dayan.structured_inputs import prepare_structured
from dayan.structured_geometry import features_summary, geometry_contract, pointer_value
from test_solver_sandbox import LIVE


def spec():
    return {'crs':'OGC:CRS84','axes':['longitude','latitude'],'units':['degree','degree'],
            'coordinate_evidence':'RFC7946; constructed protocol coordinates','allow_null':True}


def test_geometry_holes_identity_nulls_nested_properties_and_coordinates_survive_binding(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    features=[{'type':'Feature','id':'001','properties':{'id':'other','a/b':{'~name':'A'},'capacity':12},
        'geometry':{'type':'Polygon','coordinates':[
            [[0,0],[4,0],[4,4],[0,4],[0,0]],[[1,1],[1,2],[2,2],[2,1],[1,1]]]}},
        {'type':'Feature','id':'002','properties':{'id':'different','a/b':{'~name':'B'},'capacity':None},'geometry':None}]
    source={'type':'FeatureCollection','features':features}
    ds=ingest(json.dumps(source).encode(),name='几何协议夹具',format='geojson',source='controlled-test-fixture')
    binding={'dataset_id':ds['dataset_id'],'port':'terrain','contract':{
        'kind':'geojson','purpose':'initialization','geometry':spec(),'primary_key':['id'],
        'fields':{'id':{'type':'string','unit':'1'},'name':{'type':'string','unit':'1'},
                  'capacity':{'type':'integer','unit':'1','nullable':True}}},
        'columns':{'id':{'field':'id'},'name':{'pointer':'/properties/a~1b/~0name'},
                   'capacity':{'pointer':'/properties/capacity'}}}
    inputs,evidence=prepare_structured([binding])
    assert inputs['terrain']['features']==features
    assert inputs['terrain']['columns']=={'id':['001','002'],'name':['A','B'],'capacity':[12,None]}
    assert inputs['terrain']['source_row_indices']==[0,1]
    summary=evidence[0]['geometry_summary']
    assert summary['positions']==10 and summary['null_or_empty_geometries']==1
    assert summary['projection'].startswith('none') and 'not_certified' in summary['validation']
    assert 'features' not in evidence[0]  # no complete private geometries in prompts
    wrong=deepcopy(binding)
    wrong['contract']['geometry'].update(crs='LOCAL_METERS',axes=['east','north'],units=['m','m'])
    with pytest.raises(ValueError,match='不能只改crs'):
        prepare_structured([wrong])
    for pointer in ('/properties/not_present','/properties/a~2b','/geometry/coordinates/01'):
        with pytest.raises(ValueError):pointer_value(features[0],pointer)


def test_geometry_rejects_axis_confusion_unclosed_rings_and_undeclared_dimensions():
    wrong=spec()
    wrong['units']=['m','m']
    with pytest.raises(ValueError,match='不能当作米'):geometry_contract(wrong)
    feature={'type':'Feature','properties':{},'geometry':{'type':'Point','coordinates':[120,95]}}
    with pytest.raises(ValueError,match='纬度'):features_summary([feature],spec())
    feature['geometry']['coordinates']=[120,30,10]
    with pytest.raises(ValueError,match='维度'):features_summary([feature],spec())
    xyz={**spec(),'axes':['longitude','latitude','source_defined_depth'],'units':['degree','degree','km']}
    assert features_summary([feature],geometry_contract(xyz))['dimensions']==[3]
    feature['geometry']={'type':'Polygon','coordinates':[[[0,0],[2,0],[2,2],[0,2]]]}
    with pytest.raises(ValueError,match='未闭合'):features_summary([feature],spec())
    feature['geometry']=None
    with pytest.raises(ValueError,match='缺失几何'):features_summary([feature],{**spec(),'allow_null':False})
    feature['geometry']={'type':'GeometryCollection','geometries':[{'type':'LineString','coordinates':[[0,0],[1,1]]},
                                                                 {'type':'MultiPoint','coordinates':[[2,2],[3,3]]}]}
    assert features_summary([feature],spec())['positions']==4


def test_geographic_requirement_needs_actual_geometry_binding_before_design(tmp_path,monkeypatch):
    from dayan.agent.model_tools import call_native_model
    from dayan.agent.tools import call_tool
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    request='依据真实场地建立路线仿真，保留真实空间几何。'
    result=call_native_model('design_model',{},request,'geography-contract-test')
    assert not result['ok'] and '实际geojson端口' in result['error'],result
    assert not result['llm_calls']
    guide=call_tool('modeling_guide',request=request)['payload']
    assert guide['real_inputs_required'] and 'collect_data' in guide['next_tools']['data']
    assert not any('尚须结构数据端口' in gap for gap in guide['program_engine']['blocked_by'])


@LIVE
def test_geometry_reaches_actual_solver_and_changes_independent_volume_oracle(tmp_path,monkeypatch):
    from pathlib import Path
    from dayan.custom_models import register
    from dayan.runtime import run_model_full
    from dayan.run_store import get_store
    from dayan.agent.scenario_tools import report_run
    from dayan.structured_inputs import structured_audit
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    monkeypatch.setenv('DAYAN_REPORTS_DIR',str(tmp_path/'reports'))
    import dayan.report_gen as report_gen
    monkeypatch.setattr(report_gen,'REPORTS_DIR',tmp_path/'reports')
    contract={'kind':'geojson','purpose':'initialization','fields':{},'geometry':{
        'crs':'LOCAL_CARTESIAN_TEST','axes':['east','north'],'units':['m','m'],
        'coordinate_evidence':'Constructed protocol fixture; not a surveyed site','allow_null':False}}
    def bind(hole):
        geo={'type':'FeatureCollection','features':[{'type':'Feature','id':'site-001','properties':{'source':'fixture'},
            'geometry':{'type':'Polygon','coordinates':[
                [[0,0],[4,0],[4,4],[0,4],[0,0]],[[0,0],[0,hole],[hole,hole],[hole,0],[0,0]]]}}]}
        ds=ingest(json.dumps(geo).encode(),name='含孔多边形数值夹具',format='geojson',source='controlled-test-fixture',
                  metadata={'crs':'LOCAL_CARTESIAN_TEST'})
        return {'dataset_id':ds['dataset_id'],'port':'site','contract':contract,'columns':{}}
    data=[bind(1)]
    definition={'kind':'program','name':'几何输入数值核验','description':'检查原几何影响积分，非测绘或现实水文仿真',
        'time_unit':'second','parameters':{'rain':{'type':'float','default':2.,'unit':'m/s'}},
        'input_ports':{'site':contract},'populations':[],
        'solver':{'method':'精确常速积分','description':'多边形净面积乘常数降雨率'},
        'source':'''def area(ring):
    return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(ring,ring[1:])))/2
def initialize(parameters,inputs,rng):
    rings=inputs["site"]["features"][0]["geometry"]["coordinates"]
    return {"area":area(rings[0])-sum(area(ring) for ring in rings[1:]),"volume":0.}
def advance(state,parameters,inputs,rng,time,dt):
    state["volume"]+=state["area"]*parameters["rain"]*dt
    return {"state":state,"events":[]}
def observe(state,parameters,inputs,time):
    return {"area":state["area"],"volume":state["volume"]}
def frame(state,parameters,inputs,time):
    return {"stocks":state}
def validate(state,parameters,inputs,time):
    if state["area"]<=0 or state["volume"]<0:raise ValueError("invalid area or volume")
''', 'observables':{'area':{'label':'净面积','unit':'m2','equation':'外环面积-内孔面积'},
                     'volume':{'label':'累计体积','unit':'m3','equation':'积分(A*r)'}},
        'equations':[{'id':'volume','expression':'dV/dt=A*r','function':'advance','meaning':'精确常量面积积分'}],
        'mechanisms':['原始多边形净面积控制累计速率'],'assumptions':['构造的二维米制坐标'],
        'limitations':['不证明真实地形或水文规律']}
    mid=register(definition)['model_id']
    full=run_model_full(mid,ticks=3,dt=1,seed=1,data_bindings=data,capture_state=True)
    assert [row['volume'] for row in full.observations]==[0,30,60,90]
    changed=run_model_full(mid,ticks=3,dt=1,seed=1,data_bindings=[bind(3)],capture_state=True)
    assert [row['volume'] for row in changed.observations]==[0,14,28,42]
    assert structured_audit(full.manifest,full.checkpoint)[0]['status']=='recomputed'
    rid=get_store().save_run(full,source='geometry_protocol_fixture',request_text='受控几何数值验算，非实际地形')
    report=report_run(rid,'volume')
    assert report['ok'],report
    facts=json.loads(Path(report['payload']['path']).with_suffix('.json').read_text(encoding='utf-8'))
    assert facts['research_evidence']['structured_data_audit'][0]['status']=='recomputed'
