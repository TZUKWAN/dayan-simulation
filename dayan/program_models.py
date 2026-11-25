"""Reviewed program definitions. Host validation parses code; it never imports it."""
from copy import deepcopy
import ast
import math

from .limits import limits
from .population_groups import NAME
from .solvers.codec import dumps
from .solvers.sandbox import validate_source

KINDS = ('numeric','nullable_numeric','categorical')


def _text(value, path):
    if not isinstance(value,str) or not value.strip():
        raise ValueError(path+'须为非空文字')
    return value


def parameter_value(name, value, spec):
    kind=spec['type']
    if kind in ('float','int'):
        if type(value) not in (int,float) or not math.isfinite(value):
            raise ValueError('参数'+name+'须为有限数值')
        if kind=='int' and int(value)!=value:
            raise ValueError('参数'+name+'须为整数，不得取整改变研究规模')
        if not spec.get('minimum',-float('inf'))<=value<=spec.get('maximum',float('inf')):
            raise ValueError('参数'+name+'超出声明边界')
        return int(value) if kind=='int' else float(value)
    if kind=='bool' and type(value) is bool or kind=='str' and isinstance(value,str):
        return value
    raise ValueError('参数'+name+'不符合声明类型'+kind)


def effective_parameters(definition, supplied=None):
    supplied=supplied or {}
    extra=set(supplied)-set(definition['parameters'])
    if extra:raise ValueError('程序模型没有这些参数：'+','.join(sorted(extra)))
    return {name:parameter_value(name,supplied.get(name,spec['default']),spec)
            for name,spec in definition['parameters'].items()}


def population_plan(definition, parameters=None, inputs=None, *, allow_unbound=False):
    from .custom_models import Expression
    values=effective_parameters(definition,parameters)
    counts=[]
    for group in definition['populations']:
        requested=group['count']
        if isinstance(requested,dict):
            port=requested.get('input_port')
            if set(requested)!={'input_port'} or port not in definition.get('input_ports',{}):
                raise ValueError('人口数量的input_port须引用实际声明端口')
            if inputs is None and allow_unbound:
                count=None
            elif inputs is None or port not in inputs:
                raise ValueError('人口规模需要绑定真实输入端口：'+port)
            else:
                count=inputs[port]['count']
        else:
            count=Expression(requested, values).value(values)
        if count is not None and (int(count)!=count or not 0<=count<=limits().array_entities):
            raise ValueError('人口组'+group['id']+'初始数量不满足整数/规模合同')
        counts.append({'id':group['id'],'label':group['label'],'count':int(count) if count is not None else None,
                       'dynamic':group['dynamic'],'type':group['type']})
    known_total=sum(row['count'] for row in counts if row['count'] is not None)
    if known_total>limits().array_entities:raise ValueError('程序模型初始人口总数超出当前预算')
    total=known_total if all(row['count'] is not None for row in counts) else None
    return {'kernel':'isolated-program-v1','entities':total,'populations':counts,'grid':None,
            'population_storage':'dayan-populations-v1'}


def validate_definition(value):
    d=deepcopy(value)
    allowed={'kind','name','description','time_unit','parameters','source','solver','observables',
             'populations','equations','mechanisms','assumptions','limitations','scenario','visualization','input_ports','state_every','decision_policy'}
    if not isinstance(d,dict) or d.get('kind')!='program' or set(d)-allowed:
        raise ValueError('程序模型kind/顶层字段不符合合同')
    for key in ('name','description','time_unit'):_text(d.get(key),key)
    if 'state_every' in d and (type(d['state_every']) is not int or d['state_every'] < 1):
        raise ValueError('state_every须为正整数宏步归档间隔；不改变计算步长、主体或观测')
    # Do not insert the optional field into historical content-addressed models.
    if 'input_ports' in d:
        from .structured_inputs import port_contracts
        d['input_ports']=port_contracts(d['input_ports'])
    tree=validate_source(d.get('source'))
    functions={node.name:node for node in tree.body if isinstance(node,ast.FunctionDef)}
    if 'decision_policy' in d:
        from .decision_broker import validate_policy
        d['decision_policy']=validate_policy(d['decision_policy'])
    expected={'initialize':3,'advance':7 if 'decision_policy' in d else 6,'observe':4,'frame':4,'validate':4}
    if 'decision_policy' in d:expected['decision_requests']=4
    for name,count in expected.items():
        if name not in functions:raise ValueError('缺少程序入口：'+name)
        fn=functions[name]
        if (fn.decorator_list or fn.args.vararg or fn.args.kwarg or fn.args.kwonlyargs or
                len(fn.args.posonlyargs)+len(fn.args.args)!=count):
            raise ValueError('程序函数'+name+'须有'+str(count)+'个明确的位置参数；不使用装饰器、可变参数或仅关键字参数')
    params=d.setdefault('parameters',{})
    if not isinstance(params,dict):raise ValueError('parameters须为对象')
    for name,spec in params.items():
        if (not isinstance(name,str) or not NAME.fullmatch(name) or not isinstance(spec,dict)
                or set(spec)-{'type','default','minimum','maximum','unit','label','mutable'}):
            raise ValueError('程序参数元数据不合法')
        if name in ('ticks','dt','seed'):raise ValueError('时钟与种子使用运行选项，不重复声明为模型参数')
        if spec.get('type') not in ('float','int','bool','str') or 'default' not in spec:
            raise ValueError('程序参数须声明类型和默认值')
        for key in ('minimum','maximum'):
            if key in spec and (type(spec[key]) not in (int,float) or not math.isfinite(spec[key])):
                raise ValueError('程序参数边界须为有限数字')
        if ('mutable' in spec and type(spec['mutable']) is not bool) or spec.get('mutable') and spec['type'] not in ('int','float'):
            raise ValueError('运行中参数须显式声明mutable=true且为数值控制量')
        _text(spec.get('unit'),'parameters.'+name+'.unit')
        parameter_value(name,spec['default'],spec)
    outputs=d.get('observables')
    if not isinstance(outputs,dict) or not outputs:raise ValueError('须明确声明程序实际观测量')
    for name,meta in outputs.items():
        if not isinstance(name,str) or not NAME.fullmatch(name) or name=='sim_t' or not isinstance(meta,dict):
            raise ValueError('程序观测量元数据不合法')
        if set(meta)-{'label','unit','equation'}:raise ValueError('观测量含未知字段')
        for key in ('label','unit','equation'):_text(meta.get(key),'observables.'+name+'.'+key)
    equations=d.get('equations')
    if not isinstance(equations,list) or not equations:raise ValueError('程序须保存数学表达及对应实现函数')
    used=set()
    for row in equations:
        if not isinstance(row,dict) or set(row)!={'id','expression','function','meaning'}:
            raise ValueError('方程须有id、expression、function和meaning')
        for key in row:_text(row[key],'equations.'+key)
        if row['id'] in used or row['function'] not in functions:raise ValueError('方程标识重复或对应函数不存在')
        used.add(row['id'])
    solver=d.get('solver')
    if not isinstance(solver,dict) or set(solver)-{'method','description','intervention_clock'} or not {'method','description'}<=set(solver):
        raise ValueError('solver须说明实际方法及数值误差/调度策略')
    for key in solver:_text(solver[key],'solver.'+key)
    solver.setdefault('intervention_clock','step')
    if solver['intervention_clock'] not in ('step','continuous'):
        raise ValueError('intervention_clock须为step（仅步边界）或continuous（在干预时点分段推进）')
    for key in ('mechanisms','assumptions','limitations'):
        if not isinstance(d.get(key),list) or any(not isinstance(x,str) or not x.strip() for x in d[key]):
            raise ValueError(key+'须为明确的文字列表')
    groups=d.get('populations')
    if not isinstance(groups,list):raise ValueError('须声明populations（无个体时显式为空列表）')
    used=set()
    for group in groups:
        if not isinstance(group,dict) or set(group)!={'id','label','type','count','dynamic','attributes'}:
            raise ValueError('人口组须声明id/label/type/count/dynamic/attributes')
        key=group['id']
        if not isinstance(key,str) or not NAME.fullmatch(key) or key in used:raise ValueError('人口组ID非法或重复')
        used.add(key)
        for field in ('label','type'):_text(group[field],'populations.'+key+'.'+field)
        if type(group['dynamic']) is not bool:raise ValueError('dynamic须为布尔值')
        attrs=group['attributes']
        if not isinstance(attrs,dict) or not attrs:raise ValueError('人口组须声明实际属性')
        for name,spec in attrs.items():
            path='populations.'+key+'.attributes.'+str(name)
            if not isinstance(name,str) or not NAME.fullmatch(name):
                raise ValueError(path+'：属性名须为英文标识')
            if name in ('id','type','group','local_id'):
                raise ValueError(path+'：这是保留字段；实际ID请写frame.populations[].ids，属性另取person_id等名称')
            if not isinstance(spec,dict) or set(spec)!={'kind','unit'} or spec['kind'] not in KINDS:
                raise ValueError(path+'：属性元数据须恰好kind/unit，kind为'+','.join(KINDS))
            if spec['unit'] is not None:_text(spec['unit'],'属性单位')
    population_plan(d,allow_unbound=True)
    from .program_scene import validate_scene
    validate_scene(d)
    if len(dumps(d).encode('utf-8'))>limits().body_bytes:raise ValueError('完整程序定义超过传输预算')
    return d


def intervention_schedule(definition, parameters, interventions, ticks, dt):
    """Resolve timed scalar operations once, retaining exact ordering and actual times."""
    if interventions is None:return []
    if not isinstance(interventions,list):raise ValueError('interventions须为列表')
    rows=[]
    for order,iv in enumerate(interventions):
        if (not isinstance(iv,dict) or set(iv)-{'at_t','t','params','label'} or
                not isinstance(iv.get('params'),dict) or not iv['params']):
            raise ValueError('每项干预须声明时刻与非空params')
        at=iv.get('at_t',iv.get('t',0.))
        if type(at) not in (int,float) or not math.isfinite(at) or not 0<=at<=ticks*dt:
            raise ValueError('干预时刻超出原定运行范围')
        if 'at_t' in iv and 't' in iv and iv['at_t']!=iv['t']:raise ValueError('干预时刻互相矛盾')
        actual=float(at)
        if definition['solver']['intervention_clock']=='step':
            boundary=round(at/dt)*dt
            if abs(boundary-at)>max(math.ulp(actual),math.ulp(float(boundary)))*4:
                raise ValueError('本程序声明离散步调度；步间干预须采用明确支持连续分段的求解实现')
            actual=boundary
        label=iv.get('label','参数干预')
        if not isinstance(label,str):raise ValueError('干预标签须为文字')
        rows.append({'at_t':actual,'requested_t':float(at),'params':deepcopy(iv['params']),'label':label,'order':order})
    current=deepcopy(parameters)
    for row in sorted(rows,key=lambda x:(x['at_t'],x['order'])):
        for name,value in row['params'].items():
            spec=definition['parameters'].get(name)
            if not spec or not spec.get('mutable'):raise ValueError('不能干预初始化或未声明参数：'+name)
            if isinstance(value,str):
                text=value.strip().replace('−','-')
                value=current[name]*float(text[1:]) if text.startswith('*') else (
                    current[name]+float(text) if text.startswith(('+','-')) else float(text))
            value=parameter_value(name,value,spec)
            current[name]=row['params'][name]=value
    return sorted(rows,key=lambda x:(x['at_t'],x['order']))


def factory_class(model_id, definition, review=None):
    # This is metadata only. No method from generated source is loaded on host.
    return type('Managed_'+model_id,(),{'model_id':model_id,'clock_type':'managed_program','definition':definition,
        'time_unit':definition['time_unit'],'scenario_review':review,
        'parameter_schema':{name:{**meta,'required':False} for name,meta in definition['parameters'].items()},
        'output_units':{name:meta['unit'] for name,meta in definition['observables'].items()},
        'external_dependencies':('managed_solver',)})
