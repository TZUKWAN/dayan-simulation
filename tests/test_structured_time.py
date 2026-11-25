"""Point forcing protocol fixtures; no claim of empirical validation."""
from copy import deepcopy
import pytest
import jsonschema

from dayan.structured_inputs import prepare_structured, binding_schema
from test_structured_inputs import dataset
from test_solver_sandbox import LIVE


def binding(rows, **policy):
    return {'dataset_id':dataset(rows),'port':'forcing','contract':{'kind':'timeseries','purpose':'exogenous_input',
        'fields':{'region':{'type':'string','unit':'1'},'t':{'type':'number','unit':'second'},
                  'rate':{'type':'number','unit':'m3/second','nullable':True}},
        'clock':{'field':'t','origin':'协议夹具相对秒','series_by':['region'],
                 'interpolation':{'rate':'linear'},'outside':'error','missing':'error','max_gap':4,**policy}},
        'columns':{'region':{'field':'region'},'t':{'field':'t','source_unit':'second'},
                   'rate':{'field':'rate','source_unit':'m3/second'}},'order_by':['region','t']}


def test_series_preserve_joint_rows_and_explicit_point_policy(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    rows=[{'region':'B','t':4,'rate':4},{'region':'A','t':0,'rate':1},
          {'region':'B','t':0,'rate':2},{'region':'A','t':2,'rate':3}]
    b=binding(rows)
    jsonschema.validate(b,binding_schema())
    inputs,evidence=prepare_structured([b])
    assert inputs['forcing']['source_row_indices']==[1,3,2,0]
    assert inputs['forcing']['columns']['rate']==[1,3,2,4]
    assert evidence[0]['time_summary']['series']==2
    assert evidence[0]['time_summary']['max_observed_gap']==4
    assert evidence[0]['time_summary']['sampling_status']=='not_resampled_on_host'
    for changed,pattern in (({'order_by':[]},'严格递增'),
                            ({'contract':{**b['contract'],'clock':{**b['contract']['clock'],'max_gap':1}}},'max_gap')):
        with pytest.raises(ValueError,match=pattern):prepare_structured([{**b,**changed}])


def test_duplicate_time_missing_and_category_interpolation_do_not_silently_pass(tmp_path,monkeypatch):
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path))
    duplicate=[{'region':'A','t':0,'rate':1},{'region':'A','t':0,'rate':2}]
    with pytest.raises(ValueError,match='不重复'):prepare_structured([binding(duplicate)])
    rows=[{'region':'A','t':0,'rate':None},{'region':'A','t':2,'rate':3}]
    with pytest.raises(ValueError,match='missing=error'):prepare_structured([binding(rows)])
    inputs,_=prepare_structured([binding(rows,missing='preserve')])
    assert inputs['forcing']['columns']['rate'][0] is None
    bad=binding(rows)
    bad['contract']['clock']['interpolation']={'region':'linear'}
    with pytest.raises(ValueError,match='interpolation'):prepare_structured([bad])
    bad=deepcopy(binding(rows))
    bad['contract']['clock']['interval']=20
    with pytest.raises(jsonschema.ValidationError):jsonschema.validate(bad,binding_schema())
    with pytest.raises(ValueError,match='点时序clock'):prepare_structured([bad])


SOURCE='''
from bisect import bisect_right
def series(inputs):
    columns=inputs["forcing"]["columns"]
    grouped={}
    for region,t,value in zip(columns["region"],columns["t"],columns["rate"]):
        grouped.setdefault(region,[]).append((t,value))
    return grouped
def sample(points,t,clock):
    times=[row[0] for row in points]
    if t<times[0] or t>times[-1]:
        if clock["outside"]=="error":raise ValueError("outside source coverage")
        value=points[0 if t<times[0] else -1][1]
    else:
        k=bisect_right(times,t)-1
        value=points[k][1]
        if t!=times[k]:
            method=clock["interpolation"]["rate"]
            if method=="exact":raise ValueError("no exact observation at requested time")
            if method=="linear":
                right=points[k+1][1]
                if value is None or right is None:raise ValueError("missing source value not imputed")
                value+=(right-value)*(t-times[k])/(times[k+1]-times[k])
    if value is None:raise ValueError("missing source value not imputed")
    return value
def initialize(parameters,inputs,rng):
    ids=list(series(inputs))
    return {"ids":ids,"integrals":[0.0 for _ in ids]}
def advance(state,parameters,inputs,rng,time,dt):
    clock=inputs["forcing"]["contract"]["clock"]
    groups=series(inputs)
    for i,key in enumerate(state["ids"]):
        points=groups[key]
        knots=[time]+[t for t,value in points if time<t<time+dt]+[time+dt]
        for a,b in zip(knots,knots[1:]):
            left=sample(points,a,clock)
            right=sample(points,b,clock)
            method=clock["interpolation"]["rate"]
            if method=="exact":raise ValueError("exact points alone do not define an interval integral")
            state["integrals"][i]+=(b-a)*(left+right)/2 if method=="linear" else (b-a)*left
    return {"state":state,"events":[]}
def observe(state,parameters,inputs,time):
    return {"integral":sum(state["integrals"])}
def frame(state,parameters,inputs,time):
    return {"populations":[{"id":"regions","type":"region","ids":state["ids"],
             "columns":{"integral":state["integrals"]},"units":{"integral":"INTEGRAL_UNIT"}}],"relations":[]}
def validate(state,parameters,inputs,time):
    if len(state["ids"])!=len(state["integrals"]):raise ValueError("mismatched regions")
'''


def definition(b, *, count=2, time_unit='second', integral_unit='m3'):
    return {'kind':'program','name':'明确点时序的区间积分数值验算','description':'按声明规则取值并跨真实观测时点分段积分',
        'time_unit':time_unit,'parameters':{},'input_ports':{'forcing':b['contract']},
        'source':SOURCE.replace('"INTEGRAL_UNIT"',repr(integral_unit)),
        'solver':{'method':'按观测时点分段积分','description':'linear分段梯形/previous左端值，范围外按明确合同'},
        'observables':{'integral':{'label':'累计积分','unit':integral_unit,'equation':'sum_i integral_0^t f_i(s) ds'}},
        'populations':[{'id':'regions','label':'实际系列','type':'region','count':count,'dynamic':False,
                        'attributes':{'integral':{'kind':'numeric','unit':integral_unit}}}],
        'equations':[{'id':'accumulation','function':'advance','expression':'I_i(t+dt)=I_i(t)+integral_t^(t+dt) f_i(s) ds',
                      'meaning':'源时序按声明策略插值，按实际观测时点拆分积分；不外推现实效度'}],
        'mechanisms':['完整点时序实际驱动累计状态'],'assumptions':['linear为回溯重建，端点间线性假设需另验证'],
        'limitations':['数值与输入链路检查，不是预测、因果或现实校准']}


@LIVE
def test_actual_point_forcing_crosses_knots_changes_with_input_and_enforces_coverage(tmp_path,monkeypatch):
    from dayan.custom_models import register
    from dayan.runtime import run_model_full,resume_from_checkpoint
    from dayan.solvers.sandbox import SolverError
    from dayan.structured_inputs import structured_audit
    monkeypatch.setenv('DAYAN_DATA_DIR',str(tmp_path/'data'))
    rows=[{'region':key,'t':t,'rate':(1+t if key=='A' else 2)} for key in ('A','B') for t in (0,2,5)]
    b=binding(rows,max_gap=3)
    mid=register(definition(b))['model_id']
    options={'ticks':2,'dt':2.5,'seed':4,'data_bindings':[b],'capture_state':True,'full_frames':True,'checkpoint_at':1}
    rr=run_model_full(mid,**options)
    assert [row['integral'] for row in rr.observations]==[0,10.625,27.5]
    assert rr.checkpoint['inputs']['forcing']['count']==6
    assert structured_audit(rr.manifest,rr.checkpoint)[0]['status']=='recomputed'
    resumed=resume_from_checkpoint(rr.checkpoint,steps=1,dt=2.5,capture_state=True)
    assert resumed.observations==rr.observations[-1:]
    changed=deepcopy(rows)
    for row in changed:
        if row['region']=='A':row['rate']+=1
    perturbed=run_model_full(mid,**{**options,'data_bindings':[binding(changed,max_gap=3)]})
    assert [row['integral'] for row in perturbed.observations]==[0,13.125,32.5]
    with pytest.raises(SolverError,match='outside source coverage'):
        run_model_full(mid,**{**options,'dt':3})
    previous=binding(rows,max_gap=3,interpolation={'rate':'previous'})
    constant=run_model_full(register(definition(previous))['model_id'],**{**options,'data_bindings':[previous]})
    assert [row['integral'] for row in constant.observations]==[0,8.5,21]
