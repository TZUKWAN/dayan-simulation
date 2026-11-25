"""Predeclared, resumable numerical diagnostics using real model executions.

Finite refinement checks are not convergence proofs. Stochastic comparisons use
actual replicate moments; no strong-convergence claim is made without a verified
coupled-noise protocol. Parameter sweeps/ablations are model comparisons, not
empirical causal identification.
"""
from bisect import bisect_left, bisect_right
from copy import deepcopy
import math
from pathlib import Path

from ..collection.storage import file_lock, read_json
from ..solvers.codec import digest
from ..structured_inputs import _finite, _name, _object, _text
from .model_evaluation import _sealed, evaluate_diagnostic, parameter_specs
from .model_studies import _read, _write, _verified_trial

CURRENT_COMPARISON_RULE='all_refinements_vs_baseline_v2'
LEGACY_COMPARISON_RULE='finest_vs_baseline_v1'


def diagnostic_execution_contract():
    return {'comparison_rule':CURRENT_COMPARISON_RULE,
        'reference':'first declared dt is the actual baseline; compare every later finer profile against it',
        'times':'actual common baseline observation times; no interpolation or nearest-time matching',
        'acceptance':'maximum over every finer profile, common time and output; deterministic uses individual seed changes, random mode uses mean and sample-SD changes plus Monte Carlo precision',
        'targets':'diagnostic trials do not score or use holdout target values for selection',
        'limits':'finite declared-resolution checks, not a convergence theorem, strong SDE convergence or global sensitivity'}


def diagnostic_schema():
    """Describe the same declaration fields accepted before a model exists."""
    name={'type':'string','pattern':r'^[A-Za-z][A-Za-z0-9_]{0,39}$'}
    text={'type':'string','minLength':1}
    positive={'type':'number','exclusiveMinimum':0}
    nonnegative={'type':'number','minimum':0}
    common={'id':name,'basis':text,'outputs':{'type':'object','minProperties':1,
        'propertyNames':name,'additionalProperties':{'type':'object',
            'properties':{'unit':text,'scale':positive},'required':['unit','scale'],'additionalProperties':False}}}
    def branch(kind,properties):
        props={**deepcopy(common),'kind':{'const':kind},**properties}
        return {'type':'object','properties':props,'required':list(props),'additionalProperties':False}
    time={'dts':{'type':'array','minItems':3,'items':positive},'max_scaled_change':nonnegative}
    return {'oneOf':[
        branch('time_refinement',{**time,'dynamics':{'const':'deterministic'}}),
        branch('time_refinement',{**time,'dynamics':{'const':'ensemble_moments'},'max_scaled_mc_se':nonnegative}),
        branch('parameter_sweep',{'parameter':name,'values':{'type':'array','minItems':2,'items':{'type':'number'}}}),
        branch('ablation',{'parameters':{'type':'object','minProperties':1,'propertyNames':name},
            'mechanism':text,'rule_refs':{'type':'array','minItems':1,'items':text,
                'description':'已确定的真实模型字段路径，例如rates.population、agents.update.state或source.advance；模型生成后严格核对。尚未选择模型时优先使用另一分支binding，不猜路径。'}}),
        branch('ablation',{'parameters':{'type':'object','minProperties':1,'propertyNames':name},
            'mechanism':text,'binding':{'type':'object','properties':{'kind':{'const':'approved_plan'}},
                'required':['kind'],'additionalProperties':False,
                'description':'科学消融事前冻结；在后续获审方案的diagnostic_bindings按同诊断id给rule_refs/reason，编译核真实动力学，MS保存两版及hash。与rule_refs互斥。'}})
    ],'description':'事前诊断。确定性模式为deterministic；随机矩模式为ensemble_moments且至少两个seed。'
                    'dynamics不是观测名。全部细化档与首档基线在共同物理时点比较，按全部差异最大值判定。'
                    '时钟、指标单位和参数绑定在准备时核对；实际参数范围及实现路径在模型生成后再核对。'}


def diagnostic_declarations(specifications,*,observables,execution,seeds,bound_parameters=()):
    """Validate all model-independent fields before freezing an authoring intent."""
    from ..runtime import validate_run_arguments
    if not isinstance(specifications,list):
        raise ValueError('diagnostics须为事前声明的列表')
    if not isinstance(seeds,list) or not seeds:
        raise ValueError('诊断种子须非空且不重复')
    for seed in seeds:validate_run_arguments(execution['ticks'],execution['dt'],seed)
    if len(set(seeds))!=len(seeds):raise ValueError('诊断种子须非空且不重复')
    result,names=[],set()
    common={'id','kind','basis','outputs'}
    for index,raw in enumerate(specifications):
        if not isinstance(raw,dict):raise ValueError('每项诊断须为对象')
        kind=raw.get('kind')
        if kind=='time_refinement' and raw.get('dynamics') not in ('deterministic','ensemble_moments'):
            raise ValueError(f'diagnostics[{index}].dynamics须为deterministic或ensemble_moments，'
                             '不是观测名；不能用相同seed冒充强收敛')
        extras=({'dts','dynamics','max_scaled_change','max_scaled_mc_se'} if kind=='time_refinement' else
                {'parameter','values'} if kind=='parameter_sweep' else
                {'parameters','mechanism','rule_refs','binding'} if kind=='ablation' else set())
        required=common|extras
        if kind=='time_refinement' and raw.get('dynamics')=='deterministic':required-= {'max_scaled_mc_se'}
        if kind=='ablation':
            if ('rule_refs' in raw)==('binding' in raw):
                raise ValueError('消融须且只能选择rule_refs或binding={kind:approved_plan}，未选模型时不猜实现路径')
            required-= {'binding'} if 'rule_refs' in raw else {'rule_refs'}
        if not extras:raise ValueError('诊断kind须为time_refinement/parameter_sweep/ablation')
        _object(raw,common|extras,required,'诊断')
        _name(raw['id'],'诊断id')
        if raw['id'] in names:raise ValueError('诊断id重复')
        names.add(raw['id'])
        _text(raw['basis'],'诊断事前依据')
        outputs=raw['outputs']
        if not isinstance(outputs,dict) or not outputs:raise ValueError('诊断outputs须非空')
        for name,spec in outputs.items():
            _name(name,'诊断指标名')
            _object(spec,('unit','scale'),('unit','scale'),'诊断指标尺度')
            if name not in observables or spec['unit']!=observables[name]['unit']:
                raise ValueError('诊断指标/单位须与实际模型声明一致')
            if _finite(spec['scale'],'诊断尺度')<=0:raise ValueError('诊断尺度须为正值')
        if kind=='time_refinement':
            dts=raw['dts']
            if (not isinstance(dts,list) or len(dts)<3 or dts[0]!=execution['dt']
                    or any(type(dt) not in (int,float) or not math.isfinite(dt) or dt<=0 for dt in dts)):
                raise ValueError('时间细化须至少三层，以当前实际dt开始且均为正有限数')
            for left,right in zip(dts,dts[1:]):
                ratio=left/right
                if ratio<2 or not math.isclose(ratio,round(ratio),rel_tol=1e-12,abs_tol=0):
                    raise ValueError('细化dt须为前一层的整数细分，保持真实共同观测点')
            horizon=execution['ticks']*execution['dt']
            for dt in dts:
                validate_run_arguments(round(horizon/dt),dt,seeds[0])
                if not math.isclose(round(horizon/dt)*dt,horizon,rel_tol=0,abs_tol=execution['time_atol']):
                    raise ValueError('细化不能改变物理仿真终点')
                if execution['time_atol']>=dt/4:
                    raise ValueError('原时点匹配容差过大，无法区分细化时点')
            if _finite(raw['max_scaled_change'],'事前细化差异阈值')<0:
                raise ValueError('细化差异阈值须非负')
            if raw['dynamics']=='ensemble_moments':
                if len(seeds)<2:raise ValueError('随机矩诊断需要至少两个实际独立重复')
                if _finite(raw['max_scaled_mc_se'],'事前蒙特卡洛精度阈值')<0:
                    raise ValueError('蒙特卡洛精度阈值须非负')
            elif 'max_scaled_mc_se' in raw:
                raise ValueError('确定性诊断不声明随机标准误阈值')
        elif kind=='parameter_sweep':
            name=raw['parameter']
            _name(name,'响应曲线参数')
            if name in bound_parameters:raise ValueError('响应曲线不能覆盖真实数据绑定参数')
            values=raw['values']
            if not isinstance(values,list) or len(values)<2:raise ValueError('响应曲线至少需要两个事前参数值')
            for value in values:_finite(value,'响应参数值')
            if any(b<=a for a,b in zip(values,values[1:])):raise ValueError('响应参数值须严格递增，不静默去重')
        else:
            values=raw['parameters']
            if not isinstance(values,dict) or not values:raise ValueError('消融须声明实际控制参数')
            for name in values:
                _name(name,'消融参数')
                if name in bound_parameters:raise ValueError('消融参数不能覆盖真实数据绑定')
            _text(raw['mechanism'],'消融机制')
            if 'binding' in raw:
                _object(raw['binding'],('kind',),('kind',),'消融后续绑定')
                if raw['binding']['kind']!='approved_plan':raise ValueError('消融后续绑定kind须为approved_plan')
                result.append(deepcopy(raw))
                continue
            refs=raw['rule_refs']
            if not isinstance(refs,list) or not refs or any(not isinstance(path,str) or not path.strip() for path in refs):
                raise ValueError('消融须引用实际实现规则')
            if not any(path.startswith(('source.','rates.','agents.update.')) for path in refs):
                raise ValueError('消融引用须包含实际行为/方程，不能只引用参数标签')
        result.append(deepcopy(raw))
    return result


def diagnostic_contract(evaluation,specifications,seeds):
    from ..program_models import parameter_value
    from ..scene_contract import reference
    _sealed(evaluation,'诊断所用研究合同')
    model=evaluation['model']
    result=diagnostic_declarations(specifications,observables=model['observables'],execution=evaluation['execution'],
                                   seeds=seeds,bound_parameters=evaluation['bound_parameters'])
    params=parameter_specs(model['definition'])
    for spec in result:
        if spec['kind']=='parameter_sweep':
            name=spec['parameter']
            if name not in params or params[name]['type'] not in ('int','float'):
                raise ValueError('响应曲线须使用未被真实数据绑定的实际数值参数')
            for value in spec['values']:parameter_value(name,value,params[name])
        elif spec['kind']=='ablation':
            if 'binding' in spec:
                raise ValueError('待定消融须由获审方案解析真实实现路径后才能执行，不能跳过diagnostic_bindings')
            for name,value in spec['parameters'].items():
                if name not in params:raise ValueError('消融参数不能不存在或覆盖真实数据绑定')
                parameter_value(name,value,params[name])
            for path in spec['rule_refs']:reference(model['definition'],path)
    return result


def _variants(spec,evaluation,parameters):
    dt=evaluation['execution']['dt']
    baseline={'label':'baseline','parameters':deepcopy(parameters),'dt':dt}
    if spec['kind']=='time_refinement':
        return [{**baseline,'label':f'dt_{i}','dt':step} for i,step in enumerate(spec['dts'])]
    if spec['kind']=='parameter_sweep':
        return [baseline,*[{'label':f'value_{i}','parameters':{**parameters,spec['parameter']:value},'dt':dt}
                            for i,value in enumerate(spec['values'])]]
    actual={name:meta['default'] for name,meta in parameter_specs(evaluation['model']['definition']).items()}
    actual.update(evaluation['execution']['parameters']);actual.update(parameters)
    if all(actual[name]==value for name,value in spec['parameters'].items()):
        raise ValueError('所选基准已经处于指定消融设置，不能把相同运行冒充消融比较')
    return [baseline,{'label':'ablated','parameters':{**parameters,**spec['parameters']},'dt':dt}]


def _retime(evaluation,dt):
    result=deepcopy(evaluation)
    execution=result['execution']
    horizon=execution['ticks']*execution['dt']
    execution.update(dt=dt,ticks=round(horizon/dt))
    result['sha256']=digest({key:value for key,value in result.items() if key!='sha256'})
    return result


def _schedule(specs,evaluation,parameters,seeds):
    jobs,comparisons={},[]
    for spec in specs:
        variants=[]
        for variant in _variants(spec,evaluation,parameters):
            keys=[]
            for seed in seeds:
                job={'parameters':variant['parameters'],'dt':variant['dt'],'seed':seed}
                key=digest(job)
                jobs.setdefault(key,job)
                keys.append(key)
            variants.append({**variant,'jobs':keys})
        comparisons.append({'specification':spec,'variants':variants})
    return jobs,comparisons


def _stats(values):
    n=len(values)
    mean=math.fsum(value/n for value in values)
    sd=math.sqrt(math.fsum((value-mean)**2 for value in values)/(n-1)) if n>1 else None
    return {'mean':mean,'sample_sd':sd,'mean_standard_error':sd/math.sqrt(n) if sd is not None else None,'values':values}


def _aligned(rows,times,outputs,atol):
    actual=[_finite(row.get('sim_t'),'诊断实际sim_t') for row in rows]
    if not actual or any(b<=a for a,b in zip(actual,actual[1:])):
        raise ValueError('诊断实际时钟不是严格递增')
    result=[]
    for t in times:
        lo,hi=bisect_left(actual,t-atol),bisect_right(actual,t+atol)
        if hi-lo!=1:raise ValueError('诊断缺少唯一真实共同时间点，不插值或截断')
        result.append({name:_finite(rows[lo].get(name),'诊断实际指标'+name) for name in outputs})
    return result


def _comparison(item,observations,atol,comparison_rule=CURRENT_COMPARISON_RULE):
    spec,variants=item['specification'],item['variants']
    outputs=spec['outputs']
    times=[row['sim_t'] for row in observations[variants[0]['jobs'][0]]]
    profiles=[]
    for variant in variants:
        samples=[_aligned(observations[key],times,outputs,atol) for key in variant['jobs']]
        profiles.append({'label':variant['label'],'dt':variant['dt'],'parameters':variant['parameters'],
            'points':[{'sim_t':t,'metrics':{name:_stats([sample[i][name] for sample in samples]) for name in outputs}}
                      for i,t in enumerate(times)]})
    baseline=profiles[0]
    differences=[]
    for profile in profiles[1:]:
        points=[]
        for before,after in zip(baseline['points'],profile['points']):
            metrics={}
            for name,unit in outputs.items():
                a,b=before['metrics'][name],after['metrics'][name]
                delta=_stats([y-x for x,y in zip(a['values'],b['values'])])
                metrics[name]={**delta,'scaled_mean_change':abs(delta['mean'])/unit['scale'],
                    'scaled_max_individual_change':max(abs(value) for value in delta['values'])/unit['scale'],
                    'scaled_sd_change':None if a['sample_sd'] is None else abs(b['sample_sd']-a['sample_sd'])/unit['scale'],
                    'scaled_mc_se':None if delta['mean_standard_error'] is None else delta['mean_standard_error']/unit['scale']}
            points.append({'sim_t':before['sim_t'],'metrics':metrics})
        differences.append({'label':profile['label'],'points':points})
    report={'id':spec['id'],'kind':spec['kind'],'specification':spec,'profiles':profiles,
            'differences_from_baseline':differences,'status':'observed',
            'scope':'实际模型比较，未使用留出目标误差；不是现实政策因果或参数可识别性证明'}
    if spec['kind']=='time_refinement':
        mode=spec['dynamics']
        compared=differences[-1:] if comparison_rule==LEGACY_COMPARISON_RULE else differences
        metrics=[metric for difference in compared for point in difference['points'] for metric in point['metrics'].values()]
        maximum=max(m['scaled_max_individual_change'] if mode=='deterministic' else
                    max(m['scaled_mean_change'],m['scaled_sd_change']) for m in metrics)
        precision=max(m['scaled_mc_se'] for m in metrics) if mode=='ensemble_moments' else None
        stable=maximum<=spec['max_scaled_change']
        precise=precision is None or precision<=spec['max_scaled_mc_se']
        orders=[]
        for a,b,c in zip(profiles,profiles[1:],profiles[2:]):
            ratio=a['dt']/b['dt']
            same_ratio=math.isclose(ratio,b['dt']/c['dt'],rel_tol=1e-12,abs_tol=0)
            for pa,pb,pc in zip(a['points'],b['points'],c['points']):
                for name in outputs:
                    va,vb,vc=(p['metrics'][name] for p in (pa,pb,pc))
                    e1,e2=va['mean']-vb['mean'],vb['mean']-vc['mean']
                    across_seeds=all(max(p['values'])==min(p['values']) for p in (va,vb,vc))
                    p=math.log(abs(e1/e2))/math.log(ratio) if (mode=='deterministic' and across_seeds and
                        same_ratio and e1*e2>0 and abs(e1)>abs(e2)) else None
                    orders.append({'sim_t':pa['sim_t'],'observable':name,'dts':[a['dt'],b['dt'],c['dt']],
                                   'empirical_order':p,'scope':'三层差分估计；退化/非单调/有跨seed波动时不报告阶'})
        report.update(status='within_declared_resolution_checks' if stable and precise else 'failed_resolution_checks',
            max_scaled_change=maximum,max_scaled_mc_se=precision,empirical_orders=orders,
            strong_convergence='not_established',
            scope='有限步长/时点上的数值稳定性检查，非全局收敛定理；随机模式仅比较实际样本矩，不假设共同Brownian路径')
        if comparison_rule!=LEGACY_COMPARISON_RULE:report['comparison_rule']=comparison_rule
    elif spec['kind']=='parameter_sweep':
        secants=[]
        for i,(left,right) in enumerate(zip(profiles[1:],profiles[2:])):
            dx=spec['values'][i+1]-spec['values'][i]
            secants.append({'parameter_interval':[spec['values'][i],spec['values'][i+1]],
                'points':[{'sim_t':a['sim_t'],'mean_secant':{name:(b['metrics'][name]['mean']-a['metrics'][name]['mean'])/dx
                    for name in outputs}} for a,b in zip(left['points'],right['points'])]})
        report.update(secants=secants,scope='固定其他参数的单参数响应与区间割线；不是全局敏感性或解析导数')
    else:
        report['scope']='声明控制参数下的实际模型消融比较；是否切断完整机制须对照已审查源码，不自动证明现实政策因果'
    return report


def _protocol(evaluation,parameters,specifications,seeds,comparison_rule):
    if comparison_rule not in (CURRENT_COMPARISON_RULE,LEGACY_COMPARISON_RULE):
        raise ValueError('未知数值诊断比较规则版本')
    specs=diagnostic_contract(evaluation,specifications,seeds)
    jobs,comparisons=_schedule(specs,evaluation,parameters,seeds)
    return {'evaluation_sha256':evaluation['sha256'],'parameters':deepcopy(parameters),'seeds':seeds,
            'specifications':specs,'jobs':jobs,'comparisons':comparisons,
            **({'comparison_rule':comparison_rule} if comparison_rule!=LEGACY_COMPARISON_RULE else {})}


def load_diagnostics(evaluation,parameters,specifications,seeds,*,directory,comparison_rule=None):
    """Read-only verification against the immutable plan and actual trial files."""
    folder=Path(directory)
    saved=_read(folder/'protocol.json','固定诊断协议')
    comparison_rule=comparison_rule or saved.get('comparison_rule',LEGACY_COMPARISON_RULE)
    protocol=_protocol(evaluation,parameters,specifications,seeds,comparison_rule)
    if {key:value for key,value in saved.items() if key!='sha256'}!=protocol:
        raise ValueError('诊断协议不属于研究所选模型、参数和事前设置')
    result=_read(folder/'result.json','实际诊断结果')
    jobs=protocol['jobs']
    if (result['protocol_sha256']!=saved['sha256'] or result['total_trials']!=len(jobs)
            or result['completed_trials']!=len(result['trials'])
            or list(result['trials'])!=list(jobs)[:len(result['trials'])]):
        raise ValueError('诊断结果与固定试验计划不一致')
    observations={}
    for key,row in result['trials'].items():
        relative=Path(row['directory'])
        path=(folder/relative).resolve()
        root=(folder/'trials'/key).resolve()
        if relative.is_absolute() or path.parent!=root or not path.name.startswith('attempt-'):
            raise ValueError('诊断证据路径越界')
        receipt=_verified_trial(path)
        job=jobs[key]
        if (receipt['sha256']!=row['sha256'] or receipt['status']!=row['status']
                or receipt['parameters']!=job['parameters'] or receipt['seed']!=job['seed']
                or receipt['role']!='diagnostic' or receipt['model_id']!=evaluation['model']['model_id']
                or receipt['contract_sha256']!=_retime(evaluation,job['dt'])['sha256']):
            raise ValueError('诊断实际运行证据与固定合同不一致')
        if receipt['status']=='executed':
            observations[key]=read_json(path/'observations.json')
    failed=any(row['status']!='executed' for row in result['trials'].values())
    reports=[]
    status='failed' if failed else 'running'
    if not failed and len(observations)==len(jobs):
        reports=[_comparison(item,observations,evaluation['execution']['time_atol'],comparison_rule)
                 for item in protocol['comparisons']]
        status='failed' if any(item['status']=='failed_resolution_checks' for item in reports) else 'complete'
    if result['status']!=status or result['reports']!=reports:
        raise ValueError('诊断报告未由实际试验按事前规则计算')
    return result


def advance_diagnostics(evaluation,parameters,specifications,seeds,*,directory,max_evaluations=1,
                        comparison_rule=CURRENT_COMPARISON_RULE):
    """Resume real trials; successful identical jobs are shared across diagnostics."""
    if type(max_evaluations) is not int or max_evaluations<1:raise ValueError('诊断求值预算须为正整数')
    protocol=_protocol(evaluation,parameters,specifications,seeds,comparison_rule)
    jobs,comparisons=protocol['jobs'],protocol['comparisons']
    folder=Path(directory)
    with file_lock(folder/'diagnostics.lock',timeout=.1):
        if (folder/'protocol.json').exists():
            old=_read(folder/'protocol.json','固定诊断协议')
            if {key:value for key,value in old.items() if key!='sha256'}!=protocol:
                raise ValueError('诊断协议/模型/所选参数已改变，不能复用旧试验')
        else:_write(folder/'protocol.json',protocol)
        receipts,observations={},{}
        evaluations=0
        for key,job in jobs.items():
            root=folder/'trials'/key
            attempts=sorted(root.glob('attempt-*'))
            finished=[path for path in attempts if (path/'result.json').is_file()]
            variant=_retime(evaluation,job['dt'])
            if finished:
                attempt=finished[-1]
                receipt=_verified_trial(attempt)
            elif evaluations<max_evaluations:
                attempt=root/f'attempt-{len(attempts)+1:06d}'
                receipt=evaluate_diagnostic(variant,parameters=job['parameters'],seed=job['seed'],directory=attempt)
                evaluations+=1
            else:break
            if (receipt['parameters']!=job['parameters'] or receipt['seed']!=job['seed'] or
                    receipt['role']!='diagnostic' or receipt['contract_sha256']!=variant['sha256']):
                raise ValueError('实际诊断试验不属于固定合同')
            receipts[key]={'directory':attempt.relative_to(folder).as_posix(),'sha256':receipt['sha256'],
                           'status':receipt['status'],'error':receipt.get('error')}
            if receipt['status']!='executed':break
            rows=read_json(attempt/'observations.json')
            expected=evaluation['execution']['ticks']*evaluation['execution']['dt']
            if abs(rows[-1]['sim_t']-expected)>evaluation['execution']['time_atol']:
                raise ValueError('实际诊断未执行到相同物理终点')
            observations[key]=rows
        failed=any(row['status']!='executed' for row in receipts.values())
        state={'protocol_sha256':digest(protocol),'completed_trials':len(receipts),'total_trials':len(jobs),
               'trials':receipts,'status':'failed' if failed else 'running','reports':[]}
        if not failed and len(receipts)==len(jobs):
            state['reports']=[_comparison(item,observations,evaluation['execution']['time_atol'],comparison_rule) for item in comparisons]
            state['status']='failed' if any(item['status']=='failed_resolution_checks' for item in state['reports']) else 'complete'
        saved=_write(folder/'result.json',state)
    return {**saved,'new_evaluations':evaluations}
