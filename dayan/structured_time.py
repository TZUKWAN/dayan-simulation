"""Point-series contracts and checks; sampling runs only in the reviewed model."""
import math


def series_clock(clock, fields):
    keys={'field','origin','series_by','interpolation','outside','missing','max_gap'}
    if not isinstance(clock,dict) or set(clock)!=keys:
        raise ValueError('点时序clock须明确field/origin/series_by/interpolation/outside/missing/max_gap')
    field=fields.get(clock['field'])
    if not field or field['type'] not in ('number','integer') or field['nullable']:
        raise ValueError('点时序时刻须为不可缺失数值列')
    if not isinstance(clock['origin'],str) or not clock['origin'].strip():
        raise ValueError('点时序须说明时间原点/单位含义')
    groups=clock['series_by']
    if (not isinstance(groups,list) or any(not isinstance(k,str) or k not in fields or
            fields[k]['nullable'] or k==clock['field'] for k in groups) or len(set(groups))!=len(groups)):
        raise ValueError('series_by须为不可缺失的系列身份字段列表，不能包含时刻字段')
    policy=clock['interpolation']
    if not isinstance(policy,dict) or not policy:
        raise ValueError('点时序须逐列声明interpolation')
    for key,method in policy.items():
        if key not in fields or key in groups or key==clock['field'] or method not in ('linear','previous','exact'):
            raise ValueError('interpolation须引用实际取值列，方法为linear/previous/exact')
        if method=='linear' and fields[key]['type'] not in ('number','integer'):
            raise ValueError('linear仅适用数值列，不能给类别编码插值')
    if clock['outside'] not in ('error','hold') or clock['missing'] not in ('error','preserve'):
        raise ValueError('点时序须明确outside=error/hold与missing=error/preserve')
    gap=clock['max_gap']
    if gap is not None and (type(gap) not in (int,float) or not math.isfinite(gap) or gap<=0):
        raise ValueError('max_gap须为时钟单位的正数或明确null（不设间隔阈值）')
    return clock


def series_summary(clock, fields, columns):
    times=columns[clock['field']]
    if not times:
        raise ValueError('点时序输入没有实际记录')
    grouped={}
    for i,t in enumerate(times):
        key=tuple(columns[k][i] for k in clock['series_by'])
        samples=grouped.setdefault(key,[])
        if samples and t<=samples[-1]:
            raise ValueError('同一系列的时刻须严格递增且不重复；可显式order_by排序，不能自动合并重复观测')
        samples.append(t)
    gaps=[b-a for samples in grouped.values() for a,b in zip(samples,samples[1:])]
    if clock['max_gap'] is not None and any(gap>clock['max_gap'] for gap in gaps):
        raise ValueError('点时序记录间隔超过声明max_gap，不能跨缺测区间静默填补')
    if 'linear' in clock['interpolation'].values() and any(len(samples)<2 for samples in grouped.values()):
        raise ValueError('linear每个系列至少需要两个不同时刻')
    if clock['missing']=='error' and any(value is None for key in clock['interpolation'] for value in columns[key]):
        raise ValueError('点时序取值列含缺失，合同missing=error')
    return {'kind':'points','series':len(grouped),'records':len(times),'first_time':min(times),'last_time':max(times),
            'max_observed_gap':max(gaps,default=None),'unit':fields[clock['field']]['unit'],
            'interpolation':clock['interpolation'],'outside':clock['outside'],'missing':clock['missing'],
            'sampling_status':'not_resampled_on_host',
            'information_scope':'linear读取区间两端观测；回溯插值不证明未来数据在当时已知。previous也须另核验数据发布时刻。'}


def clock_schema():
    return {'type':'object','required':['field','origin','series_by','interpolation','outside','missing','max_gap'],
            'properties':{'field':{'type':'string'},'origin':{'type':'string','minLength':1},
                'series_by':{'type':'array','items':{'type':'string'},'uniqueItems':True},
                'interpolation':{'type':'object','minProperties':1,'additionalProperties':{'enum':['linear','previous','exact']}},
                'outside':{'enum':['error','hold']},'missing':{'enum':['error','preserve']},
                'max_gap':{'type':['number','null'],'exclusiveMinimum':0}}, 'additionalProperties':False,
            'description':'观测时点序列，不是区间。身份字段分组后时刻必须严格递增；取值/积分由审核后源码按合同实际执行，宿主不补值。linear使用两侧观测，不能自动用于在线/预测论证。'}
